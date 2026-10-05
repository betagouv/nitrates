"""Recable les permissions du groupe `external_observator`.

La migration 0010 attachait les permissions au groupe en les cherchant en
base. Sur une base neuve (prod, montee le 17/08), les permissions n'existent
pas encore a ce moment-la : Django ne les cree qu'au post_migrate. Le groupe
a donc ete cree vide en prod, et un observateur se connectait a un admin vide.

Ici on cree d'abord les permissions manquantes de l'app nitrates, puis on
rattache au groupe :
  - les permissions d'origine (0010) : brouillons d'arbre a soi, validation
    de branches ;
  - la consultation (view_*) de tous les modeles nitrates, pour que
    l'observateur voie les PC, contenus, referentiels, couleurs, etc.

Aucune permission change/delete n'est ajoutee hors DecisionTree (dont
l'ownership et le verrou de l'actif sont controles dans l'admin).
Idempotent : rejouable sans effet de bord.
"""

from django.contrib.auth.management import create_permissions
from django.db import migrations

GROUP_NAME = "external_observator"

PERMISSIONS_0010 = [
    "view_decisiontree",
    "add_decisiontree",
    "change_decisiontree",
    "delete_decisiontree",
    "view_decisiontreerevision",
    "add_decisiontreerevision",
    "view_branchevalidation",
    "view_branchevalidationaction",
    "add_branchevalidationaction",
    "view_rpgculture",
]


def recabler(apps, schema_editor):
    # create_permissions ignore une app sans `models_module`, ce qui est le
    # cas dans le registre historique des migrations : on le force le temps
    # de l'appel.
    app_config = apps.get_app_config("nitrates")
    models_module = getattr(app_config, "models_module", None)
    app_config.models_module = models_module or True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = models_module

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    group, _ = Group.objects.get_or_create(name=GROUP_NAME)
    nitrates = Permission.objects.filter(content_type__app_label="nitrates")
    voulues = nitrates.filter(codename__in=PERMISSIONS_0010) | nitrates.filter(
        codename__startswith="view_"
    )
    group.permissions.add(*voulues)


class Migration(migrations.Migration):

    dependencies = [
        ("nitrates", "0038_seed_couleurs_zones"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(recabler, migrations.RunPython.noop),
    ]
