from django.urls import path
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from envergo.nitrates.views import (
    DebugView,
    DecisionTreeView,
    HomeView,
    MoulinetteView,
    ReferentielsView,
    ZoneVulnerableGeoJSONView,
)
from envergo.nitrates.views_admin_yaml import (
    CloneConfirmView,
    CreateDraftView,
    RenameTreeView,
    YamlTreeView,
)

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path(
        _("simulateur/"),
        MoulinetteView.as_view(),
        name="nitrates_simulateur",
    ),
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
        "api/referentiels/",
        ReferentielsView.as_view(),
        name="nitrates_referentiels",
    ),
    path(
        "api/arbre/",
        DecisionTreeView.as_view(),
        name="nitrates_arbre",
    ),
    path(
        "admin/nitrates/arbre-decision/",
        YamlTreeView.as_view(),
        name="nitrates_admin_yaml_tree",
    ),
    path(
        "admin/nitrates/arbre-decision/draft/nouveau/",
        CreateDraftView.as_view(),
        name="nitrates_admin_yaml_create_draft",
    ),
    path(
        "admin/nitrates/arbre-decision/<int:pk>/renommer/",
        RenameTreeView.as_view(),
        name="nitrates_admin_yaml_rename_tree",
    ),
    path(
        "admin/nitrates/arbre-decision/<int:pk>/cloner/",
        CloneConfirmView.as_view(),
        name="nitrates_admin_yaml_clone_confirm",
    ),
    path(
        _("contact-us/"),
        TemplateView.as_view(template_name="nitrates/contact_us.html"),
        name="contact_us",
    ),
]
