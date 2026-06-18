"""Ingère les PNG produits par le spec e2e `capture_couvert.spec.ts` dans
les `BrancheValidation`.

Le spec écrit dans `e2e/nitrates/_captures_couvert/` :
  - `<pk>_calendrier.png` -> champ `screenshot_playwright` (+ playwright_run_at)
  - `<pk>_yaml.png`       -> champ `screenshot_yaml_viewer`

Séparer capture (node/Playwright) et ingestion (Django) évite un POST CSRF
fragile depuis le spec. Idempotent : ré-ingérer remplace les fichiers.

NE TOUCHE PAS aux champs de saisie manuelle Miro (miro_widget_id,
resultat_miro, screenshot_miro, code_pc). N'ingère que les 2 captures
auto.

Usage :
    python manage.py ingest_captures_couvert
    python manage.py ingest_captures_couvert --dir e2e/nitrates/_captures_couvert
    python manage.py ingest_captures_couvert --dry-run
"""

import re
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand
from django.utils import timezone

from envergo.nitrates.models import BrancheValidation

_RE = re.compile(r"^(\d+)_(calendrier|yaml)\.png$")


class Command(BaseCommand):
    help = "Ingère les captures couvert (calendrier + yaml viewer) dans le modèle."

    def add_arguments(self, parser):
        parser.add_argument("--dir", default="e2e/nitrates/_captures_couvert")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        d = Path(opts["dir"])
        if not d.is_dir():
            self.stderr.write(f"Dossier introuvable : {d}")
            return

        # Regroupe par pk : {pk: {"calendrier": path, "yaml": path}}
        par_pk: dict[int, dict] = {}
        for f in sorted(d.iterdir()):
            m = _RE.match(f.name)
            if not m:
                continue
            par_pk.setdefault(int(m.group(1)), {})[m.group(2)] = f

        cal = yaml_ = manquantes = 0
        for pk, fichiers in sorted(par_pk.items()):
            b = BrancheValidation.objects.filter(pk=pk).first()
            if b is None:
                manquantes += 1
                continue
            if opts["dry_run"]:
                self.stdout.write(
                    f"[dry-run] pk={pk} {b.regle_id}: "
                    f"{'cal ' if 'calendrier' in fichiers else ''}"
                    f"{'yaml' if 'yaml' in fichiers else ''}"
                )
                continue
            updated = []
            if "calendrier" in fichiers:
                with fichiers["calendrier"].open("rb") as fh:
                    b.screenshot_playwright.save(
                        f"{b.regle_id or pk}_calendrier.png", File(fh), save=False
                    )
                b.playwright_run_at = timezone.now()
                updated += ["screenshot_playwright", "playwright_run_at"]
                cal += 1
            if "yaml" in fichiers:
                with fichiers["yaml"].open("rb") as fh:
                    b.screenshot_yaml_viewer.save(
                        f"{b.regle_id or pk}_yaml.png", File(fh), save=False
                    )
                updated += ["screenshot_yaml_viewer"]
                yaml_ += 1
            if updated:
                updated.append("updated_at")
                b.save(update_fields=updated)

        if opts["dry_run"]:
            self.stdout.write(f"\n[dry-run] {len(par_pk)} feuilles à ingérer.")
        else:
            msg = f"OK : {cal} calendriers, {yaml_} yaml viewer ingérés."
            if manquantes:
                msg += f" ({manquantes} pk sans BrancheValidation, ignorés.)"
            self.stdout.write(self.style.SUCCESS(msg))
