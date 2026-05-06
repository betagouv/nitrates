"""Import the national nitrates Vulnerable Zone shapefile into a geodata Map.

Source officielle Sandre (Licence Etalab) :
https://www.sandre.eaufrance.fr/atlas/srv/fre/catalog.search#/metadata/8ddc0f01-6708-4b23-a79a-e9bac3beeee6

Le shapefile `ZoneVuln_delimitation_EU` (rapportage europeen, ~37 Mo)
est servi par le WFS Sandre via une requete GetFeature avec
`outputFormat=application/shapefile`. C'est le format officiel
publie : pas de cache S3 a faire, on tape directement Sandre.

Usage :

    # Telechargement direct depuis Sandre (defaut, recommandee) :
    docker compose run --rm django python manage.py import_nitrates_zv

    # Avec une URL custom (mirror, archive locale d'un .zip) :
    docker compose run --rm django python manage.py import_nitrates_zv \\
        --url https://example.com/zonevuln.zip

    # Avec un fichier .shp local deja decompresse :
    docker compose run --rm django python manage.py import_nitrates_zv \\
        --file /path/to/ZoneVuln_delimitation_EU.shp

Idempotent : un Map nitrates_zv avec le meme nom est reutilise, les
Zone sont identifiees par leur code naturel CdEuZoneVu (Code EU
ZoneVulnerable, identifiant officiel stable). Rejouer la commande N
fois donne le meme resultat qu'une seule fois : les zones deja en DB
sont mises a jour, les nouvelles sont creees, celles qui ont disparu
de la source officielle Sandre sont supprimees (DB miroir source).
"""

import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from django.contrib.gis.gdal import DataSource
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from envergo.geodata.models import MAP_TYPES, Map, Zone

MAP_NAME = "ZV nitrates — national"

# URL officielle Sandre (WFS GetFeature, format shapefile zip).
# Cf. la page metadata https://www.sandre.eaufrance.fr/atlas/srv/fre/
# catalog.search#/metadata/8ddc0f01-6708-4b23-a79a-e9bac3beeee6
DEFAULT_SANDRE_URL = (
    "https://services.sandre.eaufrance.fr/geo/zrpe"
    "?service=WFS&version=2.0.0&request=GetFeature"
    "&typeNames=sa:ZoneVuln_delimitation_EU"
    "&outputFormat=application/shapefile"
)


class Command(BaseCommand):
    help = (
        "Importe le shapefile des zones vulnerables nitrates (national). "
        "Telecharge depuis Sandre par defaut, ou utilise un fichier local."
    )

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--file",
            type=Path,
            help=(
                "Chemin vers un .shp local deja decompresse (utile pour "
                "tests offline ou debug)."
            ),
        )
        group.add_argument(
            "--url",
            default=DEFAULT_SANDRE_URL,
            help=(
                "URL d'un .zip contenant le shapefile (defaut : Sandre "
                "WFS GetFeature)."
            ),
        )

    def handle(self, *args, **options):
        shp_path: Path | None = options.get("file")

        # Si pas de --file, on telecharge le zip Sandre dans un tempdir
        # qu'on nettoiera a la fin (try/finally).
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
        """Telecharge `url` (zip) en streaming dans un tempdir et
        retourne (tmpdir, chemin_du_shp_trouve)."""
        tmpdir = Path(tempfile.mkdtemp(prefix="nitrates_zv_"))
        zip_path = tmpdir / "download.zip"

        self.stdout.write(f"Telechargement Sandre : {url}")
        # User-Agent explicite : certains serveurs filtrent les UA Python
        # par defaut. Sandre ne filtre pas mais on reste poli.
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
        self.stdout.write("")  # newline apres la barre de progression

        self.stdout.write(f"Decompression : {zip_path} -> {tmpdir}")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmpdir)
        zip_path.unlink()

        # Trouve le .shp dans tmpdir (recursivement, au cas ou Sandre
        # ajouterait un sous-dossier).
        shp_files = list(tmpdir.rglob("*.shp"))
        if not shp_files:
            raise CommandError(f"Aucun .shp trouve dans le zip telecharge ({tmpdir}).")
        if len(shp_files) > 1:
            self.stdout.write(
                self.style.WARNING(
                    f"Plusieurs .shp trouves, on prend le premier : {shp_files}"
                )
            )
        shp_path = shp_files[0]
        self.stdout.write(f"Shapefile trouve : {shp_path.name}")
        return tmpdir, shp_path

    # ─── Import idempotent par code naturel CdEuZoneVu ─────────────────────

    def _import_shapefile(self, shp_path: Path) -> None:
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

        # Index code naturel -> Zone.id pour les zones deja en DB.
        # Les zones sans CdEuZoneVu (cas pathologique : creees a la main avant
        # l'idempotence) sont ignorees par l'index, donc ni matchees ni prunees.
        existing_by_code = {
            z.attributes.get("CdEuZoneVu"): z.id
            for z in map_obj.zones.all()
            if z.attributes and z.attributes.get("CdEuZoneVu")
        }

        seen_codes: set[str] = set()
        created_count = 0
        updated_count = 0
        skipped_no_code = 0

        with transaction.atomic():
            for feature in layer:
                attributes = {f: feature.get(f) for f in feature.fields}
                attributes = {
                    k: (v.isoformat() if hasattr(v, "isoformat") else v)
                    for k, v in attributes.items()
                }
                code = attributes.get("CdEuZoneVu")
                if not code:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Feature sans CdEuZoneVu, skip : "
                            f"{attributes.get('NomZoneVul', '?')}"
                        )
                    )
                    skipped_no_code += 1
                    continue
                seen_codes.add(code)

                geom = GEOSGeometry(feature.geom.wkt, srid=feature.geom.srid or 4326)
                if geom.geom_type == "Polygon":
                    geom = MultiPolygon(geom, srid=geom.srid)
                if geom.srid and geom.srid != 4326:
                    geom.transform(4326)

                if code in existing_by_code:
                    Zone.objects.filter(id=existing_by_code[code]).update(
                        geometry=geom,
                        attributes=attributes,
                    )
                    updated_count += 1
                else:
                    Zone.objects.create(
                        map=map_obj,
                        geometry=geom,
                        attributes=attributes,
                    )
                    created_count += 1

                processed = created_count + updated_count
                if processed % 50 == 0 or processed == total:
                    self.stdout.write(
                        f"  {processed}/{total} ({100 * processed // total}%)"
                    )

            # Prune : Zones presentes en DB mais absentes du shapefile (zones
            # supprimees par Sandre dans une mise a jour). DB en miroir source.
            orphan_codes = set(existing_by_code) - seen_codes
            deleted_count = 0
            if orphan_codes:
                deleted_count, _ = Zone.objects.filter(
                    map=map_obj,
                    attributes__CdEuZoneVu__in=orphan_codes,
                ).delete()

        map_obj.imported_geometries = created_count + updated_count
        map_obj.save(update_fields=["imported_geometries"])

        summary = (
            f"OK : {created_count} crees, {updated_count} mis a jour, "
            f"{deleted_count} supprimes"
        )
        if skipped_no_code:
            summary += f", {skipped_no_code} skip (sans CdEuZoneVu)"
        self.stdout.write(self.style.SUCCESS(summary + "."))
