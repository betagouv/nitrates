"""Commande de seed idempotente des contenus riches éditables (carte #131).

Importe `envergo/nitrates/specs/contenus_rich.yaml` dans la table
ContenuRichDSFR. Idempotente : rejouable au déploiement / en local / en CI
sans créer de doublon (2e passage = 0 créé).

Non destructive par défaut : un contenu déjà en base n'est JAMAIS réécrit, il
a pu être édité dans l'admin (CGU, glossaire, pages…). Écraser exige
`--ecraser`, et laisse une révision dans l'historique avec son motif.

Usage :
    python manage.py seed_contenus_rich
    python manage.py seed_contenus_rich --yaml /chemin/vers/autre.yaml
    python manage.py seed_contenus_rich --dry-run    # n'écrit rien
    python manage.py seed_contenus_rich --ecraser --motif "nouvelle version CGU"
"""

from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from envergo.nitrates.historique import contexte_revision
from envergo.nitrates.models import ContenuRichDSFR
from envergo.nitrates.models_historique import RevisionContenu


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
        parser.add_argument(
            "--ecraser",
            action="store_true",
            help=(
                "Réécrit aussi les contenus déjà en base depuis le YAML (écrase "
                "les éditions admin). Sans ce drapeau, seuls les absents sont créés."
            ),
        )
        parser.add_argument(
            "--motif",
            default="",
            help="Motif consigné dans l'historique des contenus.",
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

        with contexte_revision(
            origine=RevisionContenu.ORIGINE_COMMANDE,
            source=f"seed_contenus_rich {yaml_path.name}",
            motif=options.get("motif") or "",
            differer=True,
        ), transaction.atomic():
            created, updated = self._seed(data, ecraser=options.get("ecraser", False))
            if dry_run:
                transaction.set_rollback(True)

        verbe = "mis à jour" if options.get("ecraser") else "préservé(s) (déjà en base)"
        self.stdout.write(f"ContenuRichDSFR: {created} créé(s), {updated} {verbe}")
        self.stdout.write(self.style.SUCCESS("Seed terminé."))

    def _seed(self, data: dict, ecraser: bool = False) -> tuple[int, int]:
        created = updated = 0
        for entree in data.get("contenus", []) or []:
            cle = entree["cle"]
            if not ecraser and ContenuRichDSFR.objects.filter(cle=cle).exists():
                updated += 1
                continue
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
                    # Champs glossaire (carte #110). Défauts rétro-compatibles :
                    # les entrées historiques sans ces clés restent `general`.
                    "type_contenu": entree.get("type_contenu", "general"),
                    "titre_public": entree.get("titre_public", ""),
                    "categorie": entree.get("categorie", ""),
                    "termes_declencheurs": entree.get("termes_declencheurs", []) or [],
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
        return created, updated
