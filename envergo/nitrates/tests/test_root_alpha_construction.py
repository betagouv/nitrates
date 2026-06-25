"""Tests issue #113 : ouverture du root `/` aux alpha-testeurs.

Verifie :
  - le root sert le simulateur en mode "en construction", sans debug ;
  - `/simulateur/` garde son comportement (debug pilote par le flag) ;
  - le middleware lockdown exempte `/` SEULEMENT si NITRATES_ROOT_OUVERT ;
  - le bandeau "en construction" n'apparait que sur le root.
"""

import pytest
from django.contrib.sites.models import Site

pytestmark = pytest.mark.django_db


@pytest.fixture
def nitrates_site(settings):
    settings.ENVERGO_NITRATES_DOMAIN = "testserver"
    site, _ = Site.objects.get_or_create(domain="testserver")
    site.name = "Simulateur nitrates"
    site.save()
    return site


# --- Acces / lockdown -------------------------------------------------------


def test_root_ouvert_accessible_sans_login(client, settings, nitrates_site):
    """NITRATES_ROOT_OUVERT=True + lockdown actif : `/` reste accessible
    sans authentification."""
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = True

    resp = client.get("/")

    assert resp.status_code == 200


def test_root_ferme_redirige_si_lockdown(client, settings, nitrates_site):
    """NITRATES_ROOT_OUVERT=False + lockdown actif : `/` est protege
    (redirection login)."""
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = False

    resp = client.get("/")

    assert resp.status_code == 302
    assert "/login/" in resp["Location"]


def test_simulateur_reste_ferme_meme_si_root_ouvert(client, settings, nitrates_site):
    """Ouvrir le root ne doit PAS ouvrir /simulateur/ : seul `/` est
    exempte, pas les autres URL."""
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = True

    resp = client.get("/simulateur/")

    assert resp.status_code == 302
    assert "/login/" in resp["Location"]


# --- Bandeau "en construction" + debug off sur le root ----------------------


def test_root_affiche_bandeau_construction(client, settings, nitrates_site):
    settings.LOCKDOWN_BEHIND_LOGIN = False
    settings.NITRATES_ROOT_OUVERT = True

    resp = client.get("/")

    assert resp.status_code == 200
    assert resp.context["is_building"] is True
    content = resp.content.decode()
    # ruban 45deg + barre top qui se relaient au scroll
    assert "data-nitrates-construction" in content
    assert "nitrates-construction__ribbon" in content
    assert "nitrates-construction__bar" in content


def test_root_jamais_de_debug_meme_si_flag_actif(client, settings, nitrates_site):
    """Le root force debug=False meme si NITRATES_FORM_DEBUG_PANELS=True."""
    settings.LOCKDOWN_BEHIND_LOGIN = False
    settings.NITRATES_ROOT_OUVERT = True
    settings.NITRATES_FORM_DEBUG_PANELS = True

    resp = client.get("/")

    assert resp.status_code == 200
    assert resp.context["debug"] is False


# --- /simulateur/ inchange --------------------------------------------------


def test_simulateur_pas_de_bandeau_ni_building(client, settings, nitrates_site):
    settings.LOCKDOWN_BEHIND_LOGIN = False

    resp = client.get("/simulateur/")

    assert resp.status_code == 200
    assert resp.context["is_building"] is False
    assert "data-nitrates-construction" not in resp.content.decode()


# --- Ouverture geographique : appliquee sur / public, pas sur /simulateur ----


def test_root_applique_ouverture_geographique(client, settings, nitrates_site):
    """`/` (public) -> geo_appliquee True, injecte geo=1 cote front."""
    settings.LOCKDOWN_BEHIND_LOGIN = False
    settings.NITRATES_ROOT_OUVERT = True

    resp = client.get("/")

    assert resp.status_code == 200
    assert resp.context["geo_appliquee"] is True
    assert "window.NITRATES_GEO_APPLIQUEE = true" in resp.content.decode()


def test_simulateur_bypass_ouverture_geographique(client, settings, nitrates_site):
    """`/simulateur/` (interne) -> geo_appliquee False, pas de restriction."""
    settings.LOCKDOWN_BEHIND_LOGIN = False

    resp = client.get("/simulateur/")

    assert resp.status_code == 200
    assert resp.context["geo_appliquee"] is False
    assert "window.NITRATES_GEO_APPLIQUEE = false" in resp.content.decode()


def test_simulateur_debug_suit_le_flag(client, settings, nitrates_site):
    settings.LOCKDOWN_BEHIND_LOGIN = False
    settings.NITRATES_FORM_DEBUG_PANELS = True

    resp = client.get("/simulateur/")

    assert resp.status_code == 200
    assert resp.context["debug"] is True
