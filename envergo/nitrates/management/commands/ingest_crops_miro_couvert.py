"""Ingère les crops du board Miro (un PNG par regle_id) dans le champ
`screenshot_miro` des BrancheValidation couvert.

Les crops sont produits hors-app (parsing SVG + crop_svg_viewbox.mjs, cf.
snapshot_miro/arbre_complet/<date>/crops_named/<regle_id>.png) et nommés
par le nom technique de la feuille (regle_id). Carte #140.

Un regle_id peut correspondre à plusieurs BrancheValidation (doublons
cie/cine qui partagent la même règle) : le crop est attaché à TOUTES.

Idempotent : ré-ingérer remplace l'image. N'écrase PAS miro_widget_id,
resultat_miro, ni les autres screenshots.

Usage :
    python manage.py ingest_crops_miro_couvert
    python manage.py ingest_crops_miro_couvert --dir <chemin/crops_named>
    python manage.py ingest_crops_miro_couvert --dry-run
"""

from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand

from envergo.nitrates.models import BrancheValidation


class Command(BaseCommand):
    help = "Ingère les crops Miro (<regle_id>.png) dans screenshot_miro."

    def add_arguments(self, parser):
        default_dir = (
            Path(settings.NITRATES_SPECS_DIR)
            / "snapshot_miro"
            / "arbre_complet"
            / "2026-06-17"
            / "crops_named"
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
                chemin_yaml__contains="q_couvert_sous_culture", regle_id=regle_id
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
                    b.screenshot_miro.save(f"{regle_id}.png", File(fh), save=False)
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
                    f"OK : {attaches} screenshot_miro attachés "
                    f"({feuilles} regle_id, {orphelins} orphelins)."
                )
            )
