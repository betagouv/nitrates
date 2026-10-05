"""Palette initiale des bassins ZV (retour métier du 01/10/2026).

Artois-Picardie Escaut (FRA) et Sambre (FRB2) partagent la même couleur :
c'est un seul bassin pour les utilisateurs. Les couleurs sont vives car la
couche est affichée à 30 % d'opacité sur le simulateur.

Idempotent : ne crée que les clés absentes, pour ne pas écraser une couleur
retouchée dans l'admin.
"""

from django.db import migrations

ZV = "zv_nitrates"

PALETTE = [
    ("FRA", "Artois-Picardie (Escaut)", "#00b0ff"),
    ("FRB2", "Artois-Picardie (Sambre)", "#00b0ff"),
    ("FRB1-FRC", "Rhin-Meuse", "#7c4dff"),
    # Codes 2021, avant la livraison d'un seul bloc Rhin-Meuse.
    ("FRB1", "Meuse", "#7c4dff"),
    ("FRC", "Rhin", "#7c4dff"),
    ("FRH", "Seine-Normandie", "#ffd600"),
    ("FRD", "Rhône-Méditerranée", "#00c853"),
    ("FRG", "Loire-Bretagne", "#f50057"),
    ("FRF", "Adour-Garonne", "#ff6d00"),
    ("*", "Bassin non répertorié", "#a06fc7"),
]


def seed(apps, schema_editor):
    CouleurZone = apps.get_model("nitrates", "CouleurZone")
    for cle, libelle, couleur in PALETTE:
        CouleurZone.objects.get_or_create(
            map_type=ZV, cle=cle, defaults={"libelle": libelle, "couleur": couleur}
        )


class Migration(migrations.Migration):

    dependencies = [
        ("nitrates", "0037_couleur_zone"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
