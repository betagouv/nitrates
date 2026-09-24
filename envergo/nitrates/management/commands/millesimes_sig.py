"""Pilotage des millésimes des couches SIG nitrates (ZV, ZAR).

Les couches SIG sont versionnées : plusieurs millésimes d'une même couche
coexistent en base (même `Map.name`, `Map.version` différent), un seul est
actif et servi au produit.

Cette commande est l'outil d'exploitation de ce mécanisme : voir l'état,
basculer d'un millésime à l'autre (y compris revenir en arrière), et purger
un vieux millésime quand on veut récupérer la place.

Usage :

    # État des couches et de leurs millésimes (à lancer après un déploiement) :
    docker compose run --rm django python manage.py millesimes_sig

    # Rollback : revenir au millésime 2024 des ZAR Grand Est.
    # Instantané : les zones n'ont jamais été supprimées.
    docker compose run --rm django python manage.py millesimes_sig \\
        --couche zar_par7_grand_est --activer 2024

    # Purge d'un vieux millésime (refuse de purger l'actif) :
    docker compose run --rm django python manage.py millesimes_sig \\
        --couche zar_par7_grand_est --purger 2024
"""

from django.core.management.base import BaseCommand, CommandError

from envergo.nitrates.sig_versioning import (
    lister_millesimes,
    purger_millesime,
    reactiver_millesime,
)


class Command(BaseCommand):
    help = (
        "Affiche et pilote les millésimes des couches SIG nitrates "
        "(bascule, rollback, purge)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--couche",
            help="Nom interne de la couche (ex. zar_par7_grand_est).",
        )
        action = parser.add_mutually_exclusive_group()
        action.add_argument(
            "--activer",
            metavar="VERSION",
            help="Active ce millésime et désactive les autres (rollback).",
        )
        action.add_argument(
            "--purger",
            metavar="VERSION",
            help="Supprime définitivement ce millésime et ses zones.",
        )

    def handle(self, *args, **options):
        couche = options.get("couche")
        activer = options.get("activer")
        purger = options.get("purger")

        if (activer or purger) and not couche:
            raise CommandError("--activer / --purger exigent --couche.")

        if activer:
            self._activer(couche, activer)
        elif purger:
            self._purger(couche, purger)

        self._lister(couche)

    # ─── Actions ───────────────────────────────────────────────────────────

    def _activer(self, couche: str, version: str) -> None:
        try:
            cible = reactiver_millesime(name=couche, version=version)
        except ValueError as exc:
            raise CommandError(str(exc))
        self.stdout.write(
            self.style.SUCCESS(
                f"« {couche} » sert désormais le millésime {cible.version} "
                f"({cible.zones.count()} zones)."
            )
        )

    def _purger(self, couche: str, version: str) -> None:
        try:
            cible, nb_zones = purger_millesime(name=couche, version=version)
        except ValueError as exc:
            raise CommandError(str(exc))
        self.stdout.write(
            self.style.WARNING(
                f"Millésime {version} de « {couche} » supprimé "
                f"({nb_zones} zones). Irréversible : un ré-import est "
                "nécessaire pour le retrouver."
            )
        )

    # ─── Affichage ─────────────────────────────────────────────────────────

    def _lister(self, couche: str | None) -> None:
        maps = list(lister_millesimes(couche))
        if not maps:
            cible = f" pour « {couche} »" if couche else ""
            self.stdout.write(self.style.WARNING(f"Aucune couche{cible}."))
            return

        self.stdout.write("")
        self.stdout.write(
            f"{'ACTIF':<6} {'COUCHE':<28} {'MILLÉSIME':<11} " f"{'ZONES':>7}  TYPE"
        )
        self.stdout.write("─" * 78)

        for m in maps:
            marque = "  ●  " if m.is_active else "     "
            ligne = (
                f"{marque:<6} {m.name[:28]:<28} {(m.version or '—'):<11} "
                f"{m.zones.count():>7}  {m.map_type or '—'}"
            )
            self.stdout.write(self.style.SUCCESS(ligne) if m.is_active else ligne)

        self.stdout.write("")

        # Garde-fou : une couche sans millésime actif n'est plus servie du
        # tout. Ça arrive si un import --no-activate est resté en plan.
        noms = {m.name for m in maps}
        for nom in sorted(noms):
            millesimes = [m for m in maps if m.name == nom]
            actifs = [m for m in millesimes if m.is_active]
            if not actifs:
                self.stdout.write(
                    self.style.ERROR(
                        f"⚠  « {nom} » n'a AUCUN millésime actif : cette "
                        "couche n'est pas servie au produit."
                    )
                )
            elif len(actifs) > 1:
                versions = ", ".join(m.version or "—" for m in actifs)
                self.stdout.write(
                    self.style.ERROR(
                        f"⚠  « {nom} » a PLUSIEURS millésimes actifs "
                        f"({versions}) : les zones se cumulent."
                    )
                )
