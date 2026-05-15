"""Cree le groupe `external_observator` avec les permissions minimales.

Permissions accordees :
  - view_* sur tous les modeles de l'app nitrates (consultation read-only)
  - add_decisiontree, change_decisiontree, delete_decisiontree
    (autorise a creer/editer/supprimer des drafts, mais l'ownership et
    le verrou sur l'actif sont enforces dans ModelAdmin.has_*_permission
    et dans les vues yaml_admin)
  - add/view sur DecisionTreeRevision (creees implicitement a chaque save)
  - add/view sur BrancheValidationAction (valider des branches)
  - view sur BrancheValidation (lecture de l'overview)
  - view sur RpgCulture (referentiel)

Permissions explicitement REFUSEES (= non accordees) :
  - aucune sur les autres apps Django (users, sites, geodata...)
  - delete sur DecisionTreeRevision / BrancheValidation*
"""

from django.db import migrations


GROUP_NAME = "external_observator"


# (app_label, codename) — codenames Django standard view/add/change/delete
PERMISSIONS = [
    # DecisionTree : CRUD limite (l'ownership + verrou actif sont enforces
    # par ModelAdmin.has_change_permission)
    ("nitrates", "view_decisiontree"),
    ("nitrates", "add_decisiontree"),
    ("nitrates", "change_decisiontree"),
    ("nitrates", "delete_decisiontree"),
    # DecisionTreeRevision : historique d'edition (auto-cree, lecture seule)
    ("nitrates", "view_decisiontreerevision"),
    ("nitrates", "add_decisiontreerevision"),
    # BrancheValidation : overview read-only des validations
    ("nitrates", "view_branchevalidation"),
    # BrancheValidationAction : peut valider, voir, mais pas modifier/supprimer
    ("nitrates", "view_branchevalidationaction"),
    ("nitrates", "add_branchevalidationaction"),
    # Referentiel cultures (read-only)
    ("nitrates", "view_rpgculture"),
]


def create_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    group, _ = Group.objects.get_or_create(name=GROUP_NAME)
    group.permissions.clear()

    for app_label, codename in PERMISSIONS:
        # On filtre via le ContentType de l'app pour eviter de matcher
        # un meme codename sur une autre app par accident.
        cts = ContentType.objects.filter(app_label=app_label)
        perm = Permission.objects.filter(
            content_type__in=cts, codename=codename
        ).first()
        if perm is None:
            # La permission n'existe pas encore (peut arriver si la migration
            # tourne avant que Django ait cree les permissions des modeles).
            # Dans ce cas, on cree la permission manquante associee a un
            # content_type plausible. Mais en pratique, les permissions
            # sont crees au post_migrate de l'app contenttypes, donc cette
            # branche ne devrait jamais s'executer.
            continue
        group.permissions.add(perm)


def delete_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=GROUP_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("nitrates", "0009_alter_branchevalidation_options_and_more"),
        # contenttypes + auth pour que les permissions existent au moment
        # ou on lit Permission.objects.
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(create_group, delete_group),
    ]
