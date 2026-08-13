"""Tests de l'endpoint de collecte des retours utilisateurs (#284/#287/#285)."""

import json

import pytest
from django.urls import reverse

from envergo.nitrates.models_retour import RetourUtilisateur

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]


def _post(client, payload):
    return client.post(
        reverse("nitrates_retour"),
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_feedback_avec_email_et_consentement(client):
    resp = _post(
        client,
        {
            "type": "feedback",
            "note": 4,
            "commentaire": "Très utile",
            "email": "alpha@test.fr",
            "consentement_email": True,
            "region_code": "44",
            "contexte": {"resultat": "autorise"},
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["ok"] is True
    r = RetourUtilisateur.objects.get(pk=data["id"])
    assert r.type == RetourUtilisateur.Type.FEEDBACK
    assert r.note == 4
    assert r.email == "alpha@test.fr"
    assert r.consentement_email is True
    # Le contexte ne doit contenir que de l'anonyme (pas de lat/lng).
    assert "lat" not in r.contexte and "lng" not in r.contexte


def test_feedback_email_sans_consentement_est_ignore(client):
    """RGPD : email fourni mais case non cochée -> email ignoré, retour créé."""
    resp = _post(
        client,
        {
            "type": "feedback",
            "note": 1,
            "email": "x@y.fr",
            "consentement_email": False,
        },
    )
    assert resp.status_code == 201
    r = RetourUtilisateur.objects.get(pk=resp.json()["id"])
    assert r.note == 1
    assert r.email == ""
    assert r.consentement_email is False


def test_feedback_toute_note_acceptee_meme_basse(client):
    """L'email est demandé quelle que soit la note (décision équipe : on capte
    aussi les mauvaises notes)."""
    resp = _post(
        client,
        {
            "type": "feedback",
            "note": 0,
            "email": "mecontent@test.fr",
            "consentement_email": True,
        },
    )
    assert resp.status_code == 201
    r = RetourUtilisateur.objects.get(pk=resp.json()["id"])
    assert r.note == 0
    assert r.email == "mecontent@test.fr"


def test_feedback_sans_note_refuse(client):
    resp = _post(client, {"type": "feedback", "commentaire": "coucou"})
    assert resp.status_code == 400
    assert "note" in resp.json()["errors"]


def test_note_hors_bornes_refusee(client):
    resp = _post(client, {"type": "feedback", "note": 9})
    assert resp.status_code == 400
    assert "note" in resp.json()["errors"]


def test_interet_region_avec_email(client):
    resp = _post(
        client,
        {
            "type": "interet_region",
            "email": "curieux@test.fr",
            "consentement_email": True,
            "region_code": "27",
        },
    )
    assert resp.status_code == 201
    r = RetourUtilisateur.objects.get(pk=resp.json()["id"])
    assert r.type == RetourUtilisateur.Type.INTERET_REGION
    assert r.email == "curieux@test.fr"
    assert r.region_code == "27"


def test_interet_region_sans_email_refuse(client):
    resp = _post(client, {"type": "interet_region", "region_code": "27"})
    assert resp.status_code == 400
    assert "email" in resp.json()["errors"]


def test_attacher_email_a_un_feedback_existant(client):
    """#284 volet email séquentiel : on crée d'abord un feedback (note seule),
    puis on lui attache l'email via retour_id, sans créer de 2e ligne."""
    r1 = _post(client, {"type": "feedback", "note": 5, "commentaire": "super"})
    assert r1.status_code == 201
    rid = r1.json()["id"]
    n_avant = RetourUtilisateur.objects.count()

    r2 = _post(
        client,
        {"retour_id": rid, "email": "tard@test.fr", "consentement_email": True},
    )
    assert r2.status_code == 200
    # Pas de nouvelle ligne : on a mis à jour l'existante.
    assert RetourUtilisateur.objects.count() == n_avant
    r = RetourUtilisateur.objects.get(pk=rid)
    assert r.email == "tard@test.fr"
    assert r.consentement_email is True
    assert r.note == 5  # inchangé


def test_attacher_email_sans_consentement_refuse(client):
    r1 = _post(client, {"type": "feedback", "note": 3})
    rid = r1.json()["id"]
    r2 = _post(
        client,
        {"retour_id": rid, "email": "x@y.fr", "consentement_email": False},
    )
    assert r2.status_code == 400


def test_attacher_email_retour_inexistant(client):
    resp = _post(
        client,
        {"retour_id": 999999, "email": "x@y.fr", "consentement_email": True},
    )
    assert resp.status_code == 404


def test_bug_signalement_sans_note_ni_email(client):
    """#285 : un signalement bug n'exige ni note ni email. On enregistre le
    commentaire + le contexte technique dumpé par le navigateur."""
    resp = _post(
        client,
        {
            "type": "bug",
            "commentaire": "Le bouton Suivant ne réagit pas.",
            "contexte": {
                "url": "https://exemple.fr/simulateur",
                "user_agent": "Mozilla/5.0",
                "sous_type": "bug",
                "console": [
                    {"level": "error", "message": "boom", "t": "2026-08-13T10:00:00Z"}
                ],
                "network": [{"method": "GET", "url": "/x", "status": 500}],
            },
        },
    )
    assert resp.status_code == 201
    r = RetourUtilisateur.objects.get(pk=resp.json()["id"])
    assert r.type == RetourUtilisateur.Type.BUG
    assert r.note is None
    assert r.email == ""
    assert r.commentaire == "Le bouton Suivant ne réagit pas."
    assert r.contexte["sous_type"] == "bug"
    assert r.contexte["console"][0]["level"] == "error"
    assert r.contexte["network"][0]["status"] == 500


def test_bug_ignore_email_sans_consentement(client):
    """RGPD : même sur un bug, un email sans consentement est ignoré."""
    resp = _post(
        client,
        {
            "type": "bug",
            "commentaire": "souci",
            "email": "x@y.fr",
            "consentement_email": False,
        },
    )
    assert resp.status_code == 201
    r = RetourUtilisateur.objects.get(pk=resp.json()["id"])
    assert r.email == ""


def test_get_refuse(client):
    resp = client.get(reverse("nitrates_retour"))
    assert resp.status_code == 405


def test_non_json_refuse(client):
    # Content-Type form-urlencoded (défaut du test client) -> refusé (415).
    resp = client.post(reverse("nitrates_retour"), data={"type": "feedback", "note": 3})
    assert resp.status_code == 415
