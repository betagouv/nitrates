"""Admin Django pour l'app nitrates.

Note : `MoulinetteNitrates` n'est pas un model Django (il herite de
`Moulinette` qui est une ABC Python sans table DB), il n'apparait donc
pas ici.
"""

from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from envergo.nitrates.models import DecisionTree, RpgCulture


@admin.register(RpgCulture)
class RpgCultureAdmin(admin.ModelAdmin):
    list_display = ("code", "libelle", "code_groupe", "libelle_groupe")
    list_filter = ("code_groupe",)
    search_fields = ("code", "libelle", "libelle_groupe")
    ordering = ("code",)


@admin.register(DecisionTree)
class DecisionTreeAdmin(admin.ModelAdmin):
    change_list_template = "admin/nitrates/decisiontree/change_list.html"

    list_display = (
        "name",
        "status_badge",
        "activated_at",
        "updated_at",
        "created_at",
        "created_by",
        "actions_links",
    )
    list_filter = ("status",)
    search_fields = ("name",)
    ordering = ("-activated_at", "-created_at")
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
            edit_active_url = reverse("nitrates_admin_yaml_edit_active")
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
        view_url = reverse("nitrates_admin_yaml_tree") + f"?tree_id={obj.pk}"
        edit_url = view_url + "&mode=edition"
        clone_url = reverse("nitrates_admin_yaml_clone_confirm", kwargs={"pk": obj.pk})
        edit_active_url = reverse("nitrates_admin_yaml_edit_active")
        if obj.status == DecisionTree.STATUS_DRAFT:
            # Draft : on ouvre directement en mode edition.
            return mark_safe(
                f'<a class="button" href="{view_url}">Voir</a> '
                f'<a class="button" href="{edit_url}">Éditer</a>'
            )
        if obj.status == DecisionTree.STATUS_ACTIVE:
            # Active : Voir + "Éditer" qui clone vers un draft puis bascule.
            return mark_safe(
                f'<a class="button" href="{view_url}">Voir</a> '
                f'<a class="button" href="{edit_active_url}">Éditer</a>'
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
