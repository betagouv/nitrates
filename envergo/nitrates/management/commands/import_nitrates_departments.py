"""Import French departments geometries into geodata.Department.

Source officielle IGN ADMIN EXPRESS COG (Licence Etalab) :
https://geoservices.ign.fr/adminexpress

Usage :
    docker compose run --rm django python manage.py import_nitrates_departments \\
        --file /path/to/DEPARTEMENT.shp

Idempotent : get_or_create sur le code INSEE du département.
"""

from pathlib import Path

from django.contrib.gis.gdal import DataSource
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import BaseCommand, CommandError

from envergo.geodata.models import Department


class Command(BaseCommand):
    help = "Importe les départements depuis le shapefile ADMIN EXPRESS."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            type=Path,
            help="Chemin vers DEPARTEMENT.shp (ADMIN EXPRESS)",
        )

    def handle(self, *args, **options):
        shp_path: Path = options["file"]
        if not shp_path.exists():
            raise CommandError(f"Fichier introuvable : {shp_path}")

        ds = DataSource(str(shp_path))
        layer = ds[0]
        total = len(layer)
        self.stdout.write(f"Found {total} departments in {shp_path.name}")

        created_count = 0
        updated_count = 0
        for feature in layer:
            code = feature.get("INSEE_DEP")
            geom = GEOSGeometry(feature.geom.wkt, srid=feature.geom.srid or 2154)
            if geom.geom_type == "Polygon":
                geom = MultiPolygon(geom, srid=geom.srid)
            if geom.srid and geom.srid != 4326:
                geom.transform(4326)

            dept, created = Department.objects.update_or_create(
                department=code,
                defaults={"geometry": geom},
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"OK : {created_count} créés, {updated_count} mis à jour."
            )
        )
