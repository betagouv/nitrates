"""Capture de l'historique des PC et contenus riches (cf. models_historique).

Toute écriture passant par l'ORM (save, create, update_or_create, loaddata,
suppression, composants de fusion) laisse une `RevisionContenu`. Le canal est
déduit automatiquement (commande manage.py, migration, fixture) ; l'admin et
les commandes qui le souhaitent posent un contexte explicite :

    with contexte_revision(origine="commande", motif="copié depuis staging"):
        ...

En mode `differer=True`, les objets touchés sont collectés et une seule
révision par objet est écrite à la sortie du contexte, sur l'état final relu
en base (après M2M, après restauration de blocs par update(), etc.).

Les `QuerySet.update()` et le SQL direct ne déclenchent aucun signal : la
commande `constater_historique_contenus` (jouée au déploiement) détecte ces
écarts et les consigne en révision « constat ».

Le motif par défaut peut aussi venir de l'environnement :
    NITRATES_MOTIF_REVISION="copié depuis dev" python manage.py ...
"""

import contextvars
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field

from django.conf import settings

_contexte = contextvars.ContextVar("contexte_revision_contenu", default=None)


@dataclass
class _Contexte:
    origine: str
    source: str = ""
    motif: str = ""
    auteur: object = None
    differer: bool = False
    en_attente: dict = field(default_factory=dict)


# ─── Instantanés : ce qui est rendu + métadonnées ────────────────────────────


def _modeles():
    from envergo.nitrates.models import CodePrescription, ContenuRichDSFR

    return CodePrescription, ContenuRichDSFR


def type_objet(instance):
    from envergo.nitrates.models import RevisionContenu

    CodePrescription, ContenuRichDSFR = _modeles()
    if isinstance(instance, CodePrescription):
        return RevisionContenu.TYPE_PC
    if isinstance(instance, ContenuRichDSFR):
        return RevisionContenu.TYPE_CONTENU_RICH
    return None


def identifiant_metier(instance):
    CodePrescription, _ = _modeles()
    if isinstance(instance, CodePrescription):
        return instance.identifiant
    return instance.cle


def instantane(instance):
    """État suivi d'un objet. `texte_court` et `texte_redaction_initiale`
    des PC sont volontairement exclus (reliquats, seul le bloc est rendu)."""
    CodePrescription, _ = _modeles()
    if isinstance(instance, CodePrescription):
        return {
            "identifiant": instance.identifiant,
            "blocs": instance.blocs,
            "mots_cles": instance.mots_cles,
            "toujours_affiche": instance.toujours_affiche,
            "plafond": instance.plafond,
            "note_reglementaire": (
                instance.note_reglementaire.identifiant
                if instance.note_reglementaire_id
                else None
            ),
            "scope": instance.scope,
            "region_code": instance.region_code,
            "variante_de": (
                instance.variante_de.identifiant if instance.variante_de_id else None
            ),
            "composants_fusion": (
                sorted(instance.composants_fusion.values_list("identifiant", flat=True))
                if instance.pk
                else []
            ),
            "ordre_affichage": instance.ordre_affichage,
        }
    return {
        "cle": instance.cle,
        "libelle_admin": instance.libelle_admin,
        "blocs": instance.blocs,
        "type_contenu": instance.type_contenu,
        "titre_public": instance.titre_public,
        "categorie": instance.categorie,
        "termes_declencheurs": instance.termes_declencheurs,
    }


# ─── Contexte ────────────────────────────────────────────────────────────────


def _contexte_implicite():
    """Canal déduit de la ligne de commande quand personne n'a posé de
    contexte (commande manage.py, migration, shell, worker web…)."""
    from envergo.nitrates.models import RevisionContenu

    motif = os.environ.get("NITRATES_MOTIF_REVISION", "")
    argv = sys.argv or []
    commande = ""
    if argv and os.path.basename(argv[0]) in ("manage.py", "django-admin"):
        commande = argv[1] if len(argv) > 1 else ""
    if commande == "migrate":
        return _Contexte(RevisionContenu.ORIGINE_MIGRATION, "migrate", motif)
    if commande == "loaddata":
        return _Contexte(
            RevisionContenu.ORIGINE_FIXTURE, " ".join(argv[1:])[:255], motif
        )
    if commande and commande != "shell":
        return _Contexte(
            RevisionContenu.ORIGINE_COMMANDE, " ".join(argv[1:])[:255], motif
        )
    return _Contexte(RevisionContenu.ORIGINE_CODE, commande, motif)


@contextmanager
def contexte_revision(origine, motif="", source="", auteur=None, differer=False):
    ctx = _Contexte(
        origine=origine,
        source=source,
        motif=motif or os.environ.get("NITRATES_MOTIF_REVISION", ""),
        auteur=auteur,
        differer=differer,
    )
    jeton = _contexte.set(ctx)
    try:
        yield ctx
    finally:
        _contexte.reset(jeton)
    if differer:
        for (modele, pk), _ in ctx.en_attente.items():
            objet = modele.objects.filter(pk=pk).first()
            if objet is not None:
                enregistrer(objet, ctx=ctx)


def contexte_courant():
    return _contexte.get()


# ─── Écriture d'une révision ─────────────────────────────────────────────────


def derniere_revision(type_obj, identifiant):
    from envergo.nitrates.models import RevisionContenu

    return (
        RevisionContenu.objects.filter(type_objet=type_obj, identifiant=identifiant)
        .order_by("-created_at", "-pk")
        .first()
    )


def champs_differents(avant, apres):
    avant = avant or {}
    return sorted(k for k in set(avant) | set(apres) if avant.get(k) != apres.get(k))


def enregistrer(instance, ctx=None, action=None, etat=None):
    """Écrit une révision si l'état suivi a changé depuis la dernière.

    `etat` : instantané déjà calculé (suppression : l'objet n'est plus lu).
    Renvoie la révision créée, ou None si rien n'a changé.
    """
    from envergo.nitrates.models import RevisionContenu

    type_obj = type_objet(instance)
    if type_obj is None:
        return None
    ctx = ctx or contexte_courant() or _contexte_implicite()
    ident = identifiant_metier(instance)
    etat = etat if etat is not None else instantane(instance)
    precedente = derniere_revision(type_obj, ident)
    existait = (
        precedente is not None
        and precedente.action != RevisionContenu.ACTION_SUPPRESSION
    )
    if action is None:
        action = (
            RevisionContenu.ACTION_MODIFICATION
            if existait
            else RevisionContenu.ACTION_CREATION
        )
    champs = champs_differents(precedente.instantane if existait else None, etat)
    if action != RevisionContenu.ACTION_SUPPRESSION and existait and not champs:
        return None
    auteur = ctx.auteur if getattr(ctx.auteur, "is_authenticated", False) else None
    return RevisionContenu.objects.create(
        type_objet=type_obj,
        identifiant=ident,
        action=action,
        champs_modifies=champs,
        instantane=etat,
        environnement=getattr(settings, "ENV_NAME", ""),
        origine=ctx.origine,
        source=ctx.source,
        motif=ctx.motif,
        auteur=auteur,
    )


# ─── Signaux ─────────────────────────────────────────────────────────────────


def _differer(instance):
    ctx = contexte_courant()
    if ctx and ctx.differer:
        ctx.en_attente[(type(instance), instance.pk)] = True
        return True
    return False


def apres_sauvegarde(sender, instance, raw=False, **kwargs):
    if _differer(instance):
        return
    ctx = contexte_courant()
    if raw and ctx is None:
        from envergo.nitrates.models import RevisionContenu

        implicite = _contexte_implicite()
        ctx = _Contexte(
            RevisionContenu.ORIGINE_FIXTURE, implicite.source, implicite.motif
        )
    enregistrer(instance, ctx=ctx)


def avant_suppression(sender, instance, **kwargs):
    # Instantané pris AVANT : après coup, les composants de fusion ont déjà
    # disparu avec les lignes de la table de liaison.
    instance._etat_avant_suppression = instantane(instance)


def apres_suppression(sender, instance, **kwargs):
    from envergo.nitrates.models import RevisionContenu

    ctx = contexte_courant()
    if ctx and ctx.differer:
        ctx.en_attente.pop((type(instance), instance.pk), None)
    enregistrer(
        instance,
        ctx=ctx,
        action=RevisionContenu.ACTION_SUPPRESSION,
        etat=getattr(instance, "_etat_avant_suppression", None) or instantane(instance),
    )


def composants_modifies(sender, instance, action, reverse, pk_set, **kwargs):
    if action not in ("post_add", "post_remove", "post_clear"):
        return
    CodePrescription, _ = _modeles()
    if reverse:
        # instance = un composant ; les fusions touchées sont dans pk_set.
        fusions = CodePrescription.objects.filter(pk__in=pk_set or [])
    else:
        fusions = [instance]
    for fusion in fusions:
        if not _differer(fusion):
            enregistrer(fusion)
