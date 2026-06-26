"""Ingère les crops Miro ZAR (<regle_id>.png) dans `screenshot_miro` des
BrancheValidation de scope `zar_grand_est`.

Pendant de `ingest_crops_miro_couvert`, mais cible les feuilles ZAR (filtre
`scope=zar_grand_est`). Crops produits par `match_and_crop_zar.py`
(snapshot_miro/par_zar_grand_est/<date>/crops_named_zar/<regle_id>.png).

Un regle_id peut viser plusieurs BrancheValidation ZAR (variantes
ICPE/IAA/digestats partageant la même règle) : le crop va sur TOUTES.

Idempotent. N'écrase pas miro_widget_id ni les autres screenshots.

Usage :
    python manage.py ingest_crops_miro_zar
    python manage.py ingest_crops_miro_zar --dir <chemin/crops_named_zar>
    python manage.py ingest_crops_miro_zar --dry-run
"""

from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand

from envergo.nitrates.models import BrancheValidation


class Command(BaseCommand):
    help = "Ingère les crops Miro ZAR (<regle_id>.png) dans screenshot_miro."

    def add_arguments(self, parser):
        default_dir = (
            Path(settings.NITRATES_SPECS_DIR)
            / "snapshot_miro"
            / "par_zar_grand_est"
            / "2026-06-18"
            / "crops_named_zar"
        )
        parser.add_argument("--dir", default=str(default_dir))
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        d = Path(opts["dir"])
        if not d.is_dir():
            self.stderr.write(f"Dossier introuvable : {d}")
            return

        crops = {f.stem: f for f in d.glob("*.png")}
        if not crops:
            self.stderr.write(f"Aucun PNG dans {d}")
            return

        attaches = feuilles = orphelins = 0
        for regle_id, png in sorted(crops.items()):
            qs = BrancheValidation.objects.filter(
                scope=BrancheValidation.SCOPE_ZAR_GRAND_EST, regle_id=regle_id
            )
            if not qs.exists():
                orphelins += 1
                self.stdout.write(f"  (orphelin, pas en base) {regle_id}")
                continue
            feuilles += 1
            for b in qs:
                if opts["dry_run"]:
                    self.stdout.write(f"[dry-run] {regle_id} -> pk={b.pk}")
                    continue
                with png.open("rb") as fh:
                    b.screenshot_miro.save(f"zar_{regle_id}.png", File(fh), save=False)
                b.save(update_fields=["screenshot_miro", "updated_at"])
                attaches += 1

        if opts["dry_run"]:
            self.stdout.write(
                f"\n[dry-run] {len(crops)} crops, {feuilles} regle_id en base, "
                f"{orphelins} orphelins."
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"OK ZAR : {attaches} screenshot_miro attachés "
                    f"({feuilles} regle_id, {orphelins} orphelins)."
                )
            )
