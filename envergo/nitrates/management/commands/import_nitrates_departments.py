"""Import French departments geometries into geodata.Department.

Source officielle IGN ADMIN EXPRESS COG (Licence Etalab) :
https://geoservices.ign.fr/adminexpress

Usage :

    # Avec une URL .zip (ex : mirror, archive perso) :
    docker compose run --rm django python manage.py import_nitrates_departments \\
        --url https://example.com/admin-express-cog.zip

    # Avec un fichier .shp local deja decompresse :
    docker compose run --rm django python manage.py import_nitrates_departments \\
        --file /path/to/DEPARTEMENT.shp

NB : l'IGN distribue ADMIN EXPRESS en .7z (236 Mo metropole). Cette
commande ne sait extraire que .zip, elle ne tape donc pas l'IGN
directement. Pour usage IGN : decompresser localement, puis --file ou
re-zipper et exposer sur un mirror .zip.

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


class Command(BaseCommand):
    help = "Importe les départements depuis le shapefile ADMIN EXPRESS."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
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
            help=(
                "URL d'un .zip contenant DEPARTEMENT.shp (et fichiers "
                "associes). On telecharge dans un tempdir, on decompresse, "
                "on cherche DEPARTEMENT.shp recursivement."
            ),
        )

    def handle(self, *args, **options):
        shp_path: Path | None = options.get("file")
        url: str | None = options.get("url")

        tmpdir: Path | None = None
        try:
            if url and not shp_path:
                tmpdir, shp_path = self._download_and_extract(url)

            if not shp_path or not shp_path.exists():
                raise CommandError(f"Fichier introuvable : {shp_path}")

            self._import_shapefile(shp_path)
        finally:
            if tmpdir is not None and tmpdir.exists():
                shutil.rmtree(tmpdir, ignore_errors=True)

    # ─── Download + unzip ──────────────────────────────────────────────────

    def _download_and_extract(self, url: str) -> tuple[Path, Path]:
        """Telecharge `url` (zip) en streaming dans un tempdir et
        retourne (tmpdir, chemin_du_DEPARTEMENT.shp_trouve)."""
        tmpdir = Path(tempfile.mkdtemp(prefix="nitrates_dep_"))
        zip_path = tmpdir / "download.zip"

        self.stdout.write(f"Telechargement : {url}")
        req = Request(url, headers={"User-Agent": "envergo-nitrates/1.0"})
        with urlopen(req) as resp, open(zip_path, "wb") as out:
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

        self.stdout.write(f"Decompression : {zip_path} -> {tmpdir}")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmpdir)
        zip_path.unlink()

        shp_files = [
            p for p in tmpdir.rglob("*.shp") if "DEPARTEMENT" in p.name.upper()
        ]
        if not shp_files:
            raise CommandError(
                f"Aucun DEPARTEMENT.shp trouve dans le zip telecharge ({tmpdir})."
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
