"""Seed des pages du pied de page en contenu riche (#550)."""

from django.db import migrations

from envergo.nitrates.contenu_rich.pages import seed_pages


class Migration(migrations.Migration):

    dependencies = [
        ("nitrates", "0034_lienreference"),
    ]

    operations = [
        migrations.RunPython(seed_pages, migrations.RunPython.noop),
    ]
