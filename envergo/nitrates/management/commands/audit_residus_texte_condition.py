"""Audit des residus de conversion calculatrice -> autre nature (#218/#219).

Contexte : quand une regle passe de type=calculatrice a une nature a rendu
simple via l'editeur YAML, les champs propres au calendrier dynamique couvert
survivaient comme residus (bug editeur #218). Marqueur fiable du residu :
le composant `calendrier_dynamique_couvert` present sur une regle dont le type
n'est PLUS calculatrice. On signale alors les champs orphelins associes
(inputs_requis, condition/masque de periode, texte_condition herite).

On NE se fie PAS au seul `texte_condition` : c'est une justification metier
LEGITIME hors calculatrice (rendue en tooltip ⓘ pour interdiction/ASC/plafond).
Le distinguer d'un residu demande la signature composant couvert.

PAR HdF est exclu par defaut : prototype non valide (justifications volontaires
non stabilisees, hors perimetre de nettoyage).

Usage :
    python manage.py audit_residus_texte_condition            # arbres actifs valides
    python manage.py audit_residus_texte_condition --all      # + drafts/archives
    python manage.py audit_residus_texte_condition --inclure-hdf
"""

from django.core.management.base import BaseCommand

from envergo.nitrates.models import DecisionTree

COMPOSANT_CALCULATRICE = "calendrier_dynamique_couvert"
# Arbres prototypes exclus du perimetre de nettoyage (non valides).
NOMS_EXCLUS = {"PAR HdF"}


def iter_regles(node):
    if isinstance(node, dict):
        if node.get("id") and node.get("type"):
            yield node
        for v in node.values():
            yield from iter_regles(v)
    elif isinstance(node, list):
        for it in node:
            yield from iter_regles(it)


def residus_calculatrice(contenu):
    """Regles avec composant calendrier couvert mais type != calculatrice."""
    residus = []
    for regle in iter_regles(contenu):
        if (
            regle.get("composant") == COMPOSANT_CALCULATRICE
            and regle.get("type") != "calculatrice"
        ):
            residus.append(regle)
    return residus


class Command(BaseCommand):
    help = "Audit des residus de conversion calculatrice -> autre nature."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all", action="store_true", help="Inclure drafts/archives."
        )
        parser.add_argument(
            "--inclure-hdf",
            action="store_true",
            help="Inclure le prototype PAR HdF (exclu par defaut).",
        )

    def handle(self, *args, **options):
        qs = DecisionTree.objects.all()
        if not options["all"]:
            qs = qs.filter(status=DecisionTree.STATUS_ACTIVE)
        if not options["inclure_hdf"]:
            qs = qs.exclude(name__in=NOMS_EXCLUS)
        qs = qs.order_by("scope", "name")

        total = 0
        for tree in qs:
            residus = residus_calculatrice(tree.contenu)
            entete = f"{tree.scope}/{tree.name} (pk={tree.pk}, {tree.status})"
            if not residus:
                self.stdout.write(f"[OK] {entete} : aucun residu")
                continue
            total += len(residus)
            self.stdout.write(
                self.style.WARNING(f"[{len(residus)} RESIDU(S)] {entete}")
            )
            for r in residus:
                champs = []
                if r.get("inputs_requis"):
                    champs.append("inputs_requis")
                if (r.get("texte_condition") or "").strip():
                    champs.append("texte_condition")
                if any(
                    (p.get("condition") or "").strip() or p.get("masque")
                    for p in (r.get("periodes") or [])
                ):
                    champs.append("condition/masque periode")
                self.stdout.write(
                    f"    - {r.get('id')}  (type={r.get('type')})  "
                    f"champs orphelins : {', '.join(champs) or 'composant seul'}"
                )

        if total == 0:
            self.stdout.write(self.style.SUCCESS("\nAucun residu calculatrice."))
        else:
            self.stdout.write(
                self.style.WARNING(f"\nTotal : {total} residu(s) a nettoyer.")
            )
