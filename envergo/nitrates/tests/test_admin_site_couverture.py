"""Couverture complémentaire de envergo/admin/site.py (EnvergoAdminSite).

test_admin_login_proconnect_only.py couvre déjà `login()`. Ce fichier
couvre `get_login_form`/`get_login_template` (choix de formulaire/template
selon les réglages), `each_context` (injection ProConnect) et
`has_permission` (OTP requis ou non).
"""

from unittest import mock

import pytest
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.models import AnonymousUser
from django_otp.admin import OTPAdminAuthenticationForm

from envergo.admin.site import get_login_form, get_login_template
from envergo.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# get_login_form / get_login_template
# ---------------------------------------------------------------------------


def test_get_login_form_otp_requis(settings):
    settings.ADMIN_OTP_REQUIRED = True
    assert get_login_form() is OTPAdminAuthenticationForm


def test_get_login_form_otp_non_requis(settings):
    settings.ADMIN_OTP_REQUIRED = False
    assert get_login_form() is AdminAuthenticationForm


def test_get_login_template_proconnect_prioritaire(settings):
    settings.PROCONNECT_ENABLED = True
    settings.ADMIN_OTP_REQUIRED = True
    assert get_login_template() == "admin/login_with_proconnect.html"


def test_get_login_template_otp_sans_proconnect(settings):
    settings.PROCONNECT_ENABLED = False
    settings.ADMIN_OTP_REQUIRED = True
    assert get_login_template() == "otp/admin111/login.html"


def test_get_login_template_standard(settings):
    settings.PROCONNECT_ENABLED = False
    settings.ADMIN_OTP_REQUIRED = False
    assert get_login_template() == "admin/login.html"


# ---------------------------------------------------------------------------
# each_context : injection du contexte ProConnect
# ---------------------------------------------------------------------------


def _otp_patch(request):
    """Applique le middleware django-otp pour patcher `request.user.is_verified`,
    comme le ferait le vrai stack de middlewares en requete HTTP reelle."""
    from django_otp.middleware import OTPMiddleware

    OTPMiddleware(lambda r: None)(request)
    return request


def test_each_context_proconnect_desactive(rf, settings):
    from envergo.admin.site import EnvergoAdminSite

    settings.PROCONNECT_ENABLED = False
    settings.ADMIN_OTP_REQUIRED = False
    site = EnvergoAdminSite(name="test-admin-ctx")
    request = rf.get("/admin/")
    request.user = AnonymousUser()
    _otp_patch(request)
    context = site.each_context(request)
    assert context["proconnect_enabled"] is False
    assert "proconnect_login_url" not in context


def test_each_context_proconnect_active(rf, settings):
    """L'URL `oidc_authentication_init` n'est enregistrée dans l'URLconf que
    si PROCONNECT_ENABLED est actif AU DEMARRAGE (cf. config/urls.py) : on ne
    peut pas la faire apparaitre en reglant le settings au runtime du test.
    On verifie donc le comportement observable sans dependre du routing reel :
    chaque_context doit tenter de resoudre cette URL nommee quand le flag est
    actif."""
    from envergo.admin.site import EnvergoAdminSite

    settings.PROCONNECT_ENABLED = True
    settings.ADMIN_OTP_REQUIRED = False
    site = EnvergoAdminSite(name="test-admin-ctx2")
    request = rf.get("/admin/")
    request.user = AnonymousUser()
    _otp_patch(request)

    with mock.patch(
        "envergo.admin.site.reverse", return_value="/oidc/authenticate/"
    ) as resolved:
        context = site.each_context(request)
    assert context["proconnect_enabled"] is True
    assert context["proconnect_login_url"] == "/oidc/authenticate/"
    resolved.assert_called_once_with("oidc_authentication_init")


# ---------------------------------------------------------------------------
# has_permission : combinaison staff/actif + vérification OTP
# ---------------------------------------------------------------------------


def test_has_permission_otp_non_requis_staff_actif(client, settings):
    """Via le vrai middleware stack (has_permission appelé par l'admin
    Django standard) : staff actif + OTP non requis -> accès admin."""
    settings.ADMIN_OTP_REQUIRED = False
    user = UserFactory(is_staff=True, is_active=True)
    client.force_login(user)
    from django.urls import reverse

    resp = client.get(reverse("admin:index"), follow=False)
    assert resp.status_code == 200


def test_has_permission_otp_non_requis_non_staff_refuse(client, settings):
    settings.ADMIN_OTP_REQUIRED = False
    user = UserFactory(is_staff=False, is_active=True)
    client.force_login(user)
    from django.urls import reverse

    resp = client.get(reverse("admin:index"), follow=False)
    # Pas staff -> redirigé vers le login admin (pas d'accès).
    assert resp.status_code == 302


def test_has_permission_otp_requis_sans_device_refuse(client, settings):
    """Un staff actif mais sans device OTP vérifié doit être refusé quand
    ADMIN_OTP_REQUIRED est actif (redirection vers le login admin)."""
    settings.ADMIN_OTP_REQUIRED = True
    user = UserFactory(is_staff=True, is_active=True)
    client.force_login(user)
    from django.urls import reverse

    resp = client.get(reverse("admin:index"), follow=False)
    assert resp.status_code == 302
    assert resp.url.startswith("/admin/login/")
