"""Connexion directe par ProConnect, sans révéler le préfixe admin (#577).

Un anonyme est envoyé directement vers ProConnect, jamais vers la page de
login de l'admin dont l'URL porte le préfixe secret (`DJANGO_ADMIN_URL`).
Les routes OIDC ne sont pas montées en test (ProConnect off) : on simule
l'URL d'entrée ProConnect.
"""

import pytest
from django.contrib.sites.models import Site
from django.urls import reverse

from envergo.nitrates import connexion
from envergo.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

URL_PROCONNECT = "/oidc/authenticate/"


@pytest.fixture(autouse=True)
def nitrates_site(settings):
    settings.ENVERGO_NITRATES_DOMAIN = "testserver"
    Site.objects.get_or_create(domain="testserver")


@pytest.fixture
def proconnect(settings, monkeypatch):
    settings.PROCONNECT_ENABLED = True
    monkeypatch.setattr(connexion, "url_connexion", lambda: URL_PROCONNECT)


def _admin_nitrates(nom):
    return reverse(nom, urlconf="config.urls_nitrates")


def _sans_prefixe_admin(response, settings):
    """Le login admin (seule URL qui porte le préfixe secret) n'apparaît pas."""
    return reverse("admin:login") not in response["Location"]


def test_lockdown_anonyme_va_directement_sur_proconnect(client, settings, proconnect):
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = True
    response = client.get("/simulateur/")
    assert response.status_code == 302
    assert response["Location"] == f"{URL_PROCONNECT}?next=/simulateur/"
    assert _sans_prefixe_admin(response, settings)


def test_lockdown_conserve_la_page_demandee(client, settings, proconnect):
    settings.LOCKDOWN_BEHIND_LOGIN = True
    response = client.get("/api/arbre/?scope=national")
    assert response["Location"] == (
        f"{URL_PROCONNECT}?next=/api/arbre/%3Fscope%3Dnational"
    )


def test_ecran_admin_nitrates_anonyme_va_sur_proconnect(client, settings, proconnect):
    settings.LOCKDOWN_BEHIND_LOGIN = False
    url = _admin_nitrates("nitrates_admin_matrice_index")
    response = client.get(url)
    assert response.status_code == 302
    assert response["Location"].startswith(f"{URL_PROCONNECT}?next=")
    assert _sans_prefixe_admin(response, settings)


def test_ecran_admin_nitrates_connecte_sans_droits_403(client, settings, proconnect):
    """Pas de renvoi vers ProConnect pour un connecté : il bouclerait."""
    settings.LOCKDOWN_BEHIND_LOGIN = False
    client.force_login(UserFactory(is_staff=False, is_active=True))
    response = client.get(_admin_nitrates("nitrates_admin_matrice_index"))
    assert response.status_code == 403


def test_ecran_admin_nitrates_staff_passe(client, settings, proconnect):
    settings.LOCKDOWN_BEHIND_LOGIN = False
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    response = client.get(_admin_nitrates("nitrates_admin_matrice_index"))
    assert response.status_code == 200


def test_page_login_admin_saute_directement_sur_proconnect(
    client, settings, proconnect
):
    response = client.get(reverse("admin:login") + "?next=/admin/nitrates/matrice/")
    assert response.status_code == 302
    assert response["Location"] == (f"{URL_PROCONNECT}?next=/admin/nitrates/matrice/")


def test_page_login_admin_sans_next_renvoie_vers_l_admin(client, settings, proconnect):
    response = client.get(reverse("admin:login"))
    assert response["Location"] == f"{URL_PROCONNECT}?next={reverse('admin:index')}"


def test_post_mot_de_passe_toujours_refuse(client, settings, proconnect):
    """Le refus du fallback mot de passe (pentest F1) est inchangé."""
    settings.ADMIN_PASSWORD_LOGIN_DISABLED = True
    response = client.post(reverse("admin:login"), {"username": "x", "password": "y"})
    assert response.status_code == 403


def test_sans_proconnect_repli_sur_le_login_admin(client, settings):
    """En local / tests, sans ProConnect, le login admin reste la seule voie."""
    settings.PROCONNECT_ENABLED = False
    settings.ADMIN_PASSWORD_LOGIN_DISABLED = False
    settings.LOCKDOWN_BEHIND_LOGIN = True
    response = client.get("/simulateur/")
    assert response["Location"] == f"{reverse('admin:login')}?next=/simulateur/"
    assert client.get(reverse("admin:login")).status_code == 200
