"""Rapport de résolution géo des PC, feuille par feuille (#147).

Pour chaque règle des arbres ACTIFS qui porte au moins un code de
prescription, affiche ce que le résolveur produirait sur chaque
territoire pertinent (déduits des déclinaisons présentes en base :
ex Grand Est, ZAR Grand Est, Hauts-de-France) quand le résultat diffère
des codes bruts de la feuille.

Outil de repasse avec les juristes : vérifier que chaque combinaison
retombe sur la rédaction attendue, et repérer les feuilles/surcharges
devenues inutiles.

Usage :
    python manage.py rapport_resolution_pc            # tout
    python manage.py rapport_resolution_pc --tous     # inclut les identités
"""

from django.core.management.base import BaseCommand

from envergo.nitrates.models import DecisionTree
from envergo.nitrates.regions import REGIONS
from envergo.nitrates.yaml_tree import load_referentiels, resoudre_codes_prescription
from envergo.nitrates.yaml_tree.parcours import normaliser_codes_prescription
from envergo.nitrates.yaml_tree.validator import _walk_objects


class Command(BaseCommand):
    help = "Rapport de résolution géo des codes de prescription (feuille par feuille)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--tous",
            action="store_true",
            help="Afficher aussi les règles dont la résolution est l'identité partout.",
        )

    def handle(self, *args, **options):
        ref = load_referentiels()["codes_prescription"]

        # Territoires à tester, déduits des zones d'application déclarées.
        # (scope, region_code) -> (label, region_code, en_zar). Une parcelle
        # en ZAR est aussi dans sa région : en_zar implique la région.
        territoires = [("hors zone spécifique", None, False)]
        zones = sorted(
            {
                (d.get("scope"), d.get("region_code"))
                for d in ref.values()
                if isinstance(d, dict) and d.get("scope")
            }
        )
        for scope, region_code in zones:
            nom = REGIONS.get(region_code, region_code)
            label = f"ZAR {nom}" if scope == "zar" else nom
            territoires.append((label, region_code, scope == "zar"))

        total, transformees = 0, 0
        for tree in DecisionTree.objects.filter(
            status=DecisionTree.STATUS_ACTIVE
        ).order_by("-weight"):
            entete_arbre = False
            for obj in _walk_objects(tree.contenu):
                if not isinstance(obj, dict):
                    continue
                codes = normaliser_codes_prescription(obj.get("code_prescription"))
                if not codes:
                    continue
                total += 1
                lignes = []
                differe = False
                for label, region_code, en_zar in territoires:
                    resolus = resoudre_codes_prescription(
                        codes, ref, region_code=region_code, en_zar=en_zar
                    )
                    if resolus != codes:
                        differe = True
                    lignes.append((label, resolus))
                if differe:
                    transformees += 1
                if not differe and not options["tous"]:
                    continue
                if not entete_arbre:
                    self.stdout.write(
                        self.style.MIGRATE_HEADING(
                            f"\n=== {tree.scope} — {tree.name} ==="
                        )
                    )
                    entete_arbre = True
                self.stdout.write(f"  {obj.get('id')} : {', '.join(codes)}")
                for label, resolus in lignes:
                    marque = " " if resolus == codes else "*"
                    self.stdout.write(
                        f"    {marque} {label:<28} -> {', '.join(resolus)}"
                    )

        self.stdout.write(
            f"\n{total} règle(s) avec PC, "
            f"{transformees} avec au moins une transformation géo."
        )
