"""Aligne le domaine du Site nitrates (id=3) sur settings.ENVERGO_NITRATES_DOMAIN.

La migration 0003_add_nitrates cree le Site avec un domaine en dur
("nitrates.local") qui ne matche pas l'URL en deploiement reel
(staging Scalingo, prod future, etc.). Django (notamment l'admin)
appelle Site.objects.get_current(request) qui leve DoesNotExist si
le Host: HTTP entrant ne matche aucun Site.domain, d'ou des 500.

Cette migration aligne dynamiquement Site.domain sur la valeur de
settings.ENVERGO_NITRATES_DOMAIN au moment du migrate. Idempotente.
"""

from django.conf import settings
from django.db import migrations


def set_domain(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    domain = settings.ENVERGO_NITRATES_DOMAIN
    Site.objects.filter(id=3).update(domain=domain, name="Simulateur nitrates")


def noop(apps, schema_editor):
    # Reverse: rien a faire, on laisse le domaine tel quel cote DB
    # plutot que de hardcoder une valeur de retour qui pourrait ne
    # pas correspondre a l'etat anterieur.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("sites", "0003_add_nitrates"),
    ]

    operations = [
        migrations.RunPython(set_domain, noop),
    ]
