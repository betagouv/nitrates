"""Admin de l'historique des PC et contenus riches (cf. historique.py).

- Motif obligatoire à chaque enregistrement d'un PC ou d'un contenu riche.
- Sur la fiche, la liste des révisions (où, quand, qui, canal, motif).
- Sur une révision : ce qui a changé par rapport à la précédente (textes
  rendus et métadonnées) et l'aperçu du rendu de cette version.
"""

import difflib
import json

from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.timezone import localtime

from envergo.nitrates import historique
from envergo.nitrates.contenu_rich.compilateur import compile_dsfr
from envergo.nitrates.models import RevisionContenu

NB_REVISIONS_FICHE = 50


class MotifRevisionFormMixin(forms.Form):
    motif_modification = forms.CharField(
        label="Motif de la modification",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text=(
            "Obligatoire, consigné dans l'historique. Dites ce qui change et "
            "d'où ça vient, ex « reformulation retour juristes », « copié "
            "depuis staging le 14/10 »."
        ),
    )


class HistoriqueAdminMixin:
    """Pose le contexte d'historique autour des écritures de l'admin : une
    révision par enregistrement, sur l'état final (après M2M), signée par
    l'utilisateur et portant le motif saisi."""

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method != "POST":
            return super().changeform_view(request, object_id, form_url, extra_context)
        with historique.contexte_revision(
            origine=RevisionContenu.ORIGINE_ADMIN,
            source="admin",
            motif=request.POST.get("motif_modification", "").strip(),
            auteur=request.user,
            differer=True,
        ):
            return super().changeform_view(request, object_id, form_url, extra_context)

    def delete_view(self, request, object_id, extra_context=None):
        with historique.contexte_revision(
            origine=RevisionContenu.ORIGINE_ADMIN,
            source="admin",
            motif="Suppression depuis l'admin.",
            auteur=request.user,
        ):
            return super().delete_view(request, object_id, extra_context)

    @admin.display(description="Historique")
    def historique_revisions(self, obj):
        if not obj or not obj.pk:
            return "—"
        revisions = RevisionContenu.objects.filter(
            type_objet=historique.type_objet(obj),
            identifiant=historique.identifiant_metier(obj),
        ).select_related("auteur")[:NB_REVISIONS_FICHE]
        if not revisions:
            return "Aucune révision enregistrée."
        lignes = format_html_join(
            "",
            "<tr><td><a href='{}'>{}</a></td><td>{}</td><td>{}</td><td>{}</td>"
            "<td>{}</td><td>{}</td></tr>",
            (
                (
                    reverse("admin:nitrates_revisioncontenu_change", args=[r.pk]),
                    f"{localtime(r.created_at):%d/%m/%Y %H:%M}",
                    r.environnement,
                    r.get_action_display(),
                    _qui(r),
                    ", ".join(r.champs_modifies),
                    r.motif,
                )
                for r in revisions
            ),
        )
        return format_html(
            "<table><thead><tr><th>Quand</th><th>Env</th><th>Action</th>"
            "<th>Qui / canal</th><th>Champs</th><th>Motif</th></tr></thead>"
            "<tbody>{}</tbody></table>",
            lignes,
        )


def _qui(revision):
    qui = revision.auteur.email if revision.auteur_id else ""
    canal = revision.get_origine_display()
    if revision.source and revision.source != "admin":
        canal = f"{canal} ({revision.source})"
    return f"{qui} · {canal}" if qui else canal


def _texte(valeur):
    if isinstance(valeur, list):
        return "".join(
            s if isinstance(s, str) else (s or {}).get("texte", "") for s in valeur
        )
    return valeur or ""


def textes_rendus(blocs, retrait=""):
    """Lignes de texte telles qu'un usager les lit (pour comparer deux
    versions sans lire de JSON)."""
    if isinstance(blocs, dict):
        blocs = blocs.get("blocs") or []
    lignes = []

    def items(liste, niveau):
        for item in liste or []:
            item = item if isinstance(item, dict) else {"texte": item}
            puce = "•" if niveau == 0 else "◦"
            lignes.append(
                f"{retrait}{'    ' * (niveau + 1)}{puce} {_texte(item.get('texte'))}"
            )
            items(item.get("enfants"), niveau + 1)

    for bloc in blocs or []:
        data = bloc.get("data") or {}
        t = bloc.get("type")
        if t == "titre_principal":
            lignes.append(f"{retrait}# {_texte(data.get('texte'))}")
        elif t == "titre_paragraphe":
            lignes.append(f"{retrait}## {_texte(data.get('texte'))}")
        elif t in ("paragraphe", "citation"):
            lignes.append(f"{retrait}{_texte(data.get('texte'))}")
        elif t == "liste":
            items(data.get("items"), 0)
        elif t == "foldable":
            lignes.append(f"{retrait}▸ {_texte(data.get('titre'))}")
            lignes.extend(textes_rendus(data.get("blocs"), retrait + "    "))
        elif t == "tableau":
            for ligne in data.get("lignes") or []:
                lignes.append(
                    f"{retrait}| " + " | ".join(_texte(c) for c in ligne) + " |"
                )
        else:
            lignes.append(f"{retrait}[{t}]")
    return lignes


def _diff_html(avant, apres):
    styles = {
        "+": "background:#d4f7d4",
        "-": "background:#fbd5d5;text-decoration:line-through",
    }
    lignes = [
        (styles.get(ligne[:1], ""), ligne)
        for ligne in difflib.ndiff(avant, apres)
        if not ligne.startswith("?")
    ]
    return format_html(
        "<pre style='white-space:pre-wrap;font-size:12px'>{}</pre>",
        format_html_join("", "<div style='{}'>{}</div>", lignes),
    )


@admin.register(RevisionContenu)
class RevisionContenuAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "type_objet",
        "identifiant",
        "action",
        "environnement",
        "origine",
        "auteur",
        "champs",
        "motif",
    )
    list_filter = ("type_objet", "action", "origine", "environnement")
    search_fields = ("identifiant", "motif", "source", "auteur__email")
    date_hierarchy = "created_at"
    fields = (
        "resume",
        "changements_textes",
        "changements_metadonnees",
        "apercu_version",
        "instantane_json",
    )
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        # Quiconque peut consulter les PC ou les contenus riches lit leur
        # historique, sans permission dédiée à attribuer.
        user = request.user
        return any(
            user.has_perm(f"nitrates.{action}_{modele}")
            for action in ("view", "change")
            for modele in ("codeprescription", "contenurichdsfr")
        )

    def has_module_permission(self, request):
        return self.has_view_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Champs modifiés")
    def champs(self, obj):
        return ", ".join(obj.champs_modifies)

    @admin.display(description="Révision")
    def resume(self, obj):
        precedente = obj.precedente()
        lien_prec = (
            format_html(
                "<a href='{}'>révision précédente ({})</a>",
                reverse("admin:nitrates_revisioncontenu_change", args=[precedente.pk]),
                f"{localtime(precedente.created_at):%d/%m/%Y %H:%M}",
            )
            if precedente
            else "aucune révision précédente"
        )
        return format_html(
            "<strong>{}</strong> {} · {} · env <strong>{}</strong> · {}<br>"
            "{}<br>Motif : {}<br>Champs modifiés : {}<br>{}",
            obj.get_type_objet_display(),
            obj.identifiant,
            obj.get_action_display(),
            obj.environnement or "?",
            f"{localtime(obj.created_at):%d/%m/%Y %H:%M}",
            _qui(obj),
            obj.motif or "—",
            ", ".join(obj.champs_modifies) or "—",
            lien_prec,
        )

    @admin.display(description="Textes rendus (avant → cette version)")
    def changements_textes(self, obj):
        precedente = obj.precedente()
        avant = textes_rendus(
            (precedente.instantane if precedente else {}).get("blocs")
        )
        return _diff_html(avant, textes_rendus(obj.instantane.get("blocs")))

    @admin.display(description="Métadonnées modifiées")
    def changements_metadonnees(self, obj):
        precedente = obj.precedente()
        avant = precedente.instantane if precedente else {}
        lignes = [
            (
                k,
                json.dumps(avant.get(k), ensure_ascii=False),
                json.dumps(obj.instantane.get(k), ensure_ascii=False),
            )
            for k in historique.champs_differents(avant, obj.instantane)
            if k != "blocs"
        ]
        if not lignes:
            return "—"
        return format_html(
            "<table><tr><th>Champ</th><th>Avant</th><th>Après</th></tr>{}</table>",
            format_html_join("", "<tr><td>{}</td><td>{}</td><td>{}</td></tr>", lignes),
        )

    @admin.display(description="Aperçu du rendu de cette version")
    def apercu_version(self, obj):
        return compile_dsfr(
            obj.instantane.get("blocs") or [], id_prefix=f"revision-{obj.pk}"
        )

    @admin.display(description="Instantané complet (JSON)")
    def instantane_json(self, obj):
        return format_html(
            "<details><summary>afficher</summary><pre style='font-size:11px'>{}</pre></details>",
            json.dumps(obj.instantane, ensure_ascii=False, indent=2),
        )


__all__ = ["HistoriqueAdminMixin", "MotifRevisionFormMixin"]
