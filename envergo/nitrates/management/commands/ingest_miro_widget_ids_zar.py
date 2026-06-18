"""Ingère le mapping Miro ZAR (regle_id -> widget_id / résultat / PC) dans les
BrancheValidation de scope `zar_grand_est`.

Pendant de `ingest_miro_widget_ids` (PAN couvert), mais cible les feuilles
ZAR : on filtre par `scope=zar_grand_est` au lieu du marqueur de chemin
`q_couvert_sous_culture` propre au PAN. Le mapping est produit par
`match_and_crop_zar.py` (snapshot_miro/par_zar_grand_est/<date>/).

Un regle_id peut viser plusieurs BrancheValidation ZAR (variantes
ICPE/IAA/digestats qui partagent la même règle-résultat) : on applique à
TOUTES les lignes ZAR portant ce regle_id.

Pose :
  - `miro_widget_id` : toujours (donnée technique, deeplink moveToWidget).
  - `resultat_miro`  : seulement si vide (préserve la saisie), sauf --force.
  - `code_pc_miro`   : idem.

Idempotent.

Usage :
    python manage.py ingest_miro_widget_ids_zar
    python manage.py ingest_miro_widget_ids_zar --force
    python manage.py ingest_miro_widget_ids_zar --dry-run
    python manage.py ingest_miro_widget_ids_zar --file <mapping.json>
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from envergo.nitrates.models import BrancheValidation


class Command(BaseCommand):
    help = "Ingère widget_id / résultat / PC Miro ZAR (scope=zar_grand_est)."

    def add_arguments(self, parser):
        default_file = (
            Path(settings.NITRATES_SPECS_DIR)
            / "snapshot_miro"
            / "par_zar_grand_est"
            / "2026-06-18"
            / "mapping_widget_ids_zar.json"
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
                scope=BrancheValidation.SCOPE_ZAR_GRAND_EST, regle_id=regle_id
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
                f"{verbe}OK ZAR : {feuilles} regle_id, {orphelins} orphelins | "
                f"widget_id={maj_widget}, resultat={maj_resultat}, pc={maj_pc}"
            )
        )
