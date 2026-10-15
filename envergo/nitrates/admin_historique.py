"""Admin de l'historique des PC et contenus riches (cf. historique.py).

- Motif obligatoire à chaque enregistrement d'un PC ou d'un contenu riche.
- Une page d'historique par PC / contenu (bouton « Historique » de la fiche) :
  les changements du plus récent au plus ancien, avec un résumé ; un clic
  affiche la différence avec la version précédente (texte rendu, mot à mot,
  et métadonnées) et le rendu du site avant / après.
- Annulation ligne à ligne : les lignes choisies d'un changement sont
  annulées par patch inverse sur la version ACTUELLE, ce qui crée une
  nouvelle version par-dessus (cf. historique_diff).
"""

import difflib
import hashlib
import json
import re

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.timezone import localtime

from envergo.nitrates import historique, historique_diff
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


# ─── Différences affichées ───────────────────────────────────────────────────

_MOTS = re.compile(r"\s+|\w+|[^\w\s]", re.UNICODE)
_CACHES = ("/liste", "/volet")


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


def _blocs(instantane):
    return (instantane or {}).get("blocs") or []


def lignes_comparaison(avant, apres, actuel=None):
    """Lignes affichées pour le changement avant -> apres, avec pour chaque
    ligne changée son identifiant d'annulation et si elle est annulable sur la
    version actuelle. Les marqueurs de fermeture ne sont pas affichés ; une
    ouverture de liste inchangée non plus."""
    actuel = apres if actuel is None else actuel
    ub, uc, lignes = historique_diff.lignes_annulables(
        _blocs(avant), _blocs(apres), _blocs(actuel)
    )
    sortie = []
    for lg in lignes:
        u = uc[lg["cible"]] if lg["cible"] is not None else ub[lg["base"]]
        if u["k"] in _CACHES or (lg["genre"] == "egal" and u["k"] == "liste"):
            continue
        if lg["genre"] == "modif":
            html = _diff_mots(
                historique_diff.libelle(ub[lg["base"]]), historique_diff.libelle(u)
            )
        else:
            html = format_html("{}", historique_diff.libelle(u))
        sortie.append(
            {
                "genre": lg["genre"],
                "signe": {"ajout": "+", "retrait": "−", "modif": "~"}.get(
                    lg["genre"], ""
                ),
                "html": html,
                "op": lg["op"],
                "annulable": lg.get("annulable", False),
                "deja": lg.get("deja", False),
            }
        )
    changes = [i for i, lg in enumerate(sortie) if lg["genre"] != "egal"]
    for i, lg in enumerate(sortie):
        lg["loin"] = lg["genre"] == "egal" and not any(
            abs(i - c) <= CONTEXTE for c in changes
        )
    return sortie


def grouper(lignes):
    """Regroupe les lignes inchangées éloignées des changements en plis
    dépliables (comme les « lignes masquées » d'un diff GitHub)."""
    groupes = []
    for lg in lignes:
        if lg["loin"] and groupes and groupes[-1]["pli"]:
            groupes[-1]["lignes"].append(lg)
        else:
            groupes.append({"pli": lg["loin"], "lignes": [lg]})
    return groupes


def resume_changement(avant, apres):
    """Résumé lisible d'une version par rapport à la précédente, et un drapeau
    « du texte a disparu » (pour le signaler en rouge)."""
    if avant is None:
        n = sum(
            1
            for u in historique_diff.lineariser(_blocs(apres))
            if u["k"] not in ("liste",) + _CACHES
        )
        return f"Version initiale ({n} lignes)", False
    ub, uc, lignes = historique_diff.differences(_blocs(avant), _blocs(apres))
    visibles = [
        (lg, uc[lg["cible"]] if lg["cible"] is not None else ub[lg["base"]])
        for lg in lignes
        if lg["genre"] != "egal"
    ]
    visibles = [(lg, u) for lg, u in visibles if u["k"] not in ("liste",) + _CACHES]
    retraits = [u for lg, u in visibles if lg["genre"] == "retrait"]
    sous_puces = sum(1 for u in retraits if u["k"] == "item" and u["d"] > 0)
    parties = []
    if sous_puces:
        s = "s" if sous_puces > 1 else ""
        parties.append(f"{sous_puces} sous-puce{s} supprimée{s}")
    autres = len(retraits) - sous_puces
    if autres:
        s = "s" if autres > 1 else ""
        parties.append(f"{autres} ligne{s} supprimée{s}")
    for genre, libelle_genre in (("modif", "modifiée"), ("ajout", "ajoutée")):
        n = sum(1 for lg, _ in visibles if lg["genre"] == genre)
        if n:
            s = "s" if n > 1 else ""
            parties.append(f"{n} ligne{s} {libelle_genre}{s}")
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


def lieu_courant():
    """Environnement et base où l'on écrit, ex « dev (base nitrates_de_4422) »."""
    env = getattr(settings, "ENV_NAME", "") or "?"
    base = connection.settings_dict.get("NAME") or "?"
    return f"{env} (base {base})"


def motif_annulation_defaut(cible):
    """Motif proposé pour une annulation : où elle est faite, et quelle version
    elle annule (avec son environnement d'origine), pour suivre un contenu qui
    passe d'un environnement à l'autre."""
    return (
        f"Sur {lieu_courant()} : annulation de changements de la version du "
        f"{_quand(cible)} ({cible.environnement or '?'}, {_qui(cible)})"
    )


def empreinte(instantane):
    return hashlib.sha1(
        json.dumps(instantane, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


# Métadonnées remises à leur valeur d'avant par une annulation.
_META_SIMPLES = {
    RevisionContenu.TYPE_PC: (
        "mots_cles",
        "toujours_affiche",
        "plafond",
        "scope",
        "region_code",
        "ordre_affichage",
    ),
    RevisionContenu.TYPE_CONTENU_RICH: (
        "libelle_admin",
        "type_contenu",
        "titre_public",
        "categorie",
        "termes_declencheurs",
    ),
}
_META_LIENS = ("note_reglementaire", "variante_de", "composants_fusion")


def _meta_annulable(type_obj, champ):
    return champ in _META_SIMPLES.get(type_obj, ()) or (
        type_obj == RevisionContenu.TYPE_PC and champ in _META_LIENS
    )


def _appliquer_meta(objet, champ, valeur):
    from envergo.nitrates.models import CodePrescription, NoteReglementaire

    if champ == "note_reglementaire":
        objet.note_reglementaire = (
            NoteReglementaire.objects.filter(identifiant=valeur).first()
            if valeur
            else None
        )
    elif champ == "variante_de":
        objet.variante_de = (
            CodePrescription.objects.filter(identifiant=valeur).first()
            if valeur
            else None
        )
    elif champ == "composants_fusion":
        return lambda: objet.composants_fusion.set(
            CodePrescription.objects.filter(identifiant__in=valeur or [])
        )
    else:
        setattr(objet, champ, valeur)
    return None


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
                "historique/<str:type_objet>/<str:identifiant>/annuler/",
                self.admin_site.admin_view(self.annuler_view),
                name="nitrates_revisioncontenu_annuler",
            ),
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

    # ── Page d'historique ──

    @staticmethod
    def _revisions(type_objet, identifiant):
        return list(
            RevisionContenu.objects.filter(
                type_objet=type_objet, identifiant=identifiant
            )
            .select_related("auteur")
            .order_by("created_at", "pk")
        )

    @staticmethod
    def _peut_annuler(request, type_objet, objet, cible, base):
        modele = (
            "codeprescription"
            if type_objet == RevisionContenu.TYPE_PC
            else "contenurichdsfr"
        )
        return (
            objet is not None
            and base is not None
            and cible.action
            in (RevisionContenu.ACTION_MODIFICATION, RevisionContenu.ACTION_CONSTAT)
            and request.user.has_perm(f"nitrates.change_{modele}")
        )

    def historique_view(self, request, type_objet, identifiant):
        if not self.has_view_permission(request):
            raise Http404
        revisions = self._revisions(type_objet, identifiant)
        if not revisions:
            raise Http404("Aucun historique pour ce contenu.")
        par_pk = {r.pk: r for r in revisions}
        valeur = request.GET.get("a", "")
        cible = par_pk.get(int(valeur)) if valeur.isdigit() else None
        cible = cible or revisions[-1]
        base = _version_precedente(revisions, cible)

        objet = _objet_courant(type_objet, identifiant)
        actuel = historique.instantane(objet) if objet else cible.instantane
        avant = base.instantane if base else {}
        lignes = lignes_comparaison(avant, cible.instantane, actuel)
        peut_annuler = self._peut_annuler(request, type_objet, objet, cible, base)
        metadonnees = [
            {
                "champ": k,
                "avant": json.dumps(avant.get(k), ensure_ascii=False),
                "apres": json.dumps(cible.instantane.get(k), ensure_ascii=False),
                "annulable": peut_annuler
                and _meta_annulable(type_objet, k)
                and actuel.get(k) == cible.instantane.get(k),
            }
            for k in historique.champs_differents(avant, cible.instantane)
            if k != "blocs" and base is not None
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
                "selectionnee": r.pk == cible.pk,
                "actuelle": r.pk == revisions[-1].pk,
            }
            for r in reversed(revisions)
        ]
        apercu = reverse("nitrates_admin_contenu_rich_preview")
        url_public = ""
        if type_objet == RevisionContenu.TYPE_PC and objet is not None:
            url_public = reverse("nitrates_prescription_detail", args=[identifiant])
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": f"Historique de {identifiant}",
            "identifiant": identifiant,
            "type_libelle": dict(RevisionContenu.TYPES).get(type_objet, type_objet),
            "objet": objet,
            "objet_url": _url_objet(objet),
            "url_public": url_public,
            "versions": versions,
            "cible": cible,
            "cible_quand": _quand(cible),
            "cible_qui": _qui(cible),
            "base": base,
            "base_quand": _quand(base) if base else "",
            "groupes": grouper(lignes),
            "nb_changements": sum(1 for lg in lignes if lg["genre"] != "egal"),
            "nb_annulables": sum(1 for lg in lignes if lg["annulable"])
            + sum(1 for m in metadonnees if m["annulable"]),
            "metadonnees": metadonnees,
            "peut_annuler": peut_annuler,
            "etat": empreinte(actuel),
            "url_annuler": reverse(
                "admin:nitrates_revisioncontenu_annuler", args=[type_objet, identifiant]
            ),
            "motif_defaut": motif_annulation_defaut(cible),
            "apercu_cible": f"{apercu}?type=revision&id={cible.pk}&nu=1",
            "apercu_base": f"{apercu}?type=revision&id={base.pk}&nu=1" if base else "",
        }
        return TemplateResponse(
            request, "admin/nitrates/historique_contenu.html", context
        )

    # ── Annulation : patch inverse appliqué à la version actuelle ──

    def annuler_view(self, request, type_objet, identifiant):
        if request.method != "POST":
            return redirect(url_historique(type_objet, identifiant))
        revisions = self._revisions(type_objet, identifiant)
        par_pk = {r.pk: r for r in revisions}
        valeur = request.POST.get("revision", "")
        cible = par_pk.get(int(valeur)) if valeur.isdigit() else None
        if cible is None:
            raise Http404
        retour = url_historique(type_objet, identifiant, a=cible.pk)
        base = _version_precedente(revisions, cible)
        objet = _objet_courant(type_objet, identifiant)
        if not self._peut_annuler(request, type_objet, objet, cible, base):
            raise PermissionDenied
        actuel = historique.instantane(objet)
        if request.POST.get("etat") != empreinte(actuel):
            messages.error(
                request,
                "Ce contenu a été modifié depuis l'affichage de la page : rien "
                "n'a été enregistré. Rechargez et recommencez.",
            )
            return redirect(retour)
        ops = [o for o in request.POST.getlist("ops") if o]
        metas = [
            m for m in request.POST.getlist("metas") if _meta_annulable(type_objet, m)
        ]
        motif = request.POST.get("motif", "").strip()
        if not (ops or metas):
            messages.error(
                request, "Aucune ligne sélectionnée : rien n'a été enregistré."
            )
            return redirect(retour)
        if not motif:
            messages.error(
                request, "Le motif est obligatoire : rien n'a été enregistré."
            )
            return redirect(retour)
        try:
            nouveaux_blocs = (
                historique_diff.annuler(
                    base.instantane.get("blocs"),
                    cible.instantane.get("blocs"),
                    objet.blocs,
                    ops,
                )
                if ops
                else objet.blocs
            )
        except historique_diff.Conflit as e:
            messages.error(request, f"{e} Rien n'a été enregistré.")
            return redirect(retour)
        apres_m2m = []
        for champ in metas:
            if actuel.get(champ) != cible.instantane.get(champ):
                messages.error(
                    request,
                    f"Le champ « {champ} » a changé depuis : rien n'a été enregistré.",
                )
                return redirect(retour)
            differe = _appliquer_meta(objet, champ, base.instantane.get(champ))
            if differe:
                apres_m2m.append(differe)
        with transaction.atomic(), historique.contexte_revision(
            origine=RevisionContenu.ORIGINE_ADMIN,
            source="admin (annulation)",
            motif=motif,
            auteur=request.user,
            differer=True,
        ):
            objet.blocs = nouveaux_blocs
            objet.save()
            for f in apres_m2m:
                f()
        n = len(ops) + len(metas)
        messages.success(
            request,
            f"Nouvelle version enregistrée : {n} changement{'s' if n > 1 else ''} annulé{'s' if n > 1 else ''}.",
        )
        return redirect(url_historique(type_objet, identifiant))


def _version_precedente(revisions, cible):
    """Version de départ d'un changement ; aucune après une suppression."""
    i = revisions.index(cible)
    if i == 0 or revisions[i - 1].action == RevisionContenu.ACTION_SUPPRESSION:
        return None
    return revisions[i - 1]


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
