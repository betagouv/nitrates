"""Admin Django pour l'app nitrates.

Note : `MoulinetteNitrates` n'est pas un model Django (il herite de
`Moulinette` qui est une ABC Python sans table DB), il n'apparait donc
pas ici.
"""

import json

from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from envergo.nitrates.models import DecisionTree, RpgCulture
from envergo.nitrates.permissions import (
    can_change_tree,
    can_delete_tree,
    can_edit_active,
)

# ─── Éditeur de contenu riche WYSIWYG (cartes #131/#136) ─────────────────────
# Widget + helper partagés par ContenuRichDSFR (textes volants) ET
# CodePrescription (champ blocs). Editor.js monté côté JS sur un <textarea>
# masqué qui porte le JSON.


class ContenuRichEditorWidget(forms.Textarea):
    """Widget WYSIWYG (Editor.js) pour un champ `blocs` JSON.

    Le <textarea> reste le champ réel du form (il porte le JSON), mais on le
    masque et on monte Editor.js par-dessus (cf. contenu_rich_editor.js). Le
    juriste n'édite jamais le JSON à la main."""

    def __init__(self, attrs=None):
        default = {"data-contenu-rich-editor": "1", "rows": 12}
        if attrs:
            default.update(attrs)
        super().__init__(default)

    class Media:
        js = (
            "nitrates_admin/vendor/editorjs/editorjs.umd.min.js",
            "nitrates_admin/vendor/editorjs/header.umd.min.js",
            "nitrates_admin/vendor/editorjs/list.umd.min.js",
            "nitrates_admin/vendor/editorjs/quote.umd.min.js",
            "nitrates_admin/foldable_tool.js",
            "nitrates_admin/indent_tune.js",
            "nitrates_admin/contenu_rich_editor.js",
        )
        css = {"all": ("nitrates_admin/contenu_rich_editor.css",)}


def _clean_blocs_json(valeur):
    """Parse la valeur postée par le widget (JSON string) -> objet Python.
    Vide -> enveloppe {schema, blocs:[]}. Lève ValidationError si illisible."""
    if isinstance(valeur, (dict, list)):
        return valeur
    if not valeur:
        return {"schema": 1, "blocs": []}
    try:
        return json.loads(valeur)
    except (TypeError, ValueError):
        raise forms.ValidationError(_("Contenu invalide (JSON illisible)."))


@admin.register(RpgCulture)
class RpgCultureAdmin(admin.ModelAdmin):
    list_display = ("code", "libelle", "code_groupe", "libelle_groupe")
    list_filter = ("code_groupe",)
    search_fields = ("code", "libelle", "libelle_groupe")
    ordering = ("code",)


@admin.register(DecisionTree)
class DecisionTreeAdmin(admin.ModelAdmin):
    change_list_template = "admin/nitrates/decisiontree/change_list.html"

    def has_change_permission(self, request, obj=None):
        # Liste : on laisse l'acces (les actions par ligne sont filtrees
        # par actions_links + les vues yaml_admin reverifient).
        if obj is None:
            return super().has_change_permission(request, obj)
        return can_change_tree(request.user, obj)

    def changelist_view(self, request, extra_context=None):
        # Injecte `can_edit_active` dans le contexte pour le template
        # custom change_list (qui cache le bouton "Editer l'arbre actif"
        # aux external_observator).
        extra_context = extra_context or {}
        extra_context["can_edit_active"] = can_edit_active(request.user)
        return super().changelist_view(request, extra_context=extra_context)

    def has_delete_permission(self, request, obj=None):
        if obj is None:
            return super().has_delete_permission(request, obj)
        return can_delete_tree(request.user, obj)

    list_display = (
        "id",
        "name",
        "status_badge",
        "scope",
        "region_col",
        "activation_map",
        "weight_col",
        "updated_at",
        "created_by",
        "actions_links",
    )
    list_filter = ("status", "scope", "region_code")
    search_fields = ("name", "region_code")
    ordering = ("-activated_at", "-created_at")
    # `created_by` + `activation_map` sont affiches dans list_display : sans
    # select_related, 1 query par ligne pour les resoudre. Avec, des JOIN.
    list_select_related = ("created_by", "activation_map")
    readonly_fields = (
        "yaml_preview",
        "edit_link",
        "created_at",
        "updated_at",
        "activated_at",
        "created_by",
    )
    fieldsets = (
        (None, {"fields": ("name", "status", "parent", "edit_link")}),
        (
            "Zone d'activation (sélection dynamique PAN / PAR / ZAR)",
            {
                "fields": ("scope", "region_code", "activation_map", "weight"),
                "description": (
                    "PAN = national (ni région ni couche). PAR régional = "
                    "scope « region » + code région. ZAR = scope « zar » + "
                    "couche d'activation SIG. Le poids départage les "
                    "superpositions (le plus élevé gagne)."
                ),
            },
        ),
        (
            "Contenu YAML (lecture seule — utiliser l'éditeur pour modifier)",
            {"fields": ("yaml_preview",)},
        ),
        (
            "Métadonnées",
            {"fields": ("created_at", "updated_at", "activated_at", "created_by")},
        ),
    )

    @admin.display(description="Aperçu YAML")
    def yaml_preview(self, obj):
        """Rend le YAML avec coloration syntaxique Pygments.

        Theme `monokai` (fond sombre type Darcula). On force le theme
        independant du dark/light mode du systeme pour garder une
        coloration coherente.
        """
        if not obj or not obj.contenu_yaml_brut:
            return "(vide)"
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import YamlLexer

        formatter = HtmlFormatter(
            cssclass="yaml-raw",
            linenos="inline",
            wrapcode=True,
            style="monokai",
        )
        css = formatter.get_style_defs(".yaml-raw")
        body = highlight(obj.contenu_yaml_brut, YamlLexer(), formatter)
        return format_html(
            "<style>{}\n"
            ".yaml-raw {{ max-height: 70vh; overflow: auto; "
            "border-radius: 4px; padding: 0.75rem 1rem; "
            "background: #272822 !important; "
            "color: #f8f8f2; "
            "font-family: ui-monospace, Menlo, monospace; "
            "font-size: 0.85rem; line-height: 1.5; }}\n"
            ".yaml-raw pre {{ background: transparent !important; "
            "color: inherit; margin: 0; }}\n"
            ".yaml-raw .linenos {{ color: #75715e; padding-right: 1rem; "
            "user-select: none; }}\n"
            "</style>{}",
            mark_safe(css),
            mark_safe(body),
        )

    @admin.display(description="Éditer")
    def edit_link(self, obj):
        """Lien vers l'éditeur YAML (depuis l'admin Django classique)."""
        if not obj or not obj.pk:
            return "—"
        view_url = reverse("nitrates_admin_yaml_tree") + f"?tree_id={obj.pk}"
        if obj.status == DecisionTree.STATUS_DRAFT:
            edit_url = view_url + "&mode=edition"
            return format_html(
                '<a class="button" href="{}">Voir</a> '
                '<a class="button" style="background:#1f4789;color:#fff;" href="{}">'
                "✏️ Éditer ce brouillon</a>",
                view_url,
                edit_url,
            )
        if obj.status == DecisionTree.STATUS_ACTIVE:
            # On passe tree_id pour que l'edition cible l'actif de CETTE zone
            # (PAN/PAR/ZAR), pas le PAN par defaut.
            edit_active_url = (
                reverse("nitrates_admin_yaml_edit_active") + f"?tree_id={obj.pk}"
            )
            return format_html(
                '<a class="button" href="{}">Voir</a> '
                '<a class="button" style="background:#1f4789;color:#fff;" href="{}">'
                "✏️ Éditer cet arbre</a>",
                view_url,
                edit_active_url,
            )
        # Archive
        clone_url = reverse("nitrates_admin_yaml_clone_confirm", kwargs={"pk": obj.pk})
        return format_html(
            '<a class="button" href="{}">Voir</a> '
            '<a class="button" href="{}">Cloner en draft</a>',
            view_url,
            clone_url,
        )

    @admin.display(description="Rég.", ordering="region_code")
    def region_col(self, obj):
        # En-tete court : la valeur fait 2 chiffres, inutile d'imposer la
        # largeur de "Code region" a la colonne.
        return obj.region_code or "—"

    @admin.display(description="Poids", ordering="weight")
    def weight_col(self, obj):
        return obj.weight

    @admin.display(description="Statut", ordering="status")
    def status_badge(self, obj):
        colors = {
            DecisionTree.STATUS_ACTIVE: "#1b5e20",
            DecisionTree.STATUS_DRAFT: "#e65100",
            DecisionTree.STATUS_ARCHIVE: "#616161",
        }
        bg = {
            DecisionTree.STATUS_ACTIVE: "#e8f5e9",
            DecisionTree.STATUS_DRAFT: "#fff3e0",
            DecisionTree.STATUS_ARCHIVE: "#f5f5f5",
        }
        return format_html(
            '<span style="background:{};color:{};padding:2px 8px;'
            'border-radius:3px;font-weight:600;font-size:0.85em;">{}</span>',
            bg.get(obj.status, "#eee"),
            colors.get(obj.status, "#333"),
            obj.get_status_display(),
        )

    @admin.display(description="Actions")
    def actions_links(self, obj):
        # Note : on n'a pas acces a request ici (limitation Django admin).
        # On affiche tous les boutons ; ceux qui menent a une vue non
        # autorisee retourneront 403 cote serveur. Les observateurs voient
        # donc le bouton Editer mais s'ils cliquent dessus ils sont
        # bloques par _check_editable / can_edit_active dans les vues.
        view_url = reverse("nitrates_admin_yaml_tree") + f"?tree_id={obj.pk}"
        edit_url = view_url + "&mode=edition"
        clone_url = reverse("nitrates_admin_yaml_clone_confirm", kwargs={"pk": obj.pk})
        # tree_id pour cibler l'actif de CETTE zone (PAN/PAR/ZAR), pas le PAN.
        edit_active_url = (
            reverse("nitrates_admin_yaml_edit_active") + f"?tree_id={obj.pk}"
        )
        if obj.status == DecisionTree.STATUS_DRAFT:
            # Draft : Voir + Éditer + Cloner (utile aux external_observator
            # pour cloner un draft d'autrui en faire le leur).
            return mark_safe(
                f'<a class="button" href="{view_url}">Voir</a> '
                f'<a class="button" href="{edit_url}">Éditer</a> '
                f'<a class="button" href="{clone_url}">Cloner</a>'
            )
        if obj.status == DecisionTree.STATUS_ACTIVE:
            # Active : Voir + "Éditer" (intra : clone vers un draft puis
            # bascule) + Cloner explicite (utile aux observateurs externes
            # qui ne peuvent pas utiliser "Éditer" et ont besoin d'un point
            # d'entree pour creer leur propre brouillon).
            return mark_safe(
                f'<a class="button" href="{view_url}">Voir</a> '
                f'<a class="button" href="{edit_active_url}">Éditer</a> '
                f'<a class="button" href="{clone_url}">Cloner</a>'
            )
        # Archive : Voir + Cloner (pas d'edition directe sur un archive).
        return mark_safe(
            f'<a class="button" href="{view_url}">Voir</a> '
            f'<a class="button" href="{clone_url}">Cloner</a>'
        )

    actions = ["clone_to_draft"]

    @admin.action(description="Cloner en draft (1 seul à la fois)")
    def clone_to_draft(self, request, queryset):
        """Action admin : clone le tree selectionne en nouveau draft.

        N'accepte qu'une seule ligne a la fois (cloner plusieurs trees
        d'un coup n'a pas de sens : on perd le focus).
        """
        if queryset.count() != 1:
            self.message_user(
                request,
                "Sélectionnez exactement une ligne à cloner.",
                level=messages.ERROR,
            )
            return
        source = queryset.get()
        draft = DecisionTree.clone_to_draft(source, user=request.user)
        url = reverse("nitrates_admin_yaml_tree") + f"?tree_id={draft.pk}"
        self.message_user(
            request,
            f"Draft « {draft.name} » créé. Redirection vers l'éditeur.",
        )
        return redirect(url)


# ─── Référentiels (cf. carte #61 — migration referentiels.yaml) ───────────────


from envergo.nitrates.models import (  # noqa: E402
    BrancheCulturale,
    CodePrescription,
    Culture,
    EvenementPhenologique,
    Fertilisant,
    GroupeCultureUI,
    NoteReglementaire,
)


class _ReferentielsListMixin:
    """Charge le CSS qui autorise le wrap des colonnes libelle_*/mots_cles
    sur les changelist des referentiels nitrates (carte #61). Sans ca,
    une longue valeur force une seule ligne et masque les colonnes
    suivantes."""

    class Media:
        css = {"all": ("nitrates_admin/referentiels_list.css",)}


@admin.register(GroupeCultureUI)
class GroupeCultureUIAdmin(_ReferentielsListMixin, admin.ModelAdmin):
    """Groupe affiché au 1er niveau de la cascade formulaire (UX seulement).

    Sert UNIQUEMENT à regrouper visuellement les cultures dans le 1er
    select du formulaire front. Aucune logique métier de l'arbre ne
    branche dessus -- l'arbre passe par Culture -> BrancheCulturale.
    """

    list_display = ("identifiant", "libelle_public", "ordre_affichage")
    search_fields = ("identifiant", "libelle_public")
    ordering = ("ordre_affichage", "libelle_public")


@admin.register(BrancheCulturale)
class BrancheCulturaleAdmin(_ReferentielsListMixin, admin.ModelAdmin):
    list_display = ("identifiant", "libelle_court", "ordre_affichage")
    search_fields = ("identifiant", "libelle_court")
    ordering = ("ordre_affichage", "identifiant")


class _JsonEmptyAsDictField(forms.JSONField):
    """Variante du JSONField admin qui traite `""` (textarea vide) comme
    `{}`. Sans ca, l'utilisateur qui vide le champ se prend une
    ValidationError "Enter a valid JSON" -> 500 visuel.
    """

    def to_python(self, value):
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return {}
        return super().to_python(value)


class CultureAdminForm(forms.ModelForm):
    champs_prefill = _JsonEmptyAsDictField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=(
            "Champs à injecter dans le contexte quand cette culture est "
            'choisie. Ex pour Maïs : {"culture_irriguee_type": "mais"}. '
            "Laisser vide pour le cas nominal."
        ),
    )

    class Meta:
        fields = "__all__"


@admin.register(Culture)
class CultureAdmin(_ReferentielsListMixin, admin.ModelAdmin):
    form = CultureAdminForm
    list_display = (
        "identifiant",
        "libelle_public",
        "categorie",
        "branche_culturale",
        "occupation_sol",
        "ordre_affichage",
    )
    search_fields = ("identifiant", "libelle_public")
    autocomplete_fields = ("categorie", "branche_culturale")
    ordering = ("categorie__ordre_affichage", "ordre_affichage", "libelle_public")


@admin.register(Fertilisant)
class FertilisantAdmin(_ReferentielsListMixin, admin.ModelAdmin):
    list_display = (
        "identifiant",
        "libelle_public",
        "categorie",
        "type_reglementaire",
    )
    search_fields = ("identifiant", "libelle_public")
    # Ordre liste admin : par type reglementaire (type_0, type_Ia, ...)
    # puis alphabetique. Plus parlant que l'ordre d'affichage UI quand
    # on revoit le seed depuis l'admin.
    ordering = ("type_reglementaire", "libelle_public")


@admin.register(NoteReglementaire)
class NoteReglementaireAdmin(_ReferentielsListMixin, admin.ModelAdmin):
    list_display = ("identifiant", "libelle_court", "ordre_affichage")
    search_fields = ("identifiant", "libelle_court")
    ordering = ("ordre_affichage", "identifiant")


class CodePrescriptionForm(forms.ModelForm):
    """Form admin du PC : le champ `blocs` est édité via l'éditeur WYSIWYG
    (carte #136), comme ContenuRichDSFR. Le JSON est produit sous le capot."""

    class Meta:
        model = CodePrescription
        fields = "__all__"
        widgets = {"blocs": ContenuRichEditorWidget}

    def clean_blocs(self):
        return _clean_blocs_json(self.cleaned_data.get("blocs"))


@admin.register(CodePrescription)
class CodePrescriptionAdmin(_ReferentielsListMixin, admin.ModelAdmin):
    form = CodePrescriptionForm
    list_display = (
        "identifiant",
        "mots_cles",
        "a_du_contenu_riche",
        "toujours_affiche",
        "note_reglementaire",
        "ordre_affichage",
    )
    search_fields = ("identifiant", "mots_cles", "texte_court")
    autocomplete_fields = ("note_reglementaire",)
    ordering = ("ordre_affichage", "identifiant")
    readonly_fields = ("apercu_rendu",)

    @admin.display(description="Contenu riche", boolean=True)
    def a_du_contenu_riche(self, obj):
        """Indique en liste si le PC a un contenu riche (champ `blocs`) saisi,
        sinon il retombe sur le texte legacy (carte #136)."""
        b = obj.blocs
        if isinstance(b, dict):
            return bool(b.get("blocs"))
        return bool(b)

    @admin.display(description="Aperçu du rendu")
    def apercu_rendu(self, obj):
        """Lien (nouvel onglet) vers la prévisualisation du rendu HTML DSFR de
        ce PC (carte #136)."""
        if not obj or not obj.pk:
            return "— (enregistrer d'abord)"
        url = reverse("nitrates_admin_contenu_rich_preview") + f"?type=pc&id={obj.pk}"
        return format_html(
            '<a class="button" href="{}" target="_blank" rel="noopener">'
            "🔎 Prévisualiser le rendu</a>",
            url,
        )


@admin.register(EvenementPhenologique)
class EvenementPhenologiqueAdmin(_ReferentielsListMixin, admin.ModelAdmin):
    list_display = ("identifiant", "libelle_public", "date_calendrier")
    search_fields = ("identifiant", "libelle_public")
    ordering = ("identifiant",)


from envergo.nitrates.models import DepartementOuverture  # noqa: E402


@admin.register(DepartementOuverture)
class DepartementOuvertureAdmin(admin.ModelAdmin):
    """Ouverture géographique du simulateur (carte #57).

    Le pilotage visuel se fait sur la page dédiée « Ouverture géographique »
    (drag&drop). Cet admin ORM offre une vue tabulaire + actions bulk en
    secours (filtre par région, ouvrir/fermer une sélection).
    """

    list_display = ("code", "nom", "region_label", "est_ouvert")
    list_filter = ("est_ouvert", "region_label")
    search_fields = ("code", "nom", "region_label", "region_code")
    list_editable = ("est_ouvert",)
    ordering = ("region_label", "ordre_affichage", "code")
    actions = ("ouvrir_selection", "fermer_selection")

    @admin.action(description="Ouvrir le simulateur pour les départements sélectionnés")
    def ouvrir_selection(self, request, queryset):
        n = queryset.update(est_ouvert=True)
        self.message_user(request, f"{n} département(s) ouvert(s).")

    @admin.action(description="Fermer le simulateur pour les départements sélectionnés")
    def fermer_selection(self, request, queryset):
        n = queryset.update(est_ouvert=False)
        self.message_user(request, f"{n} département(s) fermé(s).")


# ─── Contenu riche éditable « textes volants » (carte #131) ──────────────────

from envergo.nitrates.models import ContenuRichDSFR  # noqa: E402


class ContenuRichDSFRForm(forms.ModelForm):
    class Meta:
        model = ContenuRichDSFR
        fields = "__all__"
        widgets = {"blocs": ContenuRichEditorWidget}

    def clean_blocs(self):
        return _clean_blocs_json(self.cleaned_data.get("blocs"))


@admin.register(ContenuRichDSFR)
class ContenuRichDSFRAdmin(admin.ModelAdmin):
    form = ContenuRichDSFRForm
    list_display = ("cle", "libelle_admin", "updated_at")
    search_fields = ("cle", "libelle_admin")
    readonly_fields = ("updated_at", "apercu_rendu")

    @admin.display(description="Aperçu du rendu")
    def apercu_rendu(self, obj):
        """Lien (nouvel onglet) vers la prévisualisation du rendu HTML DSFR de
        ce contenu (carte #136)."""
        if not obj or not obj.pk:
            return "— (enregistrer d'abord)"
        url = reverse("nitrates_admin_contenu_rich_preview") + f"?type=rich&id={obj.pk}"
        return format_html(
            '<a class="button" href="{}" target="_blank" rel="noopener">'
            "🔎 Prévisualiser le rendu</a>",
            url,
        )
