"""Importe un shapefile de Zone d'Action Renforcée (ZAR) dans une Map geodata.

La ZAR (Zone d'Action Renforcée) est une notion complémentaire à la zone
vulnérable : des secteurs (souvent des Aires d'Alimentation de Captage) où des
mesures renforcées du PAR s'appliquent. On les reçoit par région (ici le
Grand Est, PAR 7).

Source : shapefile fourni par la DREAL / déposé sur le bucket S3 (Cellar) du
projet. La commande télécharge depuis l'URL S3 par défaut (marche direct en
staging), ou utilise un fichier local (`--file`) pour le dev offline.

Usage :

    # Téléchargement depuis le bucket S3 (défaut) :
    docker compose run --rm django python manage.py import_nitrates_zar

    # URL custom (autre dépôt) :
    docker compose run --rm django python manage.py import_nitrates_zar \\
        --url https://example.com/zar.zip

    # Fichier .shp ou .zip local :
    docker compose run --rm django python manage.py import_nitrates_zar \\
        --file /path/to/ZAR_PAR7_Grand-Est_juillet2024.shp

Idempotent : la Map `zar_par7_grand_est` est réutilisée ; chaque zone est
identifiée par sa clé naturelle (NOMZAR, suffixée `#n` en cas de doublon de
nom dans le shapefile — il en existe : « PPE-Vitry-lès-Nogent » apparaît 2×).
Rejouer la commande met à jour les zones existantes, crée les nouvelles et
supprime celles disparues de la source (DB miroir de la source).
"""

import shutil
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from urllib.request import Request, urlopen

from django.contrib.gis.gdal import DataSource
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from envergo.geodata.models import MAP_TYPES, Map, Zone

# Nom interne de la Map (clé d'idempotence du Map lui-même).
MAP_NAME = "zar_par7_grand_est"

# URL S3 par défaut (bucket Cellar du projet). Le fichier y est déposé
# manuellement (cf. commande de dépôt dans le ticket #34). En local, on
# passe --file ; en staging, le défaut suffit.
DEFAULT_S3_URL = (
    "https://bucket-nitrates.cellar-c2.services.clever-cloud.com"
    "/sig/zar_par7_grand-est_juillet2024.zip"
)

# Clé naturelle d'une zone : le nom ZAR. Non unique dans le shapefile fourni
# (1 doublon constaté), on suffixe par l'ordre d'apparition en cas de
# collision -> cf. _cle_naturelle_avec_suffixe.
NATURAL_KEY_FIELD = "NOMZAR"

# Clé sous laquelle on stocke la clé naturelle résolue dans `attributes`,
# pour pouvoir la retrouver à l'import suivant (idempotence stable).
CLE_ATTR = "_cle_naturelle"


class Command(BaseCommand):
    help = (
        "Importe un shapefile ZAR (Zone d'Action Renforcée) dans une Map "
        "geodata. Télécharge depuis le bucket S3 par défaut, ou --file local."
    )

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--file",
            type=Path,
            help="Chemin vers un .shp ou .zip local (dev offline / debug).",
        )
        group.add_argument(
            "--url",
            default=DEFAULT_S3_URL,
            help="URL d'un .zip contenant le shapefile (défaut : bucket S3).",
        )

    def handle(self, *args, **options):
        shp_path: Path | None = options.get("file")
        tmpdir: Path | None = None
        try:
            if shp_path is None:
                tmpdir, shp_path = self._download_and_extract(options["url"])
            elif shp_path.suffix.lower() == ".zip":
                # --file pointant sur un zip : on décompresse aussi.
                tmpdir, shp_path = self._extract_zip(shp_path)

            if not shp_path.exists():
                raise CommandError(f"Fichier introuvable : {shp_path}")

            self._import_shapefile(shp_path)
        finally:
            if tmpdir is not None and tmpdir.exists():
                shutil.rmtree(tmpdir, ignore_errors=True)

    # ─── Download + unzip ──────────────────────────────────────────────────

    def _download_and_extract(self, url: str) -> tuple[Path, Path]:
        tmpdir = Path(tempfile.mkdtemp(prefix="nitrates_zar_"))
        zip_path = tmpdir / "download.zip"

        self.stdout.write(f"Téléchargement : {url}")
        req = Request(url, headers={"User-Agent": "envergo-nitrates/1.0"})
        with urlopen(req) as resp, open(zip_path, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            chunk_size = 1024 * 1024
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = 100 * downloaded // total
                    self.stdout.write(
                        f"  {downloaded // 1024} / {total // 1024} KiB ({pct}%)",
                        ending="\r",
                    )
        self.stdout.write("")
        return self._unzip_to_shp(zip_path, tmpdir)

    def _extract_zip(self, zip_path: Path) -> tuple[Path, Path]:
        tmpdir = Path(tempfile.mkdtemp(prefix="nitrates_zar_"))
        return self._unzip_to_shp(zip_path, tmpdir)

    def _unzip_to_shp(self, zip_path: Path, tmpdir: Path) -> tuple[Path, Path]:
        self.stdout.write(f"Décompression : {zip_path.name} -> {tmpdir}")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmpdir)
        shp_files = list(tmpdir.rglob("*.shp"))
        if not shp_files:
            raise CommandError(f"Aucun .shp trouvé dans le zip ({tmpdir}).")
        if len(shp_files) > 1:
            self.stdout.write(
                self.style.WARNING(
                    f"Plusieurs .shp trouvés, on prend le premier : {shp_files}"
                )
            )
        return tmpdir, shp_files[0]

    # ─── Import idempotent ─────────────────────────────────────────────────

    def _import_shapefile(self, shp_path: Path) -> None:
        ds = DataSource(str(shp_path))
        layer = ds[0]
        total = len(layer)
        self.stdout.write(f"{total} features dans {shp_path.name}")

        map_obj, created = Map.objects.get_or_create(
            name=MAP_NAME,
            defaults={
                "display_name": "Zones d'action renforcée — Grand Est (PAR 7)",
                "map_type": MAP_TYPES.zone_action_renforcee,
                "description": (
                    "Zones d'action renforcée du PAR Grand Est (PAR 7). "
                    "Aires d'alimentation de captage."
                ),
                "expected_geometries": total,
            },
        )
        verb = "Créée" if created else "Réutilisée"
        self.stdout.write(f"{verb} : Map id={map_obj.id} name={map_obj.name}")

        # Index clé naturelle -> Zone.id pour les zones déjà en DB.
        existing_by_code = {}
        for z in map_obj.zones.all():
            code = (z.attributes or {}).get(CLE_ATTR)
            if code:
                existing_by_code[code] = z.id

        # Compteur d'occurrences par NOMZAR pour suffixer les doublons de
        # façon déterministe (ordre du shapefile, stable entre imports).
        occurrences = defaultdict(int)
        seen_codes: set[str] = set()
        created_count = 0
        updated_count = 0

        with transaction.atomic():
            for feature in layer:
                attributes = {f: feature.get(f) for f in feature.fields}
                attributes = {
                    k: (v.isoformat() if hasattr(v, "isoformat") else v)
                    for k, v in attributes.items()
                }
                code = self._cle_naturelle_avec_suffixe(attributes, occurrences)
                attributes[CLE_ATTR] = code
                seen_codes.add(code)

                geom = self._to_multipolygon_wgs84(feature)

                if code in existing_by_code:
                    Zone.objects.filter(id=existing_by_code[code]).update(
                        geometry=geom, attributes=attributes
                    )
                    updated_count += 1
                else:
                    Zone.objects.create(
                        map=map_obj, geometry=geom, attributes=attributes
                    )
                    created_count += 1

                processed = created_count + updated_count
                if processed % 50 == 0 or processed == total:
                    self.stdout.write(
                        f"  {processed}/{total} ({100 * processed // total}%)"
                    )

            # Prune : zones en DB absentes de la source.
            orphan_codes = set(existing_by_code) - seen_codes
            deleted_count = 0
            if orphan_codes:
                orphan_ids = [existing_by_code[c] for c in orphan_codes]
                deleted_count, _ = Zone.objects.filter(id__in=orphan_ids).delete()

        map_obj.imported_geometries = created_count + updated_count
        map_obj.save(update_fields=["imported_geometries"])

        self.stdout.write(
            self.style.SUCCESS(
                f"OK : {created_count} créées, {updated_count} mises à jour, "
                f"{deleted_count} supprimées."
            )
        )

    @staticmethod
    def _cle_naturelle_avec_suffixe(attributes, occurrences) -> str:
        """Clé naturelle = NOMZAR. En cas de doublon de nom dans le
        shapefile, on suffixe par l'ordre d'apparition (`#2`, `#3`...) pour
        garder les zones homonymes distinctes (déterministe)."""
        nom = attributes.get(NATURAL_KEY_FIELD) or "zar_sans_nom"
        occurrences[nom] += 1
        n = occurrences[nom]
        return nom if n == 1 else f"{nom}#{n}"

    @staticmethod
    def _to_multipolygon_wgs84(feature):
        """Géométrie -> MultiPolygon 2D en WGS84. Le shapefile ZAR est en
        Lambert 93 (EPSG:2154) et porte un Z (Polygon25D).

        On aplatit le Z AU NIVEAU OGR (avant GEOS) : poser `coord_dim = 2`
        sur l'OGRGeometry puis reconstruire depuis son WKB donne une géométrie
        2D. Aplatir côté GEOS ne marche pas (le Z reste, et la colonne DB
        2D rejette l'insert : « Geometry has Z dimension »)."""
        ogr_geom = feature.geom
        if ogr_geom.coord_dim == 3:
            ogr_geom = ogr_geom.clone()
            ogr_geom.coord_dim = 2
        geom = GEOSGeometry(ogr_geom.wkb, srid=ogr_geom.srid or 2154)
        if geom.geom_type == "Polygon":
            geom = MultiPolygon(geom, srid=geom.srid)
        if geom.srid and geom.srid != 4326:
            geom.transform(4326)
        return geom
