"""Seed des pages du pied de page (#550), partage par les migrations.

Cree les `page.*` absentes depuis specs/contenus_rich.yaml. Jamais
d'ecrasement : une page deja editee dans l'admin reste telle quelle.
"""

from pathlib import Path

import yaml

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
