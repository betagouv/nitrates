"""Périmètre de l'admin : nitrates seulement.

L'autodiscover de Django enregistre les ModelAdmin de toutes les apps
installées, y compris les apps Envergo dormantes (avis, pétitions, haies...).
On les retire ici pour que l'admin n'expose que ce que l'équipe nitrates
administre réellement. Les tables restent en base, seul l'admin disparaît.

Importé en dernier par `envergo/nitrates/admin.py` : l'app nitrates est la
dernière de INSTALLED_APPS, donc son module admin est chargé après tous les
autres et voit le registre complet.
"""

from django import forms
from django.contrib import admin
from django.contrib.auth import admin as auth_admin
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.utils.translation import gettext_lazy as _

from envergo.utils.fields import NoIdnEmailField

# Modèles conservés dans l'admin, par app. Une app absente de ce dict est
# entièrement retirée ; `None` garde tous les modèles de l'app.
PERIMETRE = {
    "nitrates": None,
    "users": None,
    "auth": None,
    "otp_totp": None,
    # Couches SIG et leurs millésimes.
    "geodata": {"Map", "Zone", "Department"},
    # Le simulateur tourne dans le moteur `moulinette` : la réglementation
    # nitrates et son critère (carte d'activation) vivent dans ces tables ;
    # Perimeter est requis par l'autocomplete de CriterionAdmin.
    "moulinette": {"Regulation", "Criterion", "Perimeter"},
    # Rapports de violation CSP envoyés par les navigateurs (sécurité).
    "analytics": {"CSPReport"},
}


def hors_perimetre(model):
    garder = PERIMETRE.get(model._meta.app_label, set())
    return garder is not None and model.__name__ not in garder


def restreindre(site):
    for model in [m for m in site._registry if hors_perimetre(m)]:
        site.unregister(model)


User = get_user_model()


class NitratesUserCreationForm(UserCreationForm):
    email = NoIdnEmailField(
        required=True,
        label=_("Email address"),
        widget=forms.EmailInput(attrs={"class": "vTextField"}),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "name")


class NitratesUserAdmin(auth_admin.UserAdmin):
    """Comptes admin nitrates : connexion ProConnect, groupes, TOTP.

    Remplace l'admin Envergo, qui exposait les accès aménagement / haie, les
    droits instructeur par département et les projets de pétition suivis.
    """

    add_form = NitratesUserCreationForm
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("name",)}),
        (
            _("Permissions"),
            {"fields": ("is_active", "is_staff", "is_superuser", "groups")},
        ),
        ("ProConnect", {"fields": ("proconnect_sub",)}),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "name", "password1", "password2"),
            },
        ),
    )
    list_display = ["email", "name", "is_active", "is_staff", "is_superuser"]
    list_filter = ["is_active", "is_staff", "is_superuser", "groups"]
    readonly_fields = ["last_login", "date_joined", "proconnect_sub"]
    search_fields = ["name", "email"]
    ordering = ["email"]
    filter_horizontal = ("groups",)


restreindre(admin.site)
if admin.site.is_registered(User):
    admin.site.unregister(User)
admin.site.register(User, NitratesUserAdmin)
