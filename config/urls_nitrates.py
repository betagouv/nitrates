from django.urls import include, path
from django.views.generic import RedirectView

from config.urls import handler500  # noqa
from config.urls import urlpatterns as common_urlpatterns

urlpatterns = [
    # Nom 'login' attendu par @login_required (settings.LOGIN_URL = "login").
    # On redirige vers le flow OIDC ProConnect (cf. mozilla_django_oidc).
    path(
        "login/",
        RedirectView.as_view(
            pattern_name="oidc_authentication_init",
            query_string=True,
            permanent=False,
        ),
        name="login",
    ),
    path("", include("envergo.nitrates.urls")),
] + common_urlpatterns
