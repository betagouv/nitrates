"""Provisionne un admin par email seul, pour login ProConnect.

Cree (ou met a jour) un User avec is_staff=True, sans password utilisable
(set_unusable_password). Le user pourra se connecter via ProConnect des
que ProConnect renverra le meme email.

Usage :
    python manage.py provision_admin --email max@example.com --name "Max"
    python manage.py provision_admin --email foo@bar.fr --superuser
    python manage.py provision_admin --email a@b.fr --revoke

Idempotent : rejouer N fois = etat final stable.
"""

from django.core.management.base import BaseCommand, CommandError

from envergo.users.models import User


class Command(BaseCommand):
    help = "Provisionne un admin par email pour login ProConnect."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            required=True,
            help="Email de l'admin (sera utilise pour matcher la session ProConnect).",
        )
        parser.add_argument(
            "--name",
            default="",
            help="Nom affiche (sinon rempli a la 1ere connexion ProConnect).",
        )
        parser.add_argument(
            "--superuser",
            action="store_true",
            help="Donne le statut superuser (acces a tout l'admin Django).",
        )
        parser.add_argument(
            "--revoke",
            action="store_true",
            help="Retire is_staff/is_superuser au lieu de provisionner. "
            "Le compte est conserve mais ne peut plus se connecter a l'admin.",
        )

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        name = options["name"].strip()
        superuser = options["superuser"]
        revoke = options["revoke"]

        if not email:
            raise CommandError("--email vide")

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "name": name,
                "is_active": True,
            },
        )

        if revoke:
            user.is_staff = False
            user.is_superuser = False
            user.save(update_fields=["is_staff", "is_superuser"])
            self.stdout.write(self.style.WARNING(f"Acces admin retire pour {email}"))
            return

        if name and not user.name:
            user.name = name

        user.is_staff = True
        if superuser:
            user.is_superuser = True
        user.is_active = True

        # Pas de password utilisable : la connexion passe forcement par ProConnect.
        # On ne touche au password que si le compte est nouveau ou n'a deja
        # pas de password utilisable (preserve un eventuel acces emergency).
        if created or not user.has_usable_password():
            user.set_unusable_password()

        user.save()

        verb = "cree" if created else "mis a jour"
        flags = ["is_staff"]
        if superuser:
            flags.append("is_superuser")
        self.stdout.write(
            self.style.SUCCESS(
                f"Admin {verb} : {email} ({', '.join(flags)}). "
                f"Connexion via ProConnect uniquement."
            )
        )
