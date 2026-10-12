"""Seed de la page statistiques (#517), ajoutee apres 0035/0036.

Meme seed idempotent : ne cree que les page.* absentes.
"""

from django.db import migrations

from envergo.nitrates.contenu_rich.pages import seed_pages


class Migration(migrations.Migration):

    dependencies = [
        ("nitrates", "0039_external_observator_permissions"),
    ]

    operations = [
        migrations.RunPython(seed_pages, migrations.RunPython.noop),
    ]
