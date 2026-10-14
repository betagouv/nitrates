"""Admin de l'historique des PC et contenus riches (cf. historique.py).

- Motif obligatoire à chaque enregistrement d'un PC ou d'un contenu riche.
- Une page d'historique par PC / contenu (bouton « Historique » de la fiche) :
  toutes les versions avec un résumé de ce qui a changé ; un clic affiche
  la différence avec la version précédente (texte rendu, mot à mot, et
  métadonnées) ; deux versions quelconques se comparent comme dans un
  historique de wiki ; le rendu de chaque version est celui du site public.
"""

import difflib
import json
import re

from django import forms
from django.contrib import admin
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.timezone import localtime

from envergo.nitrates import historique
from envergo.nitrates.models import RevisionContenu

NB_REVISIONS_FICHE = 5
# Lignes inchangées gardées autour d'un changement ; le reste est replié.
CONTEXTE = 2


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


def url_historique(type_objet, identifiant, **params):
    url = reverse(
        "admin:nitrates_revisioncontenu_historique", args=[type_objet, identifiant]
    )
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items() if v)
    return url


class HistoriqueAdminMixin:
    """Pose le contexte d'historique autour des écritures de l'admin : une
    révision par enregistrement, sur l'état final (après M2M), signée par
    l'utilisateur et portant le motif saisi. Le bouton « Historique » de la
    fiche mène à la page d'historique du contenu."""

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

    def history_view(self, request, object_id, extra_context=None):
        obj = self.get_object(request, object_id)
        if obj is None:
            raise Http404
        return redirect(
            url_historique(
                historique.type_objet(obj), historique.identifiant_metier(obj)
            )
        )

    @admin.display(description="Historique")
    def historique_revisions(self, obj):
        if not obj or not obj.pk:
            return "—"
        type_obj = historique.type_objet(obj)
        ident = historique.identifiant_metier(obj)
        revisions = list(
            RevisionContenu.objects.filter(type_objet=type_obj, identifiant=ident)
            .select_related("auteur")
            .order_by("created_at", "pk")
        )
        if not revisions:
            return "Aucune révision enregistrée."
        resumes = _resumes(revisions)
        dernieres = list(reversed(revisions))[:NB_REVISIONS_FICHE]
        lignes = format_html_join(
            "",
            "<li><a href='{}'>{}</a> · {} · {} : <span{}>{}</span></li>",
            (
                (
                    url_historique(type_obj, ident, a=r.pk),
                    _quand(r),
                    r.environnement,
                    _qui(r),
                    mark_safe(" style='color:#c9191e'") if resumes[r.pk][1] else "",
                    resumes[r.pk][0],
                )
                for r in dernieres
            ),
        )
        return format_html(
            "<ul style='margin:0;padding-left:1.2em'>{}</ul>"
            "<p><a class='button' href='{}'>Voir tout l'historique ({} versions)</a></p>",
            lignes,
            url_historique(type_obj, ident),
            len(revisions),
        )


def _quand(revision):
    return f"{localtime(revision.created_at):%d/%m/%Y %H:%M}"


def _qui(revision):
    qui = revision.auteur.email if revision.auteur_id else ""
    canal = revision.get_origine_display()
    if revision.source and revision.source != "admin":
        canal = f"{canal} ({revision.source})"
    return f"{qui} · {canal}" if qui else canal


# ─── Texte rendu et différences ──────────────────────────────────────────────


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


_MOTS = re.compile(r"\s+|\w+|[^\w\s]", re.UNICODE)


def _diff_mots(avant, apres):
    """Une ligne modifiée, mot à mot : <del> retiré, <ins> ajouté."""
    a, b = _MOTS.findall(avant), _MOTS.findall(apres)
    morceaux = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if op == "equal":
            morceaux.append(format_html("{}", "".join(a[i1:i2])))
            continue
        if i2 > i1:
            morceaux.append(format_html("<del>{}</del>", "".join(a[i1:i2])))
        if j2 > j1:
            morceaux.append(format_html("<ins>{}</ins>", "".join(b[j1:j2])))
    return mark_safe("".join(morceaux))


def diff_lignes(avant, apres):
    """Différence ligne à ligne : liste de (genre, html, loin) avec genre parmi
    egal / modif / ajout / retrait ; `loin` = ligne inchangée éloignée d'un
    changement (repliée par défaut)."""
    sortie = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, avant, apres, autojunk=False
    ).get_opcodes():
        if op == "equal":
            sortie += [
                ["egal", format_html("{}", ligne), False] for ligne in avant[i1:i2]
            ]
        elif op == "delete":
            sortie += [
                ["retrait", format_html("{}", ligne), False] for ligne in avant[i1:i2]
            ]
        elif op == "insert":
            sortie += [
                ["ajout", format_html("{}", ligne), False] for ligne in apres[j1:j2]
            ]
        else:
            vieux, neufs = avant[i1:i2], apres[j1:j2]
            for k in range(max(len(vieux), len(neufs))):
                v = vieux[k] if k < len(vieux) else None
                n = neufs[k] if k < len(neufs) else None
                if v is not None and n is not None:
                    if difflib.SequenceMatcher(None, v, n).ratio() >= 0.4:
                        sortie.append(["modif", _diff_mots(v, n), False])
                        continue
                    sortie.append(["retrait", format_html("{}", v), False])
                    sortie.append(["ajout", format_html("{}", n), False])
                elif v is not None:
                    sortie.append(["retrait", format_html("{}", v), False])
                else:
                    sortie.append(["ajout", format_html("{}", n), False])
    changes = [i for i, (genre, _, _) in enumerate(sortie) if genre != "egal"]
    for i, ligne in enumerate(sortie):
        if ligne[0] == "egal":
            ligne[2] = not any(abs(i - c) <= CONTEXTE for c in changes)
    return [tuple(ligne) for ligne in sortie]


def grouper(lignes):
    """Regroupe les lignes inchangées éloignées des changements en plis
    dépliables (comme les « lignes masquées » d'un diff GitHub)."""
    groupes = []
    for genre, html, loin in lignes:
        if loin and groupes and groupes[-1]["pli"]:
            groupes[-1]["lignes"].append((genre, html))
        else:
            groupes.append({"pli": loin, "lignes": [(genre, html)]})
    return groupes


def resume_changement(avant, apres):
    """Résumé lisible d'une version par rapport à la précédente, et un drapeau
    « du texte a disparu » (pour le signaler en rouge)."""
    if avant is None:
        n = len(textes_rendus(apres.get("blocs")))
        return f"Version initiale ({n} lignes)", False
    lignes = diff_lignes(
        textes_rendus(avant.get("blocs")), textes_rendus(apres.get("blocs"))
    )
    retraits = [html for genre, html, _ in lignes if genre == "retrait"]
    sous_puces = sum(1 for html in retraits if str(html).lstrip().startswith("◦"))
    parties = []
    if sous_puces:
        parties.append(
            f"{sous_puces} sous-puce{'s' if sous_puces > 1 else ''} supprimée{'s' if sous_puces > 1 else ''}"
        )
    autres = len(retraits) - sous_puces
    if autres:
        parties.append(
            f"{autres} ligne{'s' if autres > 1 else ''} supprimée{'s' if autres > 1 else ''}"
        )
    for genre, libelle in (("modif", "modifiée"), ("ajout", "ajoutée")):
        n = sum(1 for g, _, _ in lignes if g == genre)
        if n:
            parties.append(
                f"{n} ligne{'s' if n > 1 else ''} {libelle}{'s' if n > 1 else ''}"
            )
    metas = [k for k in historique.champs_differents(avant, apres) if k != "blocs"]
    if metas:
        parties.append("métadonnées : " + ", ".join(metas))
    return (", ".join(parties) or "Aucun changement visible"), bool(retraits)


def _resumes(revisions):
    """{pk: (résumé, perte)} pour une liste chronologique de révisions."""
    resumes, precedente = {}, None
    for r in revisions:
        if r.action == RevisionContenu.ACTION_SUPPRESSION:
            resumes[r.pk] = ("Contenu supprimé", True)
        else:
            resumes[r.pk] = resume_changement(precedente, r.instantane)
        precedente = (
            None if r.action == RevisionContenu.ACTION_SUPPRESSION else r.instantane
        )
    return resumes


# ─── Admin des révisions + page d'historique ─────────────────────────────────


@admin.register(RevisionContenu)
class RevisionContenuAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "type_objet",
        "lien_historique",
        "action",
        "environnement",
        "origine",
        "auteur",
        "motif",
    )
    list_filter = ("type_objet", "action", "origine", "environnement")
    search_fields = ("identifiant", "motif", "source", "auteur__email")
    date_hierarchy = "created_at"

    def get_urls(self):
        return [
            path(
                "historique/<str:type_objet>/<str:identifiant>/",
                self.admin_site.admin_view(self.historique_view),
                name="nitrates_revisioncontenu_historique",
            ),
            *super().get_urls(),
        ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
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

    @admin.display(description="Contenu", ordering="identifiant")
    def lien_historique(self, obj):
        return format_html(
            "<a href='{}'>{}</a>",
            url_historique(obj.type_objet, obj.identifiant, a=obj.pk),
            obj.identifiant,
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        revision = RevisionContenu.objects.filter(pk=object_id).first()
        if revision is None:
            raise Http404
        return redirect(
            url_historique(revision.type_objet, revision.identifiant, a=revision.pk)
        )

    def historique_view(self, request, type_objet, identifiant):
        if not self.has_view_permission(request):
            raise Http404
        revisions = list(
            RevisionContenu.objects.filter(
                type_objet=type_objet, identifiant=identifiant
            )
            .select_related("auteur")
            .order_by("created_at", "pk")
        )
        if not revisions:
            raise Http404("Aucun historique pour ce contenu.")
        par_pk = {r.pk: r for r in revisions}
        rang = {r.pk: i for i, r in enumerate(revisions)}

        def choisie(param):
            valeur = request.GET.get(param, "")
            return par_pk.get(int(valeur)) if valeur.isdigit() else None

        cible = choisie("a") or revisions[-1]
        base = choisie("de")
        if base is None:
            i = rang[cible.pk]
            base = revisions[i - 1] if i > 0 else None
        elif rang[base.pk] > rang[cible.pk]:
            base, cible = cible, base
        if base is not None and base.pk == cible.pk:
            base = None

        avant = base.instantane if base else {}
        apres = cible.instantane
        lignes = diff_lignes(
            textes_rendus(avant.get("blocs")), textes_rendus(apres.get("blocs"))
        )
        metadonnees = [
            (
                k,
                json.dumps(avant.get(k), ensure_ascii=False),
                json.dumps(apres.get(k), ensure_ascii=False),
            )
            for k in historique.champs_differents(avant, apres)
            if k != "blocs"
        ]
        resumes = _resumes(revisions)
        versions = [
            {
                "revision": r,
                "quand": _quand(r),
                "qui": _qui(r),
                "resume": resumes[r.pk][0],
                "perte": resumes[r.pk][1],
                "lien": url_historique(type_objet, identifiant, a=r.pk),
                "est_cible": r.pk == cible.pk,
                "est_base": base is not None and r.pk == base.pk,
            }
            for r in reversed(revisions)
        ]
        objet = _objet_courant(type_objet, identifiant)
        apercu = reverse("nitrates_admin_contenu_rich_preview")
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": f"Historique de {identifiant}",
            "identifiant": identifiant,
            "type_libelle": dict(RevisionContenu.TYPES).get(type_objet, type_objet),
            "objet": objet,
            "objet_url": _url_objet(objet),
            "versions": versions,
            "cible": cible,
            "cible_quand": _quand(cible),
            "cible_qui": _qui(cible),
            "base": base,
            "base_quand": _quand(base) if base else "",
            "base_qui": _qui(base) if base else "",
            "groupes": grouper(lignes),
            "nb_changements": sum(1 for genre, _, _ in lignes if genre != "egal"),
            "metadonnees": metadonnees,
            "apercu_cible": f"{apercu}?type=revision&id={cible.pk}&nu=1",
            "apercu_base": f"{apercu}?type=revision&id={base.pk}&nu=1" if base else "",
        }
        return TemplateResponse(
            request, "admin/nitrates/historique_contenu.html", context
        )


def _objet_courant(type_objet, identifiant):
    from envergo.nitrates.models import CodePrescription, ContenuRichDSFR

    if type_objet == RevisionContenu.TYPE_PC:
        return CodePrescription.objects.filter(identifiant=identifiant).first()
    return ContenuRichDSFR.objects.filter(cle=identifiant).first()


def _url_objet(objet):
    if objet is None:
        return ""
    opts = objet._meta
    return reverse(f"admin:{opts.app_label}_{opts.model_name}_change", args=[objet.pk])


__all__ = ["HistoriqueAdminMixin", "MotifRevisionFormMixin"]
