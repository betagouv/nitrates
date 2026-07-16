"""Commande de seed idempotente : peuple les 7 tables référentiel depuis
la fixture `envergo/nitrates/fixtures/initial_referentiels.json` (cf. #226).

Historique : le seed lisait autrefois `specs/referentiels.yaml`. Depuis #226,
le YAML a été supprimé (le runtime était déjà 100% DB-driven via
`load_referentiels`). La source de seed est maintenant une fixture Django
générée par `dumpdata` depuis l'état DB de référence.

La fixture embarque les PK explicites, donc `loaddata` fait un upsert :
rejouable sans doublon (idempotent), utilisable au déploiement neuf, en
local pour reset, ou en CI.

Usage :
    python manage.py seed_referentiels
    python manage.py seed_referentiels --fixture /chemin/vers/autre.json
    python manage.py seed_referentiels --dry-run    # n'écrit rien

Ordre de la fixture (dépendances FK) : GroupeCultureUI, BrancheCulturale,
Culture → Fertilisant → NoteReglementaire → CodePrescription →
EvenementPhenologique.

Préservation des `blocs` (contenu riche PC édité dans l'admin) : loaddata
écraserait la colonne `blocs` d'un CodePrescription depuis la fixture. Pour
ne pas perdre une édition juriste faite en admin, on snapshote les `blocs`
non vides AVANT le loaddata et on les restaure APRÈS (même invariant que
l'ancien seed YAML). La fixture porte quand même les blocs de référence pour
un déploiement neuf (base vide -> rien à préserver -> les blocs sont posés).
"""

from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

# 7 tables référentiel, dans l'ordre de comptage du rapport.
_MODELS = [
    ("nitrates", "GroupeCultureUI"),
    ("nitrates", "BrancheCulturale"),
    ("nitrates", "Culture"),
    ("nitrates", "Fertilisant"),
    ("nitrates", "NoteReglementaire"),
    ("nitrates", "CodePrescription"),
    ("nitrates", "EvenementPhenologique"),
]

_DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "initial_referentiels.json"
)


class Command(BaseCommand):
    help = "Seed idempotent des référentiels DB depuis la fixture initial_referentiels.json"

    def add_arguments(self, parser):
        parser.add_argument(
            "--fixture",
            type=str,
            default=None,
            help=(
                "Chemin vers la fixture JSON "
                "(defaut: nitrates/fixtures/initial_referentiels.json)."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Charge la fixture puis rollback : rien n'est écrit en base.",
        )

    def _counts(self):
        from django.apps import apps

        return {
            model: apps.get_model(app, model).objects.count() for app, model in _MODELS
        }

    def handle(self, *args, **options):
        fixture_path = Path(options.get("fixture") or _DEFAULT_FIXTURE)
        if not fixture_path.exists():
            self.stderr.write(self.style.ERROR(f"Fixture introuvable : {fixture_path}"))
            return

        dry_run = options.get("dry_run", False)
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — aucune écriture."))

        from envergo.nitrates.models import CodePrescription

        before = self._counts()

        # Snapshot des blocs (contenu riche) non vides existants : loaddata les
        # écraserait, on les restaure après pour ne pas perdre une édition admin.
        def _a_du_contenu(blocs):
            if isinstance(blocs, dict):
                return bool(blocs.get("blocs"))
            return bool(blocs)

        blocs_a_preserver = {
            ident: blocs
            for ident, blocs in CodePrescription.objects.values_list(
                "identifiant", "blocs"
            )
            if _a_du_contenu(blocs)
        }

        # loaddata (clefs naturelles) = upsert idempotent sur `identifiant`. On
        # enveloppe dans une transaction pour pouvoir rollback en dry-run.
        with transaction.atomic():
            call_command("loaddata", str(fixture_path), verbosity=0)
            # Restauration des blocs édités préexistants.
            for ident, blocs in blocs_a_preserver.items():
                CodePrescription.objects.filter(identifiant=ident).update(blocs=blocs)
            after = self._counts()
            if dry_run:
                transaction.set_rollback(True)

        for _app, model in _MODELS:
            delta = after[model] - before[model]
            self.stdout.write(
                f"{model}: {after[model]} en base ({'+' if delta >= 0 else ''}{delta})"
            )
        self.stdout.write(self.style.SUCCESS("Seed terminé."))
