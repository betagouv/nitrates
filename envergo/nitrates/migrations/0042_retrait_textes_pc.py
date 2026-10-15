"""Retrait des champs texte_court et texte_redaction_initiale des PC.

Le contenu riche (`blocs`) est la seule source de rendu ; ces deux champs ne
servaient plus que de repli pour une PC sans contenu riche. Avant de les
retirer, une PC sans contenu riche reçoit son texte court sous forme de
paragraphe, pour qu'aucun texte affiché ne disparaisse (au 15/10/2026 : seule
pc5, présente uniquement dans la fixture et les bases locales). La conversion
est consignée dans l'historique des contenus.
"""

from django.conf import settings
from django.db import migrations, models

MOTIF = (
    "Texte court converti en contenu riche avant le retrait des champs "
    "texte_court / texte_redaction_initiale (migration 0042)."
)


def _vide(blocs):
    if isinstance(blocs, dict):
        return not blocs.get("blocs")
    return not blocs


def convertir_textes_courts(apps, schema_editor):
    CodePrescription = apps.get_model("nitrates", "CodePrescription")
    RevisionContenu = apps.get_model("nitrates", "RevisionContenu")
    for pc in CodePrescription.objects.all():
        if not _vide(pc.blocs) or not (pc.texte_court or "").strip():
            continue
        pc.blocs = {
            "schema": 1,
            "blocs": [
                {"type": "paragraphe", "data": {"texte": pc.texte_court.strip()}}
            ],
        }
        pc.save(update_fields=["blocs"])
        derniere = (
            RevisionContenu.objects.filter(type_objet="pc", identifiant=pc.identifiant)
            .order_by("-created_at", "-pk")
            .first()
        )
        if derniere is not None:
            RevisionContenu.objects.create(
                type_objet="pc",
                identifiant=pc.identifiant,
                action="modification",
                champs_modifies=["blocs"],
                instantane={**derniere.instantane, "blocs": pc.blocs},
                environnement=getattr(settings, "ENV_NAME", ""),
                origine="migration",
                source="0042_retrait_textes_pc",
                motif=MOTIF,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("nitrates", "0041_historique_contenus"),
    ]

    operations = [
        migrations.RunPython(convertir_textes_courts, migrations.RunPython.noop),
        # Valeur par défaut vide avant retrait : rend la migration réversible
        # (les colonnes reviennent vides, leur contenu n'est pas restauré).
        migrations.AlterField(
            model_name="codeprescription",
            name="texte_court",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AlterField(
            model_name="codeprescription",
            name="texte_redaction_initiale",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.RemoveField(
            model_name="codeprescription",
            name="texte_court",
        ),
        migrations.RemoveField(
            model_name="codeprescription",
            name="texte_redaction_initiale",
        ),
        migrations.AlterField(
            model_name="codeprescription",
            name="blocs",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Contenu riche (format {schema, blocs:[...]}). Édité via l'éditeur, jamais à la main.",
            ),
        ),
    ]
