"""Provisionnement carte #98 — scission du fertilisant « Effluents peu chargés ».

Carte #98 (MVP-2) : dans la catégorie « Autre » du formulaire, l'ancienne
sous-catégorie unique « Effluents peu chargés » est remplacée par deux
sous-catégories distinctes, toutes deux de type réglementaire II :

    - effluents_peu_charges_elevage      « ... issus d'élevage »
    - effluents_peu_charges_non_elevage  « ... non issus d'élevage »

Chacune porte des `champs_prefill` qui pré-répondent aux questions
complémentaires de l'arbre (`effluent_peu_charge`, `effluent_peu_charge_elevage`)
pour qu'elles soient inférées et non posées.

Ce script fait DEUX choses :

  1. (re)seed des référentiels depuis `referentiels.yaml` via la commande
     `seed_referentiels` — crée/maj les deux nouveaux fertilisants (cumulatif).
  2. supprime l'ancien fertilisant `effluents_peu_charges_autre` s'il existe
     encore en base (le seed cumulatif ne supprime jamais ; il faut le faire
     explicitement pour que staging converge vers l'état cible).

Idempotent et cumulatif : rejouable autant de fois que voulu, l'état final
est stable. Conçu pour le déploiement staging (puis prod en changeant la cible).

Usage :
    python manage.py provision_carte_98
    python manage.py provision_carte_98 --dry-run   # n'écrit rien
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from envergo.nitrates.models import Fertilisant

# Slug de l'ancien fertilisant à retirer (remplacé par les deux nouveaux).
ANCIEN_SLUG = "effluents_peu_charges_autre"

# Slugs cibles attendus après provisionnement (contrôle de cohérence).
NOUVEAUX_SLUGS = (
    "effluents_peu_charges_elevage",
    "effluents_peu_charges_non_elevage",
)


class Command(BaseCommand):
    help = (
        "Provisionne la scission du fertilisant « Effluents peu chargés » "
        "(carte #98). Idempotent, rejouable au déploiement."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche ce qui serait fait sans écrire en base.",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — aucune écriture."))

        with transaction.atomic():
            # 1. Seed cumulatif : crée/maj les nouveaux fertilisants (+ flags).
            #    On délègue à seed_referentiels pour rester DRY et profiter de
            #    son idempotence (update_or_create sur l'identifiant).
            self.stdout.write("Seed des référentiels (seed_referentiels)…")
            call_command("seed_referentiels", *(["--dry-run"] if dry_run else []))

            # 2. Suppression de l'ancien fertilisant, s'il subsiste.
            ancien = Fertilisant.objects.filter(identifiant=ANCIEN_SLUG)
            if ancien.exists():
                if dry_run:
                    self.stdout.write(
                        self.style.WARNING(f"  [dry-run] supprimerait {ANCIEN_SLUG}")
                    )
                else:
                    ancien.delete()
                    self.stdout.write(self.style.SUCCESS(f"  Supprimé : {ANCIEN_SLUG}"))
            else:
                self.stdout.write(f"  {ANCIEN_SLUG} déjà absent — rien à faire.")

            # 3. Contrôle de cohérence : les deux nouveaux doivent exister.
            presents = set(
                Fertilisant.objects.filter(identifiant__in=NOUVEAUX_SLUGS).values_list(
                    "identifiant", flat=True
                )
            )
            manquants = set(NOUVEAUX_SLUGS) - presents
            if manquants and not dry_run:
                # Anomalie : le YAML ne contient pas les nouveaux slugs.
                # On rollback pour ne pas laisser un état partiel.
                self.stderr.write(
                    self.style.ERROR(
                        f"Fertilisants attendus manquants après seed : "
                        f"{sorted(manquants)}. Vérifie referentiels.yaml. "
                        f"Rollback."
                    )
                )
                transaction.set_rollback(True)
                return

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS("Provisionnement carte #98 terminé."))
