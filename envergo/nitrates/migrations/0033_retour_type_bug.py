# Generated for #285 — ajout du type "bug" (bouton flottant feedback/bug).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("nitrates", "0032_contenurichdsfr_glossaire"),
    ]

    operations = [
        migrations.AlterField(
            model_name="retourutilisateur",
            name="type",
            field=models.CharField(
                choices=[
                    ("feedback", "Feedback fin de simulation"),
                    ("interet_region", "Intérêt région non ouverte"),
                    ("bug", "Signalement bug / retour (bouton flottant)"),
                ],
                db_index=True,
                help_text="Nature du retour : feedback simulation (#284), intérêt "
                "région (#287) ou signalement bug (#285).",
                max_length=20,
            ),
        ),
    ]
