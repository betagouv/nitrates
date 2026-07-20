"""Nettoie les residus de conversion calculatrice -> autre nature (#219).

Curatif de #218 : purge, dans les arbres actifs, les champs orphelins laisses
par une regle passee de type=calculatrice a une nature simple (le composant
calendrier couvert survit avec ses inputs_requis / condition-masque de periode /
texte_condition herite).

Marqueur du residu (cf. audit_residus_texte_condition) : composant
`calendrier_dynamique_couvert` sur type != calculatrice. On purge alors :
composant couvert, inputs_requis, condition/masque des periodes, et le
texte_condition (herite du calendrier, pas une justification voulue).

NE touche PAS : les composants legitimes (luzerne_post_coupe/mixte), ni les
texte_condition volontaires hors residu, ni PAR HdF (prototype exclu).

Ecrit contenu (parse pyyaml) ET contenu_yaml_brut (ruamel) pour rester
coherent avec ce que l'editeur re-exporte.

Usage :
    python manage.py nettoyer_residus_calculatrice            # DRY-RUN
    python manage.py nettoyer_residus_calculatrice --apply    # applique
    python manage.py nettoyer_residus_calculatrice --apply --inclure-hdf
"""

import io

from django.core.management.base import BaseCommand
from ruamel.yaml import YAML

from envergo.nitrates.models import DecisionTree

COMPOSANT_CALCULATRICE = "calendrier_dynamique_couvert"
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


def _est_residu(regle):
    return (
        regle.get("composant") == COMPOSANT_CALCULATRICE
        and regle.get("type") != "calculatrice"
    )


def _purger(regle):
    """Retire les champs orphelins in place. Retourne la liste des champs vides."""
    vides = []
    if regle.get("composant") == COMPOSANT_CALCULATRICE:
        regle.pop("composant", None)
        vides.append("composant")
    if regle.get("inputs_requis"):
        regle.pop("inputs_requis", None)
        vides.append("inputs_requis")
    if (regle.get("texte_condition") or "").strip():
        regle.pop("texte_condition", None)
        vides.append("texte_condition")
    for p in regle.get("periodes") or []:
        if "condition" in p:
            p.pop("condition", None)
            vides.append("condition(periode)")
        if "masque" in p:
            p.pop("masque", None)
            vides.append("masque(periode)")
    return vides


class Command(BaseCommand):
    help = "Purge les residus de conversion calculatrice -> autre nature."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true", help="Applique (defaut dry-run)."
        )
        parser.add_argument(
            "--inclure-hdf", action="store_true", help="Inclure PAR HdF."
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        qs = DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE)
        if not options["inclure_hdf"]:
            qs = qs.exclude(name__in=NOMS_EXCLUS)
        qs = qs.order_by("scope", "name")

        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.width = 4096

        total_regles = 0
        for tree in qs:
            regles = [r for r in iter_regles(tree.contenu) if _est_residu(r)]
            if not regles:
                self.stdout.write(f"[OK] {tree.scope}/{tree.name} : rien a nettoyer")
                continue

            # 1. contenu (parse pyyaml)
            for r in regles:
                vides = _purger(r)
                total_regles += 1
                self.stdout.write(
                    f"  {tree.scope}/{tree.name} :: {r.get('id')} -> purge {vides}"
                )

            # 2. contenu_yaml_brut (ruamel round-trip) : re-parser, re-purger, re-dumper.
            raw = tree.contenu_yaml_brut or ""
            if raw.strip():
                doc = yaml.load(raw)
                for r in [rr for rr in iter_regles(doc) if _est_residu(rr)]:
                    _purger(r)
                buf = io.StringIO()
                yaml.dump(doc, buf)
                new_raw = buf.getvalue()
            else:
                new_raw = raw

            if apply:
                tree.contenu_yaml_brut = new_raw
                tree.save(update_fields=["contenu", "contenu_yaml_brut"])
                self.stdout.write(self.style.SUCCESS(f"  >>> {tree.name} sauvegarde"))

        if total_regles == 0:
            self.stdout.write(self.style.SUCCESS("\nAucun residu."))
        elif apply:
            self.stdout.write(
                self.style.SUCCESS(f"\n{total_regles} regle(s) nettoyee(s).")
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDRY-RUN : {total_regles} regle(s) a nettoyer. "
                    "Relancer avec --apply."
                )
            )
