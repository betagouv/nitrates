"""Seed initial de l'ouverture géographique (carte #57).

Crée une ligne DepartementOuverture par département (métropole + Corse +
DROM), dérivée de regions.DEPARTMENT_TO_REGION (source unique). Tous fermés
SAUF le Grand Est (région R44), ouvert — MVP régional Grand Est.

Idempotent : update_or_create sur le code. Rejouable sans doublon.
"""

from django.db import migrations

# Région ouverte au lancement (Grand Est).
REGION_OUVERTE_INITIALE = "44"


def forwards(apps, schema_editor):
    from envergo.nitrates.regions import DEPARTMENT_TO_REGION, region_for_department

    DepartementOuverture = apps.get_model("nitrates", "DepartementOuverture")

    # Ordre d'affichage stable : par (region_code, code département).
    departements = sorted(DEPARTMENT_TO_REGION.items(), key=lambda kv: (kv[1], kv[0]))
    for idx, (dept_code, region_code) in enumerate(departements):
        _, region_label = region_for_department(dept_code)
        DepartementOuverture.objects.update_or_create(
            code=dept_code,
            defaults={
                "region_code": region_code,
                "region_label": region_label or "",
                "est_ouvert": region_code == REGION_OUVERTE_INITIALE,
                "ordre_affichage": idx,
            },
        )


def backwards(apps, schema_editor):
    DepartementOuverture = apps.get_model("nitrates", "DepartementOuverture")
    DepartementOuverture.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("nitrates", "0018_departementouverture"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
