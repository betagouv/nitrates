"""Ingère le mapping Miro (regle_id -> widget_id / résultat / notes PC) dans
les BrancheValidation couvert.

Le mapping est produit hors-app par `match_and_crop.py` (parsing SVG du board
juriste) : pour chaque feuille-résultat il retient le widget Miro retenu et
extrait son id (deeplink `moveToWidget`), son texte (bloc résultat) et les
codes PC voisins. Cf. snapshot_miro/arbre_complet/<date>/mapping_widget_ids.json
et carte #140.

Ce que la commande pose :
  - `miro_widget_id`  : TOUJOURS (c'est une donnée technique, pas une saisie
    humaine ; le deeplink doit refléter le dernier parsing).
  - `resultat_miro`   : seulement si VIDE (préserve la reformulation manuelle
    de Max), sauf `--force`.
  - `code_pc_miro`    : idem (vide-only sauf `--force`).

Un regle_id peut viser plusieurs BrancheValidation (doublons cie/cine qui
partagent la règle) : on applique à TOUTES.

Idempotent.

Usage :
    python manage.py ingest_miro_widget_ids
    python manage.py ingest_miro_widget_ids --force      # écrase resultat/PC
    python manage.py ingest_miro_widget_ids --dry-run
    python manage.py ingest_miro_widget_ids --file <mapping.json>
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from envergo.nitrates.models import BrancheValidation


class Command(BaseCommand):
    help = "Ingère widget_id / résultat / PC Miro depuis mapping_widget_ids.json."

    def add_arguments(self, parser):
        default_file = (
            Path(settings.NITRATES_SPECS_DIR)
            / "snapshot_miro"
            / "arbre_complet"
            / "2026-06-17"
            / "mapping_widget_ids.json"
        )
        parser.add_argument("--file", default=str(default_file))
        parser.add_argument(
            "--force",
            action="store_true",
            help="Écrase aussi resultat_miro / code_pc_miro (sinon vide-only).",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        path = Path(opts["file"])
        if not path.is_file():
            self.stderr.write(f"Mapping introuvable : {path}")
            return
        mapping = json.loads(path.read_text(encoding="utf-8"))
        force = opts["force"]
        dry = opts["dry_run"]

        feuilles = orphelins = maj_widget = maj_resultat = maj_pc = 0
        for regle_id, data in sorted(mapping.items()):
            qs = BrancheValidation.objects.filter(
                chemin_yaml__contains="q_couvert_sous_culture", regle_id=regle_id
            )
            if not qs.exists():
                orphelins += 1
                self.stdout.write(f"  (orphelin, pas en base) {regle_id}")
                continue
            feuilles += 1
            widget_id = (data.get("widget_id") or "")[:40]
            resultat = (data.get("resultat") or "")[:500]
            code_pc = (data.get("code_pc") or "")[:300]

            for b in qs:
                champs = []
                if widget_id and b.miro_widget_id != widget_id:
                    b.miro_widget_id = widget_id
                    champs.append("miro_widget_id")
                    maj_widget += 1
                if resultat and (force or not b.resultat_miro):
                    if b.resultat_miro != resultat:
                        b.resultat_miro = resultat
                        champs.append("resultat_miro")
                        maj_resultat += 1
                if code_pc and (force or not b.code_pc_miro):
                    if b.code_pc_miro != code_pc:
                        b.code_pc_miro = code_pc
                        champs.append("code_pc_miro")
                        maj_pc += 1
                if champs and not dry:
                    champs.append("updated_at")
                    b.save(update_fields=champs)
                if dry and champs:
                    self.stdout.write(
                        f"[dry-run] {regle_id} pk={b.pk} -> {', '.join(champs)}"
                    )

        verbe = "[dry-run] " if dry else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{verbe}OK : {feuilles} regle_id, {orphelins} orphelins | "
                f"widget_id={maj_widget}, resultat={maj_resultat}, pc={maj_pc}"
            )
        )
