"""Attache en batch des screenshots aux feuilles couvert par regle_id.

Pont Playwright -> Django : un script Playwright (hors container, profil
isole) capture un PNG par regle_id distinct et les depose dans un dossier
accessible au container (le repo est monte sur /app). Cette commande
parcourt ce dossier et attache chaque `<regle_id>.png` a TOUTES les
feuilles couvert (`BrancheValidation`) qui resolvent vers ce regle_id
(plusieurs chemins ICPE/IAA/zonage peuvent partager la meme regle, donc
le meme rendu simulateur).

Champs cibles : `playwright` (rendu simulateur) ou `yaml_viewer`
(capture admin YAML). Idempotent : re-attache (ecrase) a chaque run.

Usage :
    python manage.py attach_couvert_screenshots playwright /app/.playwright-mcp/couvert
    python manage.py attach_couvert_screenshots yaml_viewer /app/.playwright-mcp/couvert_yaml
    python manage.py attach_couvert_screenshots playwright <dir> --dry-run
"""

from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from envergo.nitrates.models import BrancheValidation

FIELD_TO_ATTR = {
    "playwright": "screenshot_playwright",
    "yaml_viewer": "screenshot_yaml_viewer",
    "yaml_form": "screenshot_yaml_form",
}


class Command(BaseCommand):
    help = "Attache en batch des screenshots couvert par regle_id."

    def add_arguments(self, parser):
        parser.add_argument(
            "field",
            choices=list(FIELD_TO_ATTR.keys()),
            help="Champ cible : playwright | yaml_viewer | yaml_form",
        )
        parser.add_argument(
            "directory",
            type=Path,
            help="Dossier contenant les <regle_id>.png",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        field = opts["field"]
        directory = opts["directory"]
        attr = FIELD_TO_ATTR[field]

        if not directory.exists():
            raise CommandError(f"Dossier introuvable : {directory}")

        pngs = sorted(directory.glob("*.png"))
        if not pngs:
            raise CommandError(f"Aucun PNG dans {directory}")

        # Restreint aux feuilles couvert. On attache par regle_id : un PNG
        # peut couvrir plusieurs feuilles (memes resultats partages).
        couvert = BrancheValidation.objects.filter(
            chemin_yaml__contains="q_couvert_sous_culture"
        )

        attaches = lignes = 0
        sans_feuille = []
        for png in pngs:
            regle_id = png.stem  # nom de fichier = regle_id
            cibles = list(couvert.filter(regle_id=regle_id))
            if not cibles:
                sans_feuille.append(regle_id)
                continue
            attaches += 1
            lignes += len(cibles)
            if opts["dry_run"]:
                self.stdout.write(
                    f"[dry-run] {png.name} -> {len(cibles)} feuille(s) " f"({regle_id})"
                )
                continue
            # Nom de fichier court : le regle_id complet + le dossier
            # upload_to (= regle_id) depasse la limite de chemin du storage.
            # On garde un nom stable mais borne.
            nom_court = f"{field}_{png.stem[:40]}.png"
            for branche in cibles:
                with png.open("rb") as f:
                    getattr(branche, attr).save(nom_court, File(f), save=False)
                fields = [attr, "updated_at"]
                if field == "playwright":
                    branche.playwright_run_at = timezone.now()
                    fields.append("playwright_run_at")
                branche.save(update_fields=fields)

        if sans_feuille:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(sans_feuille)} PNG sans feuille couvert "
                    f"correspondante : {', '.join(sans_feuille[:5])}"
                    + ("..." if len(sans_feuille) > 5 else "")
                )
            )
        verbe = "attacherait" if opts["dry_run"] else "OK"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verbe} : {attaches} PNG -> {lignes} feuilles couvert "
                f"(champ {field})."
            )
        )
