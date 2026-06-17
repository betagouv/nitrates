"""Commande de seed idempotente des contenus riches éditables (carte #131).

Importe `envergo/nitrates/specs/contenus_rich.yaml` dans la table
ContenuRichDSFR. Idempotente : `update_or_create` sur la clé, donc rejouable
au déploiement / en local / en CI sans créer de doublon (2e passage = 0 créé).

Usage :
    python manage.py seed_contenus_rich
    python manage.py seed_contenus_rich --yaml /chemin/vers/autre.yaml
    python manage.py seed_contenus_rich --dry-run    # n'écrit rien
"""

from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from envergo.nitrates.models import ContenuRichDSFR


class Command(BaseCommand):
    help = "Seed idempotent des contenus riches DB depuis contenus_rich.yaml"

    def add_arguments(self, parser):
        parser.add_argument(
            "--yaml",
            type=str,
            default=None,
            help="Chemin vers contenus_rich.yaml (defaut: NITRATES_SPECS_DIR).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche ce qui serait fait sans écrire en base.",
        )

    def handle(self, *args, **options):
        yaml_path = options.get("yaml") or (
            Path(settings.NITRATES_SPECS_DIR) / "contenus_rich.yaml"
        )
        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            self.stderr.write(self.style.ERROR(f"YAML introuvable : {yaml_path}"))
            return

        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        dry_run = options.get("dry_run", False)
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — aucune écriture."))

        with transaction.atomic():
            created, updated = self._seed(data)
            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(f"ContenuRichDSFR: {created} créé(s), {updated} mis à jour")
        self.stdout.write(self.style.SUCCESS("Seed terminé."))

    def _seed(self, data: dict) -> tuple[int, int]:
        created = updated = 0
        for entree in data.get("contenus", []) or []:
            cle = entree["cle"]
            # On stocke l'enveloppe {schema, blocs} : la version du schéma
            # permet de migrer le JSON plus tard sans casser l'existant.
            blocs_payload = {
                "schema": entree.get("schema", 1),
                "blocs": entree.get("blocs", []) or [],
            }
            _, was_created = ContenuRichDSFR.objects.update_or_create(
                cle=cle,
                defaults={
                    "libelle_admin": entree.get("libelle_admin", cle),
                    "blocs": blocs_payload,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
        return created, updated
