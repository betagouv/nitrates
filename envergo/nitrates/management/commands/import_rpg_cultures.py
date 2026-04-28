"""Import du referentiel des cultures RPG (table IGN/ASP).

Source officielle :
https://data.geopf.fr/annexes/ressources/documentation/REF_CULTURES_GROUPES_CULTURES_2024.csv

Le millesime courant est embarque dans envergo/nitrates/assets/. Si l'IGN
republie une nouvelle version, on peut soit l'embarquer en remplacement
soit la passer en --file.

Modes :
    insert (defaut)  : non destructif, n'ajoute que les codes manquants
    override         : met a jour libelle / groupe sur tous les codes presents

Usage :
    docker compose run --rm django python manage.py import_rpg_cultures
    docker compose run --rm django python manage.py import_rpg_cultures \\
        --file /chemin/vers/REF_CULTURES_2025.csv --mode override
"""

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from envergo.nitrates.models import RpgCulture

DEFAULT_CSV = (
    Path(__file__).resolve().parent.parent.parent
    / "assets"
    / "REF_CULTURES_GROUPES_CULTURES_2024.csv"
)


class Command(BaseCommand):
    help = "Importe la table de reference des codes culture RPG."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=Path,
            default=DEFAULT_CSV,
            help=(
                "Chemin vers le CSV. Par defaut, on prend l'asset embarque "
                "dans envergo/nitrates/assets/."
            ),
        )
        parser.add_argument(
            "--mode",
            choices=["insert", "override"],
            default="insert",
            help=(
                "insert : ne touche pas aux codes existants (defaut). "
                "override : met a jour libelle et groupe pour tous les codes."
            ),
        )

    def handle(self, *args, **options):
        csv_path: Path = options["file"]
        mode: str = options["mode"]

        if not csv_path.exists():
            raise CommandError(f"Fichier introuvable : {csv_path}")

        rows = self._read_csv(csv_path)
        self.stdout.write(f"Lu {len(rows)} lignes depuis {csv_path.name}")

        created = 0
        updated = 0
        skipped = 0
        existing = set(RpgCulture.objects.values_list("code", flat=True))

        for row in rows:
            code = row["code"]
            if code in existing:
                if mode == "override":
                    RpgCulture.objects.filter(pk=code).update(
                        libelle=row["libelle"],
                        code_groupe=row["code_groupe"],
                        libelle_groupe=row["libelle_groupe"],
                    )
                    updated += 1
                else:
                    skipped += 1
            else:
                RpgCulture.objects.create(**row)
                created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"OK : {created} crees, {updated} mis a jour, {skipped} ignores."
            )
        )

    def _read_csv(self, path: Path):
        # Le CSV IGN est en utf-8 avec separateur ';' et 4 colonnes :
        # CODE_CULTURE;LIBELLE_CULTURE;CODE_GROUPE_CULTURE;LIBELLE_GROUPE_CULTURE
        rows = []
        with path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            for r in reader:
                rows.append(
                    {
                        "code": r["CODE_CULTURE"].strip(),
                        "libelle": r["LIBELLE_CULTURE"].strip(),
                        "code_groupe": r.get("CODE_GROUPE_CULTURE", "").strip(),
                        "libelle_groupe": r.get("LIBELLE_GROUPE_CULTURE", "").strip(),
                    }
                )
        return rows
