"""Cree la Regulation `directive_nitrates` et son Criterion `arbre_decision`.

Migration data : pas de modification de schema, juste insertion de 2 lignes
dans les tables Envergo (moulinette_regulation + moulinette_criterion).

L'`activation_map` du Criterion est la map ZV nitrates : le critere est
active si et seulement si le point intersecte une zone vulnerable. Hors
ZV, l'arbre ne tourne pas (et c'est ce qu'on veut). La logique
"hors ZV -> non applicable" reste documentee dans le YAML (le 1er noeud
catalogue n_zvn) pour la lisibilite des juristes, meme si en pratique
ce chemin n'est jamais emprunte par le critere.
"""

from django.db import migrations

REGULATION_SLUG = "directive_nitrates"
REGULATION_EVALUATOR = (
    "envergo.nitrates.regulations.directive_nitrates.DirectiveNitratesEvaluator"
)
CRITERION_BACKEND_TITLE = "Arbre de decision PAN"
CRITERION_TITLE = "Periodes d'epandage azote"
CRITERION_EVALUATOR = (
    "envergo.nitrates.regulations.arbre_decision.ArbreDecisionEvaluator"
)


def create_regulation_and_criterion(apps, schema_editor):
    Map = apps.get_model("geodata", "Map")
    Regulation = apps.get_model("moulinette", "Regulation")
    Criterion = apps.get_model("moulinette", "Criterion")

    # Activation map = ZV nitrates. La map est partagee avec la commande
    # d'import `import_nitrates_zv` (meme nom, meme map_type). On la cree
    # ici si elle n'existe pas encore : la commande d'import fera ensuite
    # `get_or_create` et ajoutera les zones a la map existante.
    activation_map, _ = Map.objects.get_or_create(
        name="ZV nitrates — national",
        defaults={
            "display_name": "Zones vulnérables nitrates (France métropole)",
            "map_type": "zv_nitrates",
            "description": "Zones vulnérables nitrates métropole. Source Sandre.",
        },
    )

    regulation, _created = Regulation.objects.get_or_create(
        regulation=REGULATION_SLUG,
        defaults={
            "evaluator": REGULATION_EVALUATOR,
            "weight": 1,
            "display_order": 1,
            "has_perimeters": False,
            "show_map": False,
        },
    )

    Criterion.objects.get_or_create(
        regulation=regulation,
        evaluator=CRITERION_EVALUATOR,
        defaults={
            "backend_title": CRITERION_BACKEND_TITLE,
            "title": CRITERION_TITLE,
            "weight": 1,
            "is_optional": False,
            "activation_map": activation_map,
        },
    )


def delete_regulation_and_criterion(apps, schema_editor):
    Regulation = apps.get_model("moulinette", "Regulation")
    # Cascade les Criterion via la FK regulation. La Map ZV n'est pas
    # supprimee : elle vient de la commande d'import phase 1.
    Regulation.objects.filter(regulation=REGULATION_SLUG).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("nitrates", "0001_initial"),
        ("moulinette", "0113_alter_configamenagement_regulations_available_and_more"),
        ("geodata", "0030_alter_map_map_type"),
    ]

    operations = [
        migrations.RunPython(
            create_regulation_and_criterion,
            reverse_code=delete_regulation_and_criterion,
        ),
    ]
