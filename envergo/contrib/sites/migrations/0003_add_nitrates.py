from django.db import connection, migrations


def add_site(apps, schema_editor):
    """Add the nitrates Site.

    Idempotent: skipped if a site with id=3 already exists.
    """
    Site = apps.get_model("sites", "Site")

    if not Site.objects.filter(id=3).exists():
        Site.objects.create(id=3, domain="nitrates.local", name="Simulateur nitrates")

        with connection.cursor() as cursor:
            cursor.execute("SELECT MAX(id) FROM django_site;")
            max_id = cursor.fetchone()[0]
            cursor.execute(
                f"ALTER SEQUENCE django_site_id_seq RESTART WITH {max_id + 1};"
            )


def rm_site(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.filter(id=3).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("sites", "0002_add_haie"),
    ]

    operations = [
        migrations.RunPython(add_site, rm_site),
    ]
