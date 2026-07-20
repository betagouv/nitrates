"""Valide les fichiers canoniques d'arbres (specs/arbres_actifs/) — garde-fou CI.

Un arbre malformé (YAML cassé, structure invalide, référence SIG/branche
inconnue) ne doit JAMAIS être mergé sur main (GitOps #50). Ce check parse et
valide chaque fichier canonique, en fournissant `referentiels + scope` à
`validate_arbre` (sinon faux négatifs `[exhaustivite]` sur les branches SIG des
arbres PAR/ZAR, cf. spike).

Le scope est DÉDUIT du nom de fichier (identité = (scope, région)) :
    national.yaml       -> scope national
    region_<code>.yaml  -> scope region,  region_code=<code>
    zar_<code>.yaml     -> scope zar,     region_code=<code>

Autonome (pas de DB active requise) : tourne en CI sur la base éphémère.

Usage :
    python manage.py validate_arbres_actifs
    python manage.py validate_arbres_actifs --dir /chemin/specs
"""

from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from envergo.nitrates.management.commands.dump_active_trees import ARBRES_ACTIFS_SUBDIR
from envergo.nitrates.models import DecisionTree
from envergo.nitrates.yaml_tree.loader import load_referentiels
from envergo.nitrates.yaml_tree.validator import ValidationError, validate_arbre


def scope_from_filename(name: str):
    """Déduit (scope, region_code) du nom de fichier canonique. None si hors norme."""
    stem = Path(name).stem
    if stem == "national":
        return DecisionTree.SCOPE_NATIONAL, ""
    if stem.startswith("region_"):
        return DecisionTree.SCOPE_REGION, stem.removeprefix("region_")
    if stem.startswith("zar_"):
        return DecisionTree.SCOPE_ZAR, stem.removeprefix("zar_")
    return None


class Command(BaseCommand):
    help = "Valide les arbres canoniques specs/arbres_actifs/ (garde-fou CI #50)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir",
            default=None,
            help="Répertoire specs (défaut: NITRATES_SPECS_DIR).",
        )

    def handle(self, *args, **options):
        specs_dir = Path(options["dir"] or settings.NITRATES_SPECS_DIR)
        arbres_dir = specs_dir / ARBRES_ACTIFS_SUBDIR

        if not arbres_dir.is_dir():
            self.stdout.write(
                self.style.WARNING(f"Aucun répertoire {arbres_dir} — rien à valider.")
            )
            return

        try:
            referentiels = load_referentiels()
        except FileNotFoundError:
            referentiels = None

        fichiers = sorted(arbres_dir.glob("*.yaml"))
        if not fichiers:
            self.stdout.write(
                self.style.WARNING(f"Aucun fichier .yaml dans {arbres_dir}.")
            )
            return

        erreurs = []
        for f in fichiers:
            coords = scope_from_filename(f.name)
            if coords is None:
                erreurs.append(
                    f"{f.name} : nom hors convention "
                    "(attendu national.yaml / region_<code>.yaml / zar_<code>.yaml)"
                )
                continue
            scope, _region = coords

            try:
                arbre = yaml.safe_load(f.read_text(encoding="utf-8"))
            except yaml.YAMLError as e:
                erreurs.append(f"{f.name} : YAML invalide : {e}")
                continue

            try:
                validate_arbre(arbre, referentiels, scope=scope)
                self.stdout.write(f"  {f.name:22s} OK ({scope})")
            except ValidationError as e:
                detail = "; ".join(e.errors)[:400]
                erreurs.append(f"{f.name} : {detail}")

        if erreurs:
            raise CommandError(
                "Arbre(s) canonique(s) invalide(s) :\n  - " + "\n  - ".join(erreurs)
            )

        self.stdout.write(
            self.style.SUCCESS(f"OK : {len(fichiers)} arbre(s) canonique(s) valide(s).")
        )
