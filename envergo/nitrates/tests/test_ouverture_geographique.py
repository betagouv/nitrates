"""Tests du bornage géographique du simulateur (carte #57).

Couvre :
  - modèle + helper departement_est_ouvert (allowlist, fermé par défaut)
  - seed initial : Grand Est ouvert, reste fermé, 101 départements
  - vue localisation (DebugView) expose simulateur_ouvert
  - admin : toggle d'un département persiste, toggle région en masse
"""

import pytest
from django.test import Client

from envergo.nitrates.models import DepartementOuverture, departement_est_ouvert
from envergo.users.models import User

pytestmark = pytest.mark.django_db


# ─── Seed (migration data 0019) ─────────────────────────────────────────────


def test_seed_101_departements():
    assert DepartementOuverture.objects.count() == 101


def test_seed_grand_est_ouvert():
    ouverts = set(
        DepartementOuverture.objects.filter(est_ouvert=True).values_list(
            "code", flat=True
        )
    )
    assert ouverts == {"08", "10", "51", "52", "54", "55", "57", "67", "68", "88"}


def test_seed_reste_ferme():
    # Un département hors Grand Est est fermé.
    assert not DepartementOuverture.objects.get(code="75").est_ouvert
    assert not DepartementOuverture.objects.get(code="971").est_ouvert


def test_seed_inclut_drom():
    for code in ("971", "972", "973", "974", "976"):
        assert DepartementOuverture.objects.filter(code=code).exists()


# ─── Helper allowlist ───────────────────────────────────────────────────────


def test_helper_grand_est_ouvert():
    assert departement_est_ouvert("57") is True


def test_helper_hors_grand_est_ferme():
    assert departement_est_ouvert("75") is False


def test_helper_none_ferme():
    assert departement_est_ouvert(None) is False
    assert departement_est_ouvert("") is False


def test_helper_inconnu_ferme():
    # Code absent de la table -> fermé par défaut (allowlist).
    assert departement_est_ouvert("999") is False


# ─── Vue localisation (DebugView) ───────────────────────────────────────────


def test_debug_view_expose_simulateur_ouvert(client):
    # Sans département résolu (point en mer), simulateur_ouvert doit être False.
    r = client.get("/simulateur/debug/?lng=-30&lat=30")
    assert r.status_code == 200
    data = r.json()
    assert "simulateur_ouvert" in data
    assert data["simulateur_ouvert"] is False


# ─── Admin ──────────────────────────────────────────────────────────────────


@pytest.fixture
def staff_client(db):
    u = User.objects.create(
        email="geo@test.local", is_staff=True, is_superuser=True, is_active=True
    )
    c = Client()
    c.force_login(u)
    return c


def test_admin_index_accessible(staff_client):
    r = staff_client.get("/admin/nitrates/ouverture-geographique/")
    assert r.status_code == 200
    assert b"Ouverture" in r.content


def test_admin_index_refuse_non_staff(client):
    r = client.get("/admin/nitrates/ouverture-geographique/")
    # staff_member_required -> redirect login.
    assert r.status_code in (302, 403)


def test_toggle_ouvre_un_departement(staff_client):
    assert not departement_est_ouvert("75")
    r = staff_client.post(
        "/admin/nitrates/ouverture-geographique/toggle/",
        {"code": "75", "est_ouvert": "true"},
    )
    assert r.status_code == 204
    assert departement_est_ouvert("75") is True


def test_toggle_ferme_un_departement(staff_client):
    assert departement_est_ouvert("57")
    r = staff_client.post(
        "/admin/nitrates/ouverture-geographique/toggle/",
        {"code": "57", "est_ouvert": "false"},
    )
    assert r.status_code == 204
    assert departement_est_ouvert("57") is False


def test_toggle_code_inconnu_400(staff_client):
    r = staff_client.post(
        "/admin/nitrates/ouverture-geographique/toggle/",
        {"code": "999", "est_ouvert": "true"},
    )
    assert r.status_code == 400


def test_toggle_params_invalides_400(staff_client):
    r = staff_client.post(
        "/admin/nitrates/ouverture-geographique/toggle/",
        {"code": "75", "est_ouvert": "peut-etre"},
    )
    assert r.status_code == 400


def test_toggle_region_ouvre_toute_la_region(staff_client):
    # Île-de-France (R11) : tout fermé au départ.
    idf = DepartementOuverture.objects.filter(region_code="11")
    assert not idf.filter(est_ouvert=True).exists()
    r = staff_client.post(
        "/admin/nitrates/ouverture-geographique/toggle-region/",
        {"region_code": "11", "est_ouvert": "true"},
    )
    assert r.status_code == 204
    assert r["HX-Refresh"] == "true"
    assert idf.filter(est_ouvert=False).count() == 0
    assert idf.count() == 8  # 8 départements en IDF


def test_toggle_region_ferme_grand_est(staff_client):
    ge = DepartementOuverture.objects.filter(region_code="44")
    assert ge.filter(est_ouvert=True).count() == 10
    r = staff_client.post(
        "/admin/nitrates/ouverture-geographique/toggle-region/",
        {"region_code": "44", "est_ouvert": "false"},
    )
    assert r.status_code == 204
    assert ge.filter(est_ouvert=True).count() == 0


# ─── Liens admin (accès rapide + ORM) ───────────────────────────────────────


def test_admin_orm_changelist_accessible(staff_client):
    r = staff_client.get("/admin/nitrates/departementouverture/")
    assert r.status_code == 200


def test_admin_orm_action_ouvrir(staff_client):
    """L'action bulk « ouvrir la sélection » de l'admin ORM fonctionne."""
    r = staff_client.post(
        "/admin/nitrates/departementouverture/",
        {
            "action": "ouvrir_selection",
            "_selected_action": [
                str(DepartementOuverture.objects.get(code="75").pk),
            ],
        },
    )
    assert r.status_code in (200, 302)
    assert departement_est_ouvert("75") is True
