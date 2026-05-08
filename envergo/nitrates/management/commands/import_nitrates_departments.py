"""Import French departments geometries into geodata.Department.

Source officielle IGN ADMIN EXPRESS COG (Licence Etalab) :
https://geoservices.ign.fr/adminexpress

Distribuee en .7z par l'IGN (~250 Mo metropole). Le download stable
2024 :
https://data.geopf.fr/telechargement/download/ADMIN-EXPRESS-COG/ADMIN-EXPRESS-COG_3-2__SHP_LAMB93_FXX_2024-02-22/ADMIN-EXPRESS-COG_3-2__SHP_LAMB93_FXX_2024-02-22.7z

Usage :

    # Telechargement direct depuis IGN (defaut, recommandee) :
    docker compose run --rm django python manage.py import_nitrates_departments

    # Avec une URL custom (.7z ou .zip) :
    docker compose run --rm django python manage.py import_nitrates_departments \\
        --url https://example.com/admin-express-cog.7z

    # Avec un fichier .shp local deja decompresse :
    docker compose run --rm django python manage.py import_nitrates_departments \\
        --file /path/to/DEPARTEMENT.shp

Format du conteneur deduit de l'extension de l'URL : .7z via py7zr,
.zip via stdlib zipfile.

Idempotent : update_or_create sur le code INSEE du département.
"""

import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from django.contrib.gis.gdal import DataSource
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import BaseCommand, CommandError

from envergo.geodata.models import Department

DEFAULT_IGN_URL = (
    "https://data.geopf.fr/telechargement/download/ADMIN-EXPRESS-COG/"
    "ADMIN-EXPRESS-COG_3-2__SHP_LAMB93_FXX_2024-02-22/"
    "ADMIN-EXPRESS-COG_3-2__SHP_LAMB93_FXX_2024-02-22.7z"
)


class Command(BaseCommand):
    help = "Importe les départements depuis le shapefile ADMIN EXPRESS."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--file",
            type=Path,
            help=(
                "Chemin vers DEPARTEMENT.shp local deja decompresse "
                "(le repertoire doit aussi contenir le .dbf, .prj, .shx)."
            ),
        )
        group.add_argument(
            "--url",
            default=DEFAULT_IGN_URL,
            help=(
                "URL d'un .7z ou .zip contenant DEPARTEMENT.shp et fichiers "
                "associes (defaut : IGN ADMIN-EXPRESS-COG 2024-02-22)."
            ),
        )

    def handle(self, *args, **options):
        shp_path: Path | None = options.get("file")

        tmpdir: Path | None = None
        try:
            if shp_path is None:
                tmpdir, shp_path = self._download_and_extract(options["url"])

            if not shp_path.exists():
                raise CommandError(f"Fichier introuvable : {shp_path}")

            self._import_shapefile(shp_path)
        finally:
            if tmpdir is not None and tmpdir.exists():
                shutil.rmtree(tmpdir, ignore_errors=True)

    # ─── Download + unzip ──────────────────────────────────────────────────

    def _download_and_extract(self, url: str) -> tuple[Path, Path]:
        """Telecharge `url` (.7z ou .zip) en streaming dans un tempdir,
        decompresse, retourne (tmpdir, chemin_DEPARTEMENT.shp)."""
        tmpdir = Path(tempfile.mkdtemp(prefix="nitrates_dep_"))

        ext = ".7z" if url.lower().endswith(".7z") else ".zip"
        archive_path = tmpdir / f"download{ext}"

        self.stdout.write(f"Telechargement : {url}")
        req = Request(url, headers={"User-Agent": "envergo-nitrates/1.0"})
        with urlopen(req) as resp, open(archive_path, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            chunk_size = 1024 * 1024  # 1 MiB
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = 100 * downloaded // total
                    self.stdout.write(
                        f"  {downloaded // (1024 * 1024)} / "
                        f"{total // (1024 * 1024)} MiB ({pct}%)",
                        ending="\r",
                    )
        self.stdout.write("")

        self.stdout.write(f"Decompression : {archive_path} -> {tmpdir}")
        if ext == ".7z":
            # py7zr est une lib Python pure, pas de dep apt cote dyno
            import py7zr

            with py7zr.SevenZipFile(archive_path, mode="r") as z:
                z.extractall(path=tmpdir)
        else:
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(tmpdir)
        archive_path.unlink()

        shp_files = [
            p for p in tmpdir.rglob("*.shp") if "DEPARTEMENT" in p.name.upper()
        ]
        if not shp_files:
            raise CommandError(
                f"Aucun DEPARTEMENT.shp trouve dans l'archive telechargee ({tmpdir})."
            )
        if len(shp_files) > 1:
            self.stdout.write(
                self.style.WARNING(
                    f"Plusieurs candidats DEPARTEMENT.shp, on prend le 1er : "
                    f"{shp_files}"
                )
            )
        shp_path = shp_files[0]
        self.stdout.write(f"Shapefile trouve : {shp_path}")
        return tmpdir, shp_path

    # ─── Import idempotent ─────────────────────────────────────────────────

    def _import_shapefile(self, shp_path: Path) -> None:
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
                f"OK : {created_count} crees, {updated_count} mis a jour."
            )
        )
