"""Auto-import du YAML actuel vers la table DecisionTree au 1er migrate.

Best effort : si le fichier n'est pas accessible (CI, collegue sans le
bind-mount, prod sans NITRATES_SPECS_DIR pointant vers un YAML), on
warn sur stderr et on no-op. La commande management
`import_decision_tree` permet de re-importer manuellement apres coup.

Idempotent : ne fait rien si la table contient deja un tree.
"""

import sys
from pathlib import Path

import yaml
from django.conf import settings
from django.db import migrations
from django.utils import timezone


def forwards(apps, schema_editor):
    DecisionTree = apps.get_model("nitrates", "DecisionTree")
    if DecisionTree.objects.exists():
        return  # idempotent

    yaml_path = Path(settings.NITRATES_SPECS_DIR) / "arbre_decision_national.yaml"
    if not yaml_path.exists():
        sys.stderr.write(
            f"[migration nitrates 0004] {yaml_path} introuvable, "
            f"auto-import saute. Importer plus tard via "
            f"`python manage.py import_decision_tree`.\n"
        )
        return

    text = yaml_path.read_text(encoding="utf-8")
    try:
        arbre = yaml.safe_load(text)
    except yaml.YAMLError as e:
        sys.stderr.write(
            f"[migration nitrates 0004] YAML invalide ({e}), "
            f"auto-import saute.\n"
        )
        return

    # Pas de validate_arbre() ici : eviter les imports croises avec le
    # validateur (qui pourrait dependre du modele a son tour). La commande
    # management le fait, ce qui est suffisant pour la rigueur metier.
    DecisionTree.objects.create(
        name="arbre_decision_national",
        status="active",
        contenu=arbre,
        contenu_yaml_brut=text,
        activated_at=timezone.now(),
    )


def reverse(apps, schema_editor):
    DecisionTree = apps.get_model("nitrates", "DecisionTree")
    DecisionTree.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("nitrates", "0003_decisiontree"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse),
    ]
