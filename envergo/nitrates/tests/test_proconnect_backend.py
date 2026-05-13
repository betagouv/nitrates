"""Tests du backend OIDC ProConnect (envergo/nitrates/auth.py).

Vise les invariants de la politique d'auth nitrates :
- Aucune creation de compte spontanee (refus si email inconnu)
- Reconciliation prioritaire par `sub` (stable), fallback `email`
- Persistance du `sub` a la 1ere connexion
- Nom rempli depuis ProConnect seulement si absent
"""

import pytest
from django.core.exceptions import SuspiciousOperation

from envergo.nitrates.auth import ProConnectBackend
from envergo.users.models import User


@pytest.fixture(autouse=True)
def _oidc_settings(settings):
    """ProConnectBackend()' s init lit les settings OIDC_OP_*. En local et
    en CI sans creds ProConnect, ces settings n'existent pas (cf. base.py
    ou ils ne sont ajoutes que si PROCONNECT_ENABLED). On les force a des
    valeurs fakes pour permettre l'instanciation -- les tests ne font pas
    de network call, ils testent la logique de reconciliation user."""
    settings.OIDC_RP_CLIENT_ID = "test-client"
    settings.OIDC_RP_CLIENT_SECRET = "test-secret"  # pragma: allowlist secret
    settings.OIDC_RP_SIGN_ALGO = "RS256"
    settings.OIDC_OP_AUTHORIZATION_ENDPOINT = "https://op.test/authorize"
    settings.OIDC_OP_TOKEN_ENDPOINT = "https://op.test/token"
    settings.OIDC_OP_USER_ENDPOINT = "https://op.test/userinfo"
    settings.OIDC_OP_JWKS_ENDPOINT = "https://op.test/jwks"


@pytest.fixture
def backend():
    return ProConnectBackend()


@pytest.mark.django_db
def test_unknown_email_is_refused(backend):
    """Un email inconnu en DB doit declencher SuspiciousOperation."""
    claims = {"sub": "abc", "email": "stranger@example.com"}
    with pytest.raises(SuspiciousOperation):
        backend.create_user(claims)


@pytest.mark.django_db
def test_filter_by_sub_priority(backend):
    """Si proconnect_sub matche, on prend cet user meme si email different."""
    user = User.objects.create(
        email="old-email@example.com",
        name="Foo",
        is_staff=True,
        proconnect_sub="pc-sub-123",
    )
    claims = {"sub": "pc-sub-123", "email": "new-email@example.com"}
    users = backend.filter_users_by_claims(claims)
    assert list(users) == [user]


@pytest.mark.django_db
def test_filter_by_email_fallback(backend):
    """Sans match sub (1ere connexion), on retombe sur l'email."""
    user = User.objects.create(email="known@example.com", name="Foo", is_staff=True)
    claims = {"sub": "first-time-sub", "email": "known@example.com"}
    users = backend.filter_users_by_claims(claims)
    assert list(users) == [user]


@pytest.mark.django_db
def test_filter_email_case_insensitive(backend):
    """L'email est compare insensitive (ProConnect peut renvoyer en maj)."""
    user = User.objects.create(email="known@example.com", name="Foo", is_staff=True)
    claims = {"sub": "x", "email": "KNOWN@Example.Com"}
    users = backend.filter_users_by_claims(claims)
    assert list(users) == [user]


@pytest.mark.django_db
def test_update_user_persists_sub_first_login(backend):
    """A la 1ere connexion, on persiste le sub pour les futures reconnexions."""
    user = User.objects.create(email="known@example.com", name="Foo", is_staff=True)
    claims = {"sub": "pc-sub-fresh", "email": "known@example.com"}
    updated = backend.update_user(user, claims)
    assert updated.proconnect_sub == "pc-sub-fresh"


@pytest.mark.django_db
def test_update_user_does_not_overwrite_existing_sub(backend):
    """Si un sub est deja persiste, on ne l'ecrase pas."""
    user = User.objects.create(
        email="known@example.com",
        name="Foo",
        is_staff=True,
        proconnect_sub="original-sub",
    )
    claims = {"sub": "different-sub", "email": "known@example.com"}
    backend.update_user(user, claims)
    user.refresh_from_db()
    assert user.proconnect_sub == "original-sub"


@pytest.mark.django_db
def test_update_user_fills_name_when_empty(backend):
    """Le nom est rempli depuis given_name + usual_name si User.name vide."""
    user = User.objects.create(email="known@example.com", name="", is_staff=True)
    claims = {
        "sub": "s",
        "email": "known@example.com",
        "given_name": "Marie",
        "usual_name": "Curie",
    }
    backend.update_user(user, claims)
    user.refresh_from_db()
    assert user.name == "Marie Curie"


@pytest.mark.django_db
def test_update_user_preserves_existing_name(backend):
    """Si User.name est deja saisi (par un admin), ProConnect ne l'ecrase pas."""
    user = User.objects.create(
        email="known@example.com", name="Nom Choisi", is_staff=True
    )
    claims = {
        "sub": "s",
        "email": "known@example.com",
        "given_name": "Autre",
        "usual_name": "Nom",
    }
    backend.update_user(user, claims)
    user.refresh_from_db()
    assert user.name == "Nom Choisi"


def test_verify_claims_requires_email(backend):
    """Un id_token sans email ne doit pas autoriser la connexion."""
    assert backend.verify_claims({"sub": "x"}) is False


@pytest.mark.django_db
def test_no_match_returns_empty_queryset(backend):
    """Aucun user en DB => queryset vide (mozilla-django-oidc declenche create_user)."""
    claims = {"sub": "unknown", "email": "noone@example.com"}
    assert backend.filter_users_by_claims(claims).count() == 0
