"""Point d'entrée HTTP du serveur MCP (cf. envergo.nitrates.mcp).

POST /mcp/ : un message (ou un lot) JSON-RPC, réponse JSON. GET et DELETE
répondent 405 : le transport « Streamable HTTP » le prévoit pour un serveur
qui n'ouvre pas de flux SSE ni de session.

Sans authentification ni CSRF : les clients sont des serveurs d'assistants
(ChatGPT, Le Chat...) et tout ce qui est exposé est déjà public. Lecture seule,
appels d'outils limités par IP. Derrière le flag NITRATES_MCP : 404 sinon.
"""

import json
import logging

from django.conf import settings
from django.db import transaction
from django.http import Http404, HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from django_ratelimit.core import is_ratelimited

from envergo.nitrates.mcp.protocole import CLE_IMAGE, traiter_corps

logger = logging.getLogger(__name__)

# 30 appels d'outils par minute et par IP. A revoir avant toute ouverture
# large : les appels de ChatGPT partent d'adresses partagees entre ses
# utilisateurs.
LIMITE_APPELS_OUTILS = "30/m"

# Les inspecteurs MCP tournent dans le navigateur : on autorise le CORS. Aucun
# cookie n'est lu, donc rien a proteger cote origine.
ENTETES_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": (
        "Content-Type, Accept, Mcp-Session-Id, Mcp-Protocol-Version"
    ),
    "Access-Control-Expose-Headers": "Mcp-Session-Id",
}


def _reponse(contenu=None, status=200):
    if contenu is None:
        reponse = HttpResponse(status=status)
    else:
        reponse = HttpResponse(
            json.dumps(contenu, ensure_ascii=False),
            status=status,
            content_type="application/json; charset=utf-8",
        )
    for cle, valeur in ENTETES_CORS.items():
        reponse[cle] = valeur
    return reponse


def _messages(request) -> list:
    try:
        messages = json.loads(request.body or b"")
    except (ValueError, UnicodeDecodeError):
        return []
    messages = messages if isinstance(messages, list) else [messages]
    return [m for m in messages if isinstance(m, dict)]


def _journaliser(messages, request):
    """Une ligne par message : méthode, outil, et si l'appel vient d'un
    navigateur (en-tête Origin) ou du serveur de l'assistant. Sert à
    comprendre comment chaque hôte enchaîne ses appels."""
    for message in messages:
        logger.info(
            "MCP %s %s origine=%s",
            message.get("method"),
            (message.get("params") or {}).get("name") or "",
            request.headers.get("Origin", "-"),
        )


def _trop_d_appels(messages, request) -> bool:
    """Limite sur les seuls appels d'outils (ceux qui coûtent : géographie,
    simulation). L'application ChatGPT rouvre une session à chaque appel
    (server/discover, initialize, notification, puis l'appel) : limiter
    toutes les requêtes revenait à diviser la limite par quatre."""
    if not any(m.get("method") == "tools/call" for m in messages):
        return False
    return is_ratelimited(
        request,
        group="nitrates-mcp-outils",
        key="ip",
        rate=LIMITE_APPELS_OUTILS,
        increment=True,
    )


@method_decorator(csrf_exempt, name="dispatch")
class McpView(View):
    http_method_names = ["get", "post", "delete", "options"]

    @classmethod
    def as_view(cls, **initkwargs):
        # Lecture seule : pas de transaction par requete (ATOMIC_REQUESTS),
        # dont le COMMIT sur une connexion perdue tournait en erreur 500.
        return transaction.non_atomic_requests(super().as_view(**initkwargs))

    def dispatch(self, request, *args, **kwargs):
        if not getattr(settings, "NITRATES_MCP", False):
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        messages = _messages(request)
        _journaliser(messages, request)
        if _trop_d_appels(messages, request):
            return _reponse(
                {
                    "jsonrpc": "2.0",
                    "id": messages[0].get("id"),
                    "error": {
                        "code": -32000,
                        "message": "Trop d'appels : réessayer dans une minute.",
                    },
                },
                status=429,
            )
        base_url = request.build_absolute_uri("/").rstrip("/")
        reponse = traiter_corps(request.body, base_url)
        if reponse is None:
            # Notification ou reponse du client : accuse de reception seul.
            return _reponse(status=202)
        return _reponse(reponse)

    def get(self, request, *args, **kwargs):
        reponse = _reponse(status=405)
        reponse["Allow"] = "POST, OPTIONS"
        return reponse

    delete = get

    def options(self, request, *args, **kwargs):
        return _reponse(status=204)


class ImageMcpView(View):
    """GET /mcp/image/<cle>.png : image (carte, calendrier) renvoyée par un
    outil, servie par lien pour les clients qui n'affichent pas le contenu
    image du résultat. Gardée 7 jours en cache, 404 ensuite."""

    def get(self, request, cle):
        if not getattr(settings, "NITRATES_MCP", False):
            raise Http404
        from django.core.cache import cache

        png = cache.get(CLE_IMAGE.format(cle))
        if png is None:
            raise Http404
        reponse = HttpResponse(png, content_type="image/png")
        reponse["Cache-Control"] = "public, max-age=86400"
        return reponse


class IconeMcpView(View):
    """GET /mcp/icone.png : pictogramme du serveur (serverInfo.icons)."""

    def get(self, request):
        if not getattr(settings, "NITRATES_MCP", False):
            raise Http404
        from envergo.nitrates.mcp import vue

        reponse = HttpResponse(vue.icone_png(), content_type="image/png")
        reponse["Cache-Control"] = "public, max-age=86400"
        return reponse
