"""Seed des pages du pied de page en contenu riche (#550).

Cree les `page.*` absentes depuis specs/contenus_rich.yaml. Jamais
d'ecrasement : une page deja editee dans l'admin reste telle quelle.
"""

from pathlib import Path

import yaml
from django.db import migrations

YAML_PATH = Path(__file__).resolve().parents[1] / "specs" / "contenus_rich.yaml"


def seed_pages(apps, schema_editor):
    ContenuRichDSFR = apps.get_model("nitrates", "ContenuRichDSFR")
    with YAML_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    for entree in data.get("contenus", []) or []:
        if not entree["cle"].startswith("page."):
            continue
        ContenuRichDSFR.objects.get_or_create(
            cle=entree["cle"],
            defaults={
                "libelle_admin": entree.get("libelle_admin", entree["cle"]),
                "blocs": {
                    "schema": entree.get("schema", 1),
                    "blocs": entree.get("blocs", []) or [],
                },
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("nitrates", "0034_lienreference"),
    ]

    operations = [
        migrations.RunPython(seed_pages, migrations.RunPython.noop),
    ]
