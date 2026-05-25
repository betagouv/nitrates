"""Renomme CategorieCulture -> GroupeCultureUI.

Le modele n'a pas change de structure ; seul son nom Python evolue pour
mieux refleter son role (regroupement UX de cascade form, sans logique
metier d'arbre). Django gere automatiquement le rename de la table SQL
et l'update de la FK Culture.categorie.

Voir discussion conception 2026-05-25 (issue suite a carte #103) :
- CategorieCulture sert UNIQUEMENT a la cascade form front
- BrancheCulturale = la vraie branche d'arbre
- Culture = mapper UI <-> arbre (FK vers les 2)
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("nitrates", "0012_seed_referentiels"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="CategorieCulture",
            new_name="GroupeCultureUI",
        ),
        migrations.AlterModelOptions(
            name="groupecultureui",
            options={
                "ordering": ("ordre_affichage", "libelle_public"),
                "verbose_name": "Groupe de culture (UI cascade)",
                "verbose_name_plural": "Groupes de culture (UI cascade)",
            },
        ),
        migrations.AlterField(
            model_name="groupecultureui",
            name="champs_prefill",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Champs à injecter dans le contexte quand ce groupe est "
                    "choisi SANS sous-culture (cas 'Sol non cultivé')."
                ),
            ),
        ),
    ]
