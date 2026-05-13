"""Attache un screenshot a une BrancheValidation depuis un fichier local.

Usage devops local : Max ou un agent prend des captures Playwright,
les pousse dans un dossier accessible au container Django, et utilise
cette commande pour les rattacher.

Usage :
    python manage.py attach_validation_screenshot <branche_id> <field> <path>

Exemples :
    python manage.py attach_validation_screenshot 7 playwright /screens/r_colza_type_III.png
    python manage.py attach_validation_screenshot 7 yaml_viewer /screens/yaml_view_r_colza.png
    python manage.py attach_validation_screenshot 7 yaml_form /screens/yaml_form_r_colza.png
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
    "miro": "screenshot_miro",
}


class Command(BaseCommand):
    help = "Attache un screenshot a une BrancheValidation."

    def add_arguments(self, parser):
        parser.add_argument("branche_id", type=int)
        parser.add_argument(
            "field",
            choices=list(FIELD_TO_ATTR.keys()),
            help="Champ cible : playwright | yaml_viewer | yaml_form | miro",
        )
        parser.add_argument("path", type=Path, help="Chemin local du fichier PNG")

    def handle(self, *args, **opts):
        branche_id = opts["branche_id"]
        field = opts["field"]
        path = opts["path"]

        if not path.exists():
            raise CommandError(f"Fichier introuvable : {path}")

        try:
            branche = BrancheValidation.objects.get(pk=branche_id)
        except BrancheValidation.DoesNotExist:
            raise CommandError(f"BrancheValidation pk={branche_id} introuvable")

        attr = FIELD_TO_ATTR[field]
        with path.open("rb") as f:
            getattr(branche, attr).save(path.name, File(f), save=False)

        update_fields = [attr, "updated_at"]
        if field == "playwright":
            branche.playwright_run_at = timezone.now()
            update_fields.append("playwright_run_at")
        branche.save(update_fields=update_fields)

        self.stdout.write(
            f"OK : branche #{branche_id} ({branche.regle_id}) field {field} "
            f"<- {path.name}"
        )
