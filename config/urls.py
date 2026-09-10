from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.utils.translation import gettext_lazy as _
from django.views import defaults as default_views

from envergo.analytics.views import CSPReportView
from envergo.pages.views import rate_limited, security_txt, server_error
from envergo.urlmappings.views import UrlMappingRedirect

# customize error pages to handle multi-site
handler500 = server_error
handler429 = rate_limited

urlpatterns = [
    path("anymail/", include("anymail.urls")),
    path(_("analytics/"), include("envergo.analytics.urls")),
    path(_("feedback/"), include("envergo.analytics.urls")),
    path("urlmappings/", include("envergo.urlmappings.urls")),
    path(
        "simulation/<slug:key>/",
        UrlMappingRedirect.as_view(),
        name="urlmapping_redirect",
    ),
    path("csp/reports/", CSPReportView.as_view(), name="csp_report"),
    # RFC 9116 (carte #443) : emplacement normatif + alias racine tolere
    path(".well-known/security.txt", security_txt, name="security_txt"),
    path("security.txt", security_txt),
    path(settings.ADMIN_URL, admin.site.urls),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# ProConnect (SSO admin nitrates) : routes /oidc/authenticate/, /oidc/callback/,
# /oidc/logout/. Active uniquement si PROCONNECT_ENABLED (cf. config.settings.base).
if settings.PROCONNECT_ENABLED:
    urlpatterns += [
        path("oidc/", include("mozilla_django_oidc.urls")),
    ]

# Sonde infra (carte #111) : montee seulement si un jeton est configure, donc
# absente par defaut. Volontairement hors du lockdown ProConnect : on doit
# pouvoir la lire pendant un incident, y compris quand l'auth rame.
if getattr(settings, "NITRATES_PROBE_TOKEN", ""):
    from envergo.nitrates.views_probe import probe_dash, probe_now

    urlpatterns += [
        path("_probe/", probe_dash, name="nitrates_probe_dash"),
        path("_probe/now/", probe_now, name="nitrates_probe_now"),
    ]


if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        path(
            "400/",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        path(
            "403/",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        path(
            "404/",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        path("429/", rate_limited),
        path("500/", server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
