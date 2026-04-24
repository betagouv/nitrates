"""Import the national RPG (PAC parcels) GeoPackage into a geodata Map.

Source officielle IGN (Licence Etalab) :
https://www.data.gouv.fr/datasets/rpg

Usage :
    # France entière (~10M features, long)
    docker compose run --rm django python manage.py import_nitrates_rpg \\
        --file /path/to/PARCELLES_GRAPHIQUES.gpkg

    # Restreint à certains départements (nécessite import_nitrates_departments avant)
    docker compose run --rm django python manage.py import_nitrates_rpg \\
        --file /path/to/PARCELLES_GRAPHIQUES.gpkg \\
        --departments 51,35

Resumable : un Map rpg_parcelle du même nom est réutilisé ; les Zone déjà
importées sont conservées. En mode --departments, l'import itère département
par département (bbox serrée + polygone simplifié + PreparedGeometry pour
un intersects rapide). Sans --departments, scan linéaire.
"""

from pathlib import Path

from django.contrib.gis.gdal import DataSource
from django.contrib.gis.gdal.error import GDALException
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import BaseCommand, CommandError

from envergo.geodata.models import MAP_TYPES, Department, Map, Zone

BATCH_SIZE = 5000
SIMPLIFY_TOLERANCE_M = 50  # Lambert93 est en mètres


class Command(BaseCommand):
    help = "Importe le GeoPackage RPG (parcelles PAC France entière ou filtrées)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            type=Path,
            help="Chemin vers le .gpkg RPG (PARCELLES_GRAPHIQUES.gpkg)",
        )
        parser.add_argument(
            "--millesime",
            default="2023",
            help="Millésime RPG à tagger (défaut 2023)",
        )
        parser.add_argument(
            "--departments",
            default="",
            help=(
                "Codes INSEE des départements à importer, séparés par virgule "
                "(ex: 51,35). Vide = France entière. "
                "Requiert que import_nitrates_departments ait été lancé avant."
            ),
        )

    def handle(self, *args, **options):
        gpkg_path: Path = options["file"]
        millesime: str = options["millesime"]
        departments = [
            d.strip() for d in options["departments"].split(",") if d.strip()
        ]
        if not gpkg_path.exists():
            raise CommandError(f"Fichier introuvable : {gpkg_path}")

        ds = DataSource(str(gpkg_path))
        layer = ds[0]
        layer_srid = layer.srs.srid if layer.srs else 2154

        # Vérifier d'abord que tous les départements sont en DB
        if departments:
            qs = Department.objects.filter(department__in=departments)
            found = list(qs.values_list("department", flat=True))
            missing = set(departments) - set(found)
            if missing:
                raise CommandError(
                    f"Départements introuvables en DB : {sorted(missing)}. "
                    f"Lancer d'abord import_nitrates_departments."
                )

        if departments:
            total_imported = self._import_per_department(
                layer, layer_srid, millesime, sorted(departments)
            )
        else:
            map_obj = self._get_or_create_map(
                millesime, dept_code=None, expected=len(layer)
            )
            total_imported = self._import_all(layer, layer_srid, map_obj)
            map_obj.imported_geometries = total_imported
            map_obj.save(update_fields=["imported_geometries"])

        self.stdout.write(
            self.style.SUCCESS(f"OK : {total_imported} zones importées au total.")
        )

    def _get_or_create_map(self, millesime, dept_code, expected):
        """Un Map par millésime et (optionnel) par département.

        Séparer les Map par département permet de reprendre l'import d'un dept
        interrompu sans retoucher les autres.
        """
        suffix = f" — dept {dept_code}" if dept_code else ""
        name = f"RPG parcelles PAC — {millesime}{suffix}"
        display = f"RPG parcelles PAC {millesime}"
        if dept_code:
            display += f" (département {dept_code})"
        map_obj, created = Map.objects.get_or_create(
            name=name,
            defaults={
                "display_name": display,
                "map_type": MAP_TYPES.rpg_parcelle,
                "source": "https://www.data.gouv.fr/datasets/rpg",
                "description": (
                    f"Registre Parcellaire Graphique {millesime} — "
                    "parcelles agricoles déclarées PAC. Source IGN/ASP."
                ),
                "expected_geometries": expected,
            },
        )
        verb = "Créée" if created else "Réutilisée"
        self.stdout.write(
            f"{verb} : Map id={map_obj.id} name={map_obj.name} "
            f"(déjà {map_obj.zones.count()} zones)"
        )
        return map_obj

    def _import_per_department(self, layer, layer_srid, millesime, dept_codes):
        """Itère département par département, 1 Map par département.

        Pour chaque département : bbox serrée + polygone simplifié + intersects
        via PreparedGeometry → ~1500 features/s vs ~100/s avec l'union.
        Resumable : skip les Map dont imported_geometries >= expected.
        """
        imported_total = 0
        for code in dept_codes:
            d = Department.objects.get(department=code)
            dept_geom = d.geometry.clone()
            if layer_srid != 4326:
                dept_geom.transform(layer_srid)
            simplified = dept_geom.simplify(
                SIMPLIFY_TOLERANCE_M, preserve_topology=True
            )
            prepared = simplified.prepared

            layer.spatial_filter = simplified.extent
            total_in_bbox = len(layer)
            self.stdout.write(
                f"Département {code} : {total_in_bbox} features dans la bbox"
            )

            map_obj = self._get_or_create_map(
                millesime, dept_code=code, expected=total_in_bbox
            )
            already = map_obj.zones.count()

            # Skip si déjà complet (expected ~= features dans la bbox)
            if (
                already
                and map_obj.expected_geometries
                and already >= int(0.95 * map_obj.expected_geometries)
            ):
                self.stdout.write(
                    f"  ✓ dept {code} déjà importé ({already} zones), skip"
                )
                imported_total += already
                continue

            # Si import partiel, on purge et on recommence proprement sur ce dept
            if already:
                self.stdout.write(
                    f"  import partiel détecté ({already} zones), purge et reprise"
                )
                map_obj.zones.all().delete()

            imported = self._import_layer_with_filter(
                layer, layer_srid, map_obj, prepared
            )
            map_obj.imported_geometries = imported
            map_obj.save(update_fields=["imported_geometries"])
            imported_total += imported
            self.stdout.write(f"  → {imported} parcelles importées pour {code}")

        return imported_total

    def _import_all(self, layer, layer_srid, map_obj):
        """Import linéaire sans filtre département (France entière)."""
        total = len(layer)
        self.stdout.write(f"Found {total} features")
        return self._import_layer_with_filter(layer, layer_srid, map_obj, None)

    def _import_layer_with_filter(self, layer, layer_srid, map_obj, prepared_filter):
        """Itère la layer courante et insère les features qui matchent.

        prepared_filter : PreparedGeometry dans le SRID de la layer, ou None
        (import sans filtre). Si fourni, seules les features qui intersectent
        sont importées.
        """
        batch = []
        imported = 0
        total = len(layer)
        i = 0
        layer_iter = iter(layer)
        while True:
            try:
                feature = next(layer_iter)
            except StopIteration:
                break
            except GDALException:
                # Fin de layer mal remontée par OGR (pointeur NULL sur
                # GetNextFeature alors qu'on est au bout, surtout après un
                # spatial_filter). On considère ça comme fin d'itération.
                break
            try:
                geom = GEOSGeometry(
                    feature.geom.wkt, srid=feature.geom.srid or layer_srid
                )
                if geom.geom_type == "Polygon":
                    geom = MultiPolygon(geom, srid=geom.srid)

                if prepared_filter and not prepared_filter.intersects(geom):
                    i += 1
                    continue

                # Reprojeter vers 4326 uniquement pour les features conservées
                if geom.srid and geom.srid != 4326:
                    geom.transform(4326)

                attributes = {f: feature.get(f) for f in feature.fields}
                batch.append(Zone(map=map_obj, geometry=geom, attributes=attributes))
            except Exception as e:
                self.stderr.write(f"feature {i} ignorée: {e}")
                i += 1
                continue

            i += 1
            if len(batch) >= BATCH_SIZE:
                Zone.objects.bulk_create(batch, batch_size=BATCH_SIZE)
                imported += len(batch)
                batch = []
                pct = 100 * i // total if total else 100
                self.stdout.write(f"  scanned {i}/{total} ({pct}%), kept {imported}")

        if batch:
            Zone.objects.bulk_create(batch, batch_size=BATCH_SIZE)
            imported += len(batch)

        return imported
