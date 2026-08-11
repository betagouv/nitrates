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

        # Attachement d'email à un retour existant (#284, volet email séquentiel) :
        # si `retour_id` est fourni, on ne crée pas une 2e ligne, on ajoute
        # seulement l'email (avec consentement) au feedback déjà envoyé. Ainsi la
        # note/commentaire et l'email restent découplés côté UX sans dupliquer.
        retour_id = payload.get("retour_id")
        if retour_id:
            return self._attacher_email(payload, retour_id)

        form = RetourUtilisateurForm(payload)
        if not form.is_valid():
            return JsonResponse({"ok": False, "errors": form.errors}, status=400)

        retour = form.save()
        return JsonResponse({"ok": True, "id": retour.pk}, status=201)

    def _attacher_email(self, payload, retour_id):
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError

        from envergo.nitrates.models_retour import RetourUtilisateur

        email = (payload.get("email") or "").strip()
        consent = bool(payload.get("consentement_email"))
        # RGPD : pas d'email sans consentement.
        if not email or not consent:
            return JsonResponse(
                {"ok": False, "errors": {"email": ["Email + consentement requis."]}},
                status=400,
            )
        try:
            validate_email(email)
        except ValidationError:
            return JsonResponse(
                {"ok": False, "errors": {"email": ["Email invalide."]}}, status=400
            )
        try:
            retour = RetourUtilisateur.objects.get(pk=retour_id)
        except (RetourUtilisateur.DoesNotExist, ValueError, TypeError):
            return JsonResponse(
                {"ok": False, "error": "Retour introuvable."}, status=404
            )
        retour.email = email
        retour.consentement_email = True
        retour.save(update_fields=["email", "consentement_email"])
        return JsonResponse({"ok": True, "id": retour.pk}, status=200)
