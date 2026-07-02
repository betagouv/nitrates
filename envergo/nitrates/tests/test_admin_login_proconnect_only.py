"""Faille pentest F1 (2026-06-18) — le form mot de passe /admin/login/
contourne ProConnect.

Ces tests verrouillent la remediation : quand
`ADMIN_PASSWORD_LOGIN_DISABLED` est actif, l'AdminSite refuse (403) la
SOUMISSION (POST) d'identifiants par mot de passe sur /admin/login/, y compris
le POST direct d'identifiants superuser valides (le PoC du pentester). Le GET
de la page reste servi pour proposer le bouton ProConnect (regression #197 : un
403 sur GET faisait un cul-de-sac). Quand l'option est desactivee (dev/local),
le comportement Django standard est preserve.
"""

import pytest
from django.urls import reverse

from envergo.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

# Mot de passe FACTICE de test (jamais un vrai secret) : simule un compte admin
# à mot de passe utilisable, la cible de la faille F1.
TEST_PASSWORD = "PentestPoC123!"  # pragma: allowlist secret


@pytest.fixture
def superuser():
    """Superuser avec un mot de passe UTILISABLE : exactement la cible de F1."""
    return UserFactory(
        email="admin@nitrates.local",
        password=TEST_PASSWORD,
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )


def login_url():
    return reverse("admin:login")


# ── Option desactivee (dev/local) : comportement Django standard preserve ──


def test_form_mot_de_passe_accessible_quand_option_off(client, settings):
    settings.ADMIN_PASSWORD_LOGIN_DISABLED = False
    resp = client.get(login_url())
    # Le form login standard est servi (200), avec un champ password.
    assert resp.status_code == 200
    assert b'name="password"' in resp.content


def test_login_mot_de_passe_fonctionne_quand_option_off(client, settings):
    settings.ADMIN_PASSWORD_LOGIN_DISABLED = False
    user = UserFactory(
        email="staff@nitrates.local",
        password=TEST_PASSWORD,
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )
    resp = client.post(
        login_url(),
        {"username": user.email, "password": TEST_PASSWORD},
    )
    # Redirection (302) = login accepte quand l'option est OFF.
    assert resp.status_code == 302


# ── Option activee (prod/staging) : fallback mot de passe ferme (403) ──


def test_get_login_ne_renvoie_pas_403_quand_option_on(client, settings):
    """Regression #197 : le GET de /admin/login/ ne doit PAS renvoyer 403 — ca
    faisait un cul-de-sac (plus aucune voie d'entree, il fallait connaitre
    /oidc/authenticate/). La page doit s'afficher (200) : c'est elle qui porte
    le bouton ProConnect. Seul le POST mot de passe est refuse (test suivant).

    NB : PROCONNECT_ENABLED reste OFF ici (le routing OIDC n'est inclus qu'au
    boot de l'URLconf, cf. config/urls.py — on ne peut pas le basculer au
    runtime du test). On verifie donc le point cle de la regression : GET != 403.
    """
    settings.ADMIN_PASSWORD_LOGIN_DISABLED = True
    resp = client.get(login_url())
    assert resp.status_code == 200
    assert resp.status_code != 403


def test_poc_pentester_post_creds_superuser_refuse_403(client, settings, superuser):
    """Le PoC F1 end-to-end : POST direct des creds d'un superuser a mot de
    passe utilisable. Doit etre refuse (403) et NE PAS creer de session."""
    settings.ADMIN_PASSWORD_LOGIN_DISABLED = True
    resp = client.post(
        login_url(),
        {"username": superuser.email, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 403
    # Aucune session authentifiee n'a ete posee.
    assert "_auth_user_id" not in client.session


def test_utilisateur_deja_authentifie_pas_403(client, settings, superuser):
    """Un utilisateur deja authentifie (ex session ProConnect valide) qui
    repasse sur /admin/login/ ne doit pas se prendre un 403 : Django le
    redirige normalement. On simule l'auth via force_login (== session posee
    hors form mot de passe, comme ProConnect)."""
    settings.ADMIN_PASSWORD_LOGIN_DISABLED = True
    client.force_login(superuser)
    resp = client.get(login_url())
    # Django redirige un user deja connecte hors de la page login (302).
    assert resp.status_code == 302


def test_acces_admin_index_anonyme_redirige_toujours(client, settings):
    """Sanity : l'index admin reste protege (302 -> login) meme avec l'option,
    on n'a pas casse la protection existante."""
    settings.ADMIN_PASSWORD_LOGIN_DISABLED = True
    resp = client.get(reverse("admin:index"))
    assert resp.status_code in (302, 403)
