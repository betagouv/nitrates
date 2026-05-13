from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0011_rename_is_instructor_for_departments_user_is_instructor"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="proconnect_sub",
            field=models.CharField(
                blank=True,
                max_length=255,
                null=True,
                unique=True,
                verbose_name="Identifiant ProConnect (sub)",
            ),
        ),
    ]
