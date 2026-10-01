"""Seed de la page donnees personnelles (#550), ajoutee apres 0035.

Meme seed idempotent : ne cree que les page.* absentes.
"""

from django.db import migrations

from envergo.nitrates.contenu_rich.pages import seed_pages


class Migration(migrations.Migration):

    dependencies = [
        ("nitrates", "0035_seed_pages_footer"),
    ]

    operations = [
        migrations.RunPython(seed_pages, migrations.RunPython.noop),
    ]
