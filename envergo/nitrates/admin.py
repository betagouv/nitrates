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
        "contenu",
        "contenu_yaml_brut",
        "created_at",
        "updated_at",
        "activated_at",
        "created_by",
    )
    fieldsets = (
        (None, {"fields": ("name", "status", "parent")}),
        (
            "Contenu",
            {
                "classes": ("collapse",),
                "fields": ("contenu_yaml_brut", "contenu"),
            },
        ),
        (
            "Métadonnées",
            {"fields": ("created_at", "updated_at", "activated_at", "created_by")},
        ),
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
        clone_url = reverse("nitrates_admin_yaml_clone_confirm", kwargs={"pk": obj.pk})
        if obj.status == DecisionTree.STATUS_DRAFT:
            # Sur un draft : juste Éditer (cloner un draft n'a pas de sens
            # immediat ; si on en a vraiment besoin, l'action dropdown reste).
            return mark_safe(f'<a class="button" href="{view_url}">Éditer</a>')
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
