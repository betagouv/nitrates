from django.urls import path
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from envergo.nitrates.views import DebugView, HomeView, ZoneVulnerableGeoJSONView

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path(
        _("simulateur/debug/"),
        DebugView.as_view(),
        name="nitrates_debug",
    ),
    path(
        "geojson/zv/",
        ZoneVulnerableGeoJSONView.as_view(),
        name="nitrates_zv_geojson",
    ),
    path(
        _("contact-us/"),
        TemplateView.as_view(template_name="nitrates/contact_us.html"),
        name="contact_us",
    ),
]
