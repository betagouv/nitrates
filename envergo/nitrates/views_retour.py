"""Endpoint de collecte des retours utilisateurs (#284/#287).

Premier endpoint POST du simulateur nitrates (tout le reste est en GET
stateless). Le front (popup feedback fin de simulation, capture email région
fermée) poste ici en JSON avec le token CSRF. Rate-limité par IP.
"""

import json

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import View
from django_ratelimit.decorators import ratelimit

from envergo.nitrates.forms_retour import RetourUtilisateurForm


@method_decorator(
    ratelimit(key="ip", rate="10/m", method="POST", block=True), name="dispatch"
)
@method_decorator(require_POST, name="dispatch")
class RetourUtilisateurCreateView(View):
    """POST /api/retour/ : enregistre un retour utilisateur.

    Corps JSON attendu (selon le type) :
      { "type": "feedback", "note": 4, "commentaire": "...",
        "email": "a@b.fr", "consentement_email": true, "region_code": "44",
        "contexte": { ... anonyme ... } }
      { "type": "interet_region", "email": "a@b.fr",
        "consentement_email": true, "region_code": "27" }

    Réponses : 201 {ok:true, id}, 400 {ok:false, errors}, 415 si non-JSON.
    Protégé par CSRF (le front envoie le token dans l'en-tête X-CSRFToken).
    """

    def post(self, request, *args, **kwargs):
        content_type = (request.content_type or "").split(";")[0].strip()
        if content_type != "application/json":
            return JsonResponse(
                {"ok": False, "error": "Content-Type application/json attendu."},
                status=415,
            )
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({"ok": False, "error": "JSON illisible."}, status=400)
        if not isinstance(payload, dict):
            return JsonResponse(
                {"ok": False, "error": "Objet JSON attendu."}, status=400
            )

        form = RetourUtilisateurForm(payload)
        if not form.is_valid():
            return JsonResponse({"ok": False, "errors": form.errors}, status=400)

        retour = form.save()
        return JsonResponse({"ok": True, "id": retour.pk}, status=201)
