"""Normalise les champs des questions complementaires (carte #620).

La reponse a une question complementaire (QC) est rangee sous son `champ`, et
c'est ce champ qui evite de la reposer plus loin (dans l'arbre et d'un arbre a
l'autre de la cascade ZAR -> PAR -> PAN). Une meme question posee sous deux
champs differents est donc posee deux fois.

Regle appliquee : meme texte affiche (casse, ponctuation, accents ignores) et
memes reponses possibles => meme champ. Le regroupement est transitif, le
champ retenu est le plus utilise (a egalite le plus parlant). Les references
au champ sont reecrites avec lui (expressions de catalogue parametre,
remap_contexte, inputs_requis).

Ecriture par le meme chemin que l'editeur admin : chaque arbre actif touche
est clone en brouillon, le brouillon est modifie (revision d'avant
enregistree), puis valide. Les arbres actifs ne changent qu'avec --activer.

Usage :
    python manage.py normaliser_champs_qc                      # DRY-RUN (plan)
    python manage.py normaliser_champs_qc --apply              # brouillons
    python manage.py normaliser_champs_qc --apply --activer    # + activation
    python manage.py normaliser_champs_qc --canonique fertilisant_iaa
    python manage.py normaliser_champs_qc --exclure pas_digestats
    python manage.py normaliser_champs_qc --fusionner type_iii,culture_irriguee
    python manage.py normaliser_champs_qc --groupe fertirrigation --apply
"""

import copy
import re

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from envergo.nitrates.models import DecisionTree
from envergo.nitrates.yaml_admin import editor
from envergo.nitrates.yaml_tree import load_tree_admin
from envergo.nitrates.yaml_tree.qc_champs import (
    PlanImpossible,
    RenommageImpossible,
    collecter_qc,
    iter_noeuds,
    planifier_normalisation,
    renommer_champs,
)
from envergo.nitrates.yaml_tree.validator import ValidationError, validate_arbre


def _erreurs_validation(tree: DecisionTree) -> list[str]:
    try:
        validate_arbre(load_tree_admin(tree), scope=tree.scope)
    except ValidationError as exc:
        return list(exc.errors)
    return []


def _traduire(message: str, mapping: dict[str, str]) -> str:
    for ancien, nouveau in mapping.items():
        message = re.sub(rf"\b{re.escape(ancien)}\b", nouveau, message)
    return message


def _libelle(tree: DecisionTree) -> str:
    zone = tree.scope + (f"/{tree.region_code}" if tree.region_code else "")
    return f"#{tree.pk} {tree.name} ({zone})"


class Command(BaseCommand):
    help = (
        "Donne le meme champ aux questions complementaires identiques "
        "(meme texte, memes reponses). Dry-run par defaut."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Cree un brouillon normalise par arbre actif touche.",
        )
        parser.add_argument(
            "--activer",
            action="store_true",
            help="Avec --apply : active les brouillons (l'actif courant est archive).",
        )
        parser.add_argument(
            "--canonique",
            action="append",
            default=[],
            metavar="CHAMP",
            help="Force le champ retenu pour le groupe qui le contient (repetable).",
        )
        parser.add_argument(
            "--exclure",
            action="append",
            default=[],
            metavar="CHAMP",
            help="Champ a ne jamais renommer ni absorber (repetable).",
        )
        parser.add_argument(
            "--fusionner",
            action="append",
            default=[],
            metavar="A,B[,C]",
            help=(
                "Fusionne des champs aux textes differents mais qui posent la "
                "meme question (memes reponses exigees, repetable)."
            ),
        )
        parser.add_argument(
            "--groupe",
            action="append",
            default=[],
            metavar="CHAMP",
            help="N'applique que les groupes contenant ce champ (repetable).",
        )
        parser.add_argument(
            "--utilisateur",
            metavar="EMAIL",
            help="Auteur des brouillons et des revisions.",
        )

    def handle(self, *args, **options):
        if options["activer"] and not options["apply"]:
            raise CommandError("--activer s'utilise avec --apply.")

        actifs = list(
            DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE).order_by(
                "-weight", "scope", "region_code", "name"
            )
        )
        occurrences = []
        for tree in actifs:
            occurrences.extend(collecter_qc(tree.contenu, tree.name, tree.pk))

        try:
            plan = planifier_normalisation(
                occurrences,
                canoniques_forces=options["canonique"],
                exclus=options["exclure"],
                fusions=[f.split(",") for f in options["fusionner"]],
            )
        except PlanImpossible as exc:
            raise CommandError(str(exc))

        groupes = plan.groupes
        if options["groupe"]:
            voulus = set(options["groupe"])
            groupes = [g for g in groupes if voulus & set(g.champs)]
        mapping = {}
        for g in groupes:
            mapping.update(g.renommages)

        self._afficher_plan(actifs, occurrences, plan, groupes)

        if not mapping:
            self.stdout.write(self.style.SUCCESS("\nRien a normaliser."))
            return
        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDRY-RUN : {len(mapping)} champ(s) a renommer. Relancer "
                    "avec --apply (brouillons) puis --activer."
                )
            )
            return

        user = None
        if options["utilisateur"]:
            user = get_user_model().objects.filter(email=options["utilisateur"]).first()
            if user is None:
                raise CommandError(f"utilisateur {options['utilisateur']} inconnu.")
        self._appliquer(actifs, mapping, user, options["activer"])

    # ─── Affichage ─────────────────────────────────────────────────────────

    def _afficher_plan(self, actifs, occurrences, plan, groupes):
        w = self.stdout.write
        w(f"{len(actifs)} arbre(s) actif(s), {len(occurrences)} QC.")
        if not groupes:
            w("\nAucune question posee sous plusieurs champs.")
        for g in groupes:
            w(self.style.MIGRATE_HEADING(f"\n== {g.canonique} (champ retenu)"))
            for champ in g.champs:
                marque = "=" if champ == g.canonique else "->"
                w(f"  {marque} {champ} : {g.compte_par_champ[champ]} noeud(s)")
            for texte in g.textes:
                w(f"     « {texte} »")
            par_arbre = {}
            for o in g.occurrences:
                if o.champ != g.canonique:
                    par_arbre.setdefault(o.arbre, []).append(
                        f"{o.noeud_id} ({o.champ})"
                    )
            for arbre, noeuds in par_arbre.items():
                w(f"     {arbre} : {', '.join(noeuds)}")

        if plan.valeurs_divergentes:
            w(self.style.WARNING("\nMeme champ, reponses differentes (NON corrige) :"))
            for champ, jeux in plan.valeurs_divergentes.items():
                w(f"  {champ}")
                for valeurs, occs in jeux:
                    arbres = sorted({o.arbre for o in occs})
                    w(
                        f"     [{', '.join(sorted(valeurs))}] {len(occs)} noeud(s) "
                        f"dans {', '.join(arbres)}"
                    )
        if plan.ecartes_polarite:
            w(self.style.WARNING("\nEcartes (libelle contraire de la valeur) :"))
            for champ, occs in plan.ecartes_polarite.items():
                w(f"  {champ} : {', '.join(o.noeud_id for o in occs)}")
        if plan.proches:
            w("\nTextes proches, memes reponses (a trancher, --fusionner) :")
            for a, b, score in plan.proches:
                w(f"  {a} ~ {b} ({score})")

        anciens = {c for g in groupes for c in g.renommages}
        brouillons = []
        for d in DecisionTree.objects.filter(status=DecisionTree.STATUS_DRAFT):
            utilises = {n.get("champ") for n in iter_noeuds(d.contenu)} & anciens
            if utilises:
                brouillons.append((d, sorted(utilises)))
        if brouillons:
            w(
                self.style.WARNING(
                    "\nBrouillons qui utilisent un ancien champ (a reprendre, "
                    "ils le reintroduiraient a l'activation) :"
                )
            )
            for d, champs in brouillons:
                w(f"  {_libelle(d)} : {', '.join(champs)}")

    # ─── Application ───────────────────────────────────────────────────────

    def _appliquer(self, actifs, mapping, user, activer):
        w = self.stdout.write
        with transaction.atomic():
            brouillons = []
            for actif in actifs:
                try:
                    modifs = renommer_champs(copy.deepcopy(actif.contenu), mapping)
                except RenommageImpossible as exc:
                    raise CommandError(f"{_libelle(actif)} : {exc}")
                if not modifs:
                    continue
                draft = DecisionTree.clone_to_draft(actif, user=user)
                res = editor.renommer_champs_qc(
                    draft,
                    mapping,
                    user,
                    description="Normalisation des champs de QC (#620)",
                )
                if not res.ok:
                    raise CommandError(
                        f"{_libelle(actif)} : "
                        + " ; ".join(e.message for e in res.errors)
                    )
                draft.refresh_from_db()
                avant = {_traduire(e, mapping) for e in _erreurs_validation(actif)}
                nouvelles = [e for e in _erreurs_validation(draft) if e not in avant]
                if nouvelles:
                    raise CommandError(
                        f"{_libelle(actif)} : la normalisation introduit "
                        f"{len(nouvelles)} erreur(s) de validation, rien n'est "
                        f"ecrit. {nouvelles[:3]}"
                    )
                brouillons.append((actif, draft, res.summary))
                w(f"  brouillon {_libelle(draft)} <- {actif.name} : {res.summary}")
            if activer:
                for actif, draft, _ in brouillons:
                    draft.activate()
                    w(self.style.SUCCESS(f"  active : {_libelle(draft)}"))
        if activer:
            w(
                self.style.SUCCESS(
                    f"\n{len(brouillons)} arbre(s) normalise(s) et active(s)."
                )
            )
        else:
            w(
                self.style.SUCCESS(
                    f"\n{len(brouillons)} brouillon(s) cree(s). A relire dans "
                    "l'editeur puis publier, ou relancer avec --activer."
                )
            )
