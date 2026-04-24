"""Import the national nitrates Vulnerable Zone shapefile into a geodata Map.

Source officielle Sandre (Licence Etalab) :
https://www.sandre.eaufrance.fr/atlas/srv/fre/catalog.search#/metadata/8ddc0f01-6708-4b23-a79a-e9bac3beeee6

Usage :
    docker compose run --rm django python manage.py import_nitrates_zv \\
        --file /path/to/ZoneVuln_delimitation_FXX.shp

Resumable : un Map nitrates_zv avec le même nom est réutilisé,
les Zone déjà importées sont skippées.
"""

from pathlib import Path

from django.contrib.gis.gdal import DataSource
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from envergo.geodata.models import MAP_TYPES, Map, Zone

MAP_NAME = "ZV nitrates — national"


class Command(BaseCommand):
    help = "Importe le shapefile des zones vulnérables nitrates (national)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            type=Path,
            help="Chemin vers le .shp de la ZV nationale",
        )

    def handle(self, *args, **options):
        shp_path: Path = options["file"]
        if not shp_path.exists():
            raise CommandError(f"Fichier introuvable : {shp_path}")

        ds = DataSource(str(shp_path))
        layer = ds[0]
        total = len(layer)
        self.stdout.write(f"Found {total} features in {shp_path.name}")

        map_obj, created = Map.objects.get_or_create(
            name=MAP_NAME,
            defaults={
                "display_name": "Zones vulnérables nitrates (France métropole)",
                "map_type": MAP_TYPES.zv_nitrates,
                "source": (
                    "https://www.sandre.eaufrance.fr/atlas/srv/fre/catalog.search"
                    "#/metadata/8ddc0f01-6708-4b23-a79a-e9bac3beeee6"
                ),
                "description": "Zones vulnérables nitrates métropole. Source Sandre.",
                "expected_geometries": total,
            },
        )
        verb = "Créée" if created else "Réutilisée"
        self.stdout.write(f"{verb} : Map id={map_obj.id} name={map_obj.name}")

        already = map_obj.zones.count()
        if already >= total:
            self.stdout.write(self.style.SUCCESS(f"Déjà importé ({already} zones)."))
            return

        self.stdout.write(f"Import en cours — {already} déjà présentes sur {total}")
        imported = already
        with transaction.atomic():
            for i, feature in enumerate(layer):
                if i < already:
                    continue
                geom = GEOSGeometry(feature.geom.wkt, srid=feature.geom.srid or 4326)
                if geom.geom_type == "Polygon":
                    geom = MultiPolygon(geom, srid=geom.srid)
                if geom.srid and geom.srid != 4326:
                    geom.transform(4326)
                attributes = {f: feature.get(f) for f in feature.fields}
                # Sérialisation dates → ISO pour JSON
                attributes = {
                    k: (v.isoformat() if hasattr(v, "isoformat") else v)
                    for k, v in attributes.items()
                }
                Zone.objects.create(
                    map=map_obj,
                    geometry=geom,
                    attributes=attributes,
                )
                imported += 1
                if imported % 10 == 0 or imported == total:
                    self.stdout.write(
                        f"  {imported}/{total} ({100 * imported // total}%)"
                    )

        map_obj.imported_geometries = imported
        map_obj.save(update_fields=["imported_geometries"])
        self.stdout.write(self.style.SUCCESS(f"OK : {imported} zones importées."))
