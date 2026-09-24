"""Importe un shapefile de Zone d'Action Renforcée (ZAR) dans une Map geodata.

La ZAR (Zone d'Action Renforcée) est une notion complémentaire à la zone
vulnérable : des secteurs (souvent des Aires d'Alimentation de Captage) où des
mesures renforcées du PAR s'appliquent. On les reçoit par région.

Régions couvertes (cf. `REGIONS` ci-dessous) :

  - `grand-est`     : ZAR du PAR 7 Grand Est. Millésime courant 2026.
  - `hauts-de-france` : ZAR Hauts-de-France. Importées pour la **cohérence
    visuelle de la carte** : il n'y a pas de PAR ZAR spécifique en HdF, donc
    aucun arbre ZAR ne leur est rattaché. Un point en ZAR HdF retombe sur
    l'arbre PAR Hauts-de-France, ou sur le PAN à défaut. C'est voulu.

Source : shapefile fourni par la DREAL, déposé sur le bucket S3 (Cellar) du
projet. La commande télécharge depuis l'URL S3 par défaut (marche sur tous
les environnements), ou utilise un fichier local (`--file`) pour le dev
offline.

Usage :

    # Import d'une région (millésime par défaut du registre) :
    docker compose run --rm django python manage.py import_nitrates_zar \\
        --region grand-est

    # Toutes les régions d'un coup (ce que fait le provisioning) :
    docker compose run --rm django python manage.py import_nitrates_zar --all

    # Fichier local (.shp, .zip ou .7z déjà décompressé) :
    docker compose run --rm django python manage.py import_nitrates_zar \\
        --region hauts-de-france --file /path/to/Couches_zar_partenaires.shp

    # Import sans bascule : la couche est importée mais pas servie.
    # Permet de préparer un millésime puis de basculer plus tard.
    docker compose run --rm django python manage.py import_nitrates_zar \\
        --region grand-est --no-activate

**Versioning** : chaque import crée/réutilise la Map du millésime cible
(`Map.version`), la remplit, puis l'active — ce qui désactive les autres
millésimes de la même couche sans supprimer leurs zones. Un import
interrompu ne casse rien : tant que la bascule n'a pas eu lieu, l'ancien
millésime continue d'être servi. Rollback via
`manage.py millesimes_sig --activer`.

Idempotent : rejouer la commande sur un millésime déjà importé met à jour
les zones, crée les nouvelles et supprime celles disparues de la source.
"""

import os
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

from envergo.geodata.models import MAP_TYPES, Zone
from envergo.nitrates.sig_versioning import activer_millesime, get_or_create_millesime

# Repli reseau si l'archive embarquee est absente. Pilotable par env :
# chaque environnement a son propre bucket Cellar.
BUCKET = os.environ.get(
    "NITRATES_SIG_BUCKET_URL",
    "https://bucket-nitrates.cellar-c2.services.clever-cloud.com/sig",
).rstrip("/")

# Les archives ZAR sont petites (< 500 Ko au total) et versionnées AVEC le
# code, dans `envergo/nitrates/sig/`. Elles sont donc disponibles sur tous
# les environnements sans dépendre du réseau ni du bucket : le provisioning
# marche partout, y compris en CI et en local offline.
#
# (La couche ZV 2026 fait 39 Mo : celle-là reste sur le bucket.)
SIG_EMBARQUE = Path(__file__).resolve().parents[2] / "sig"

# Registre des couches ZAR par région.
#
# `cle_naturelle` : champ du shapefile qui identifie une zone de façon stable
# entre deux millésimes. Attention, c'est un nom : un renommage côté DREAL
# est vu comme « ancienne zone supprimée + nouvelle zone créée ». C'est le
# comportement voulu (on suit la source), et le versioning garantit qu'on
# peut comparer les deux millésimes pour vérifier.
REGIONS = {
    "grand-est": {
        "map_name": "zar_par7_grand_est",
        "display_name": "Zones d'action renforcée — Grand Est (PAR 7)",
        "description": (
            "Zones d'action renforcée du PAR Grand Est (PAR 7). "
            "Aires d'alimentation de captage."
        ),
        "version": "2026",
        "archive": "zar_par7_grand-est_juillet2026.zip",
        "url": f"{BUCKET}/zar_par7_grand-est_juillet2026.zip",
        "cle_naturelle": "NOMZAR",
        "departements": None,
    },
    "hauts-de-france": {
        "map_name": "zar_hauts_de_france",
        "display_name": "Zones d'action renforcée — Hauts-de-France",
        "description": (
            "Zones d'action renforcée Hauts-de-France (couches partenaires). "
            "Affichage carte uniquement : pas de PAR ZAR spécifique en HdF, "
            "les arbres retombent sur le PAR régional ou le PAN."
        ),
        "version": "2026",
        "archive": "zar_hauts-de-france_20260923.zip",
        "url": f"{BUCKET}/zar_hauts-de-france_20260923.zip",
        # Le shapefile HdF n'a pas de NOMZAR : il porte `Commune` + une
        # `Catégorie`. La commune sert de clé naturelle.
        "cle_naturelle": "Commune",
        "departements": None,
    },
}

# Clé sous laquelle on stocke la clé naturelle résolue dans `attributes`,
# pour pouvoir la retrouver à l'import suivant (idempotence stable).
CLE_ATTR = "_cle_naturelle"


class Command(BaseCommand):
    help = (
        "Importe un shapefile ZAR (Zone d'Action Renforcée) dans une Map "
        "geodata versionnée. Télécharge depuis le bucket S3 par défaut."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--region",
            choices=sorted(REGIONS),
            help="Région à importer. Exclusif avec --all.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help=f"Importe toutes les régions ({', '.join(sorted(REGIONS))}).",
        )
        # `--version` est réservé par Django (affiche la version du
        # framework), d'où `--millesime`.
        parser.add_argument(
            "--millesime",
            help="Millésime cible (défaut : celui du registre pour la région).",
        )
        source = parser.add_mutually_exclusive_group()
        source.add_argument(
            "--file",
            type=Path,
            help="Chemin vers un .shp ou .zip local (dev offline / debug).",
        )
        source.add_argument(
            "--url",
            help="URL d'un .zip contenant le shapefile (défaut : bucket S3).",
        )
        parser.add_argument(
            "--no-activate",
            action="store_true",
            help=(
                "Importe sans basculer : le millésime reste inactif et le "
                "produit continue de servir l'ancien."
            ),
        )

    def handle(self, *args, **options):
        if options["all"] and options["region"]:
            raise CommandError("--all et --region sont exclusifs.")
        if not options["all"] and not options["region"]:
            raise CommandError(
                "Précise --region <"
                + "|".join(sorted(REGIONS))
                + "> ou --all pour tout importer."
            )

        regions = sorted(REGIONS) if options["all"] else [options["region"]]

        if len(regions) > 1 and (options.get("file") or options.get("url")):
            raise CommandError(
                "--file / --url ne valent que pour une seule région "
                "(ils désignent un fichier précis). Utilise --region."
            )

        for region in regions:
            self._import_region(region, options)

    # ─── Import d'une région ───────────────────────────────────────────────

    def _import_region(self, region: str, options) -> None:
        conf = REGIONS[region]
        version = options.get("millesime") or conf["version"]

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"── ZAR {region} — millésime {version} ──────────────────"
            )
        )

        shp_path: Path | None = options.get("file")
        tmpdir: Path | None = None
        try:
            if shp_path is None and not options.get("url"):
                # Source par défaut : l'archive versionnée avec le code.
                embarquee = SIG_EMBARQUE / conf["archive"]
                if embarquee.exists():
                    self.stdout.write(f"Archive embarquée : {embarquee.name}")
                    shp_path = embarquee
                else:
                    # Repli sur le bucket si l'archive n'est pas là (cas d'un
                    # déploiement qui n'embarquerait pas les fichiers SIG).
                    tmpdir, shp_path = self._download_and_extract(conf["url"])

            if shp_path is None:
                tmpdir, shp_path = self._download_and_extract(options["url"])
            elif shp_path.suffix.lower() == ".zip":
                tmpdir, shp_path = self._extract_zip(shp_path)

            if not shp_path.exists():
                raise CommandError(f"Fichier introuvable : {shp_path}")

            self._import_shapefile(shp_path, conf, version, options)
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

    # ─── Import idempotent dans un millésime ───────────────────────────────

    def _import_shapefile(self, shp_path: Path, conf: dict, version: str, options):
        ds = DataSource(str(shp_path))
        layer = ds[0]
        total = len(layer)
        self.stdout.write(f"{total} features dans {shp_path.name}")

        cle_field = conf["cle_naturelle"]
        if total and cle_field not in layer.fields:
            raise CommandError(
                f"Champ clé « {cle_field} » absent du shapefile. "
                f"Champs disponibles : {', '.join(layer.fields)}."
            )

        map_obj, created = get_or_create_millesime(
            name=conf["map_name"],
            version=version,
            defaults={
                "display_name": conf["display_name"],
                "map_type": MAP_TYPES.zone_action_renforcee,
                "description": conf["description"],
                "expected_geometries": total,
                "departments": conf.get("departements"),
            },
        )
        verb = "Créé" if created else "Réutilisé"
        self.stdout.write(
            f"{verb} : Map id={map_obj.id} name={map_obj.name} version={version}"
        )

        occurrences = defaultdict(int)
        created_count = 0
        updated_count = 0
        # Ids des zones ÉCRITES par cet import ; tout le reste sera pruné.
        ids_ecrits: list[int] = []

        with transaction.atomic():
            # Index construit DANS la transaction et verrouillé : deux
            # imports concurrents se sérialisent au lieu de créer chacun
            # leur jeu de zones.
            existing_by_code = {}
            for z in map_obj.zones.select_for_update().all():
                code = (z.attributes or {}).get(CLE_ATTR)
                if code and code not in existing_by_code:
                    existing_by_code[code] = z.id

            for feature in layer:
                attributes = {f: feature.get(f) for f in feature.fields}
                attributes = {
                    k: (v.isoformat() if hasattr(v, "isoformat") else v)
                    for k, v in attributes.items()
                }
                code = self._cle_naturelle_avec_suffixe(
                    attributes, occurrences, cle_field
                )
                attributes[CLE_ATTR] = code

                geom = self._to_multipolygon_wgs84(feature)

                if code in existing_by_code:
                    zone_id = existing_by_code[code]
                    Zone.objects.filter(id=zone_id).update(
                        geometry=geom, attributes=attributes
                    )
                    updated_count += 1
                else:
                    zone = Zone.objects.create(
                        map=map_obj, geometry=geom, attributes=attributes
                    )
                    zone_id = zone.id
                    created_count += 1
                ids_ecrits.append(zone_id)

                processed = created_count + updated_count
                if processed % 50 == 0 or processed == total:
                    self.stdout.write(
                        f"  {processed}/{total} ({100 * processed // total}%)"
                    )

            # Prune EXHAUSTIF : tout ce que cet import n'a pas écrit
            # disparaît. Couvre les zones retirées de la source, mais aussi
            # les doublons d'un import précédent interrompu. Ne touche
            # jamais aux autres millésimes (Map distincte).
            deleted_count, _ = map_obj.zones.exclude(id__in=ids_ecrits).delete()

        map_obj.imported_geometries = created_count + updated_count
        map_obj.expected_geometries = total
        map_obj.save(update_fields=["imported_geometries", "expected_geometries"])

        self.stdout.write(
            self.style.SUCCESS(
                f"OK : {created_count} créées, {updated_count} mises à jour, "
                f"{deleted_count} supprimées."
            )
        )

        if options.get("no_activate"):
            self.stdout.write(
                self.style.WARNING(
                    f"--no-activate : millésime {version} importé mais NON "
                    f"servi. Bascule avec :\n"
                    f"  manage.py millesimes_sig --couche {map_obj.name} "
                    f"--activer {version}"
                )
            )
            return

        anciens = activer_millesime(map_obj)
        if anciens:
            detail = ", ".join(
                f"{m.version or '—'} ({m.zones.count()} zones)" for m in anciens
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Millésime {version} ACTIF. Désactivé : {detail}. "
                    "Les zones sont conservées (rollback possible)."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"Millésime {version} ACTIF."))

    # ─── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _cle_naturelle_avec_suffixe(attributes, occurrences, cle_field) -> str:
        """Clé naturelle stable d'une zone. En cas de doublon dans le
        shapefile, on suffixe par l'ordre d'apparition (`#2`, `#3`...) pour
        garder les zones homonymes distinctes (déterministe).

        Il y a de vrais doublons dans les sources : « PPE-Vitry-lès-Nogent »
        apparaît 2× côté Grand Est, et plusieurs ZAR HdF partagent la même
        commune."""
        nom = attributes.get(cle_field) or "zar_sans_nom"
        nom = str(nom).strip()
        occurrences[nom] += 1
        n = occurrences[nom]
        return nom if n == 1 else f"{nom}#{n}"

    @staticmethod
    def _to_multipolygon_wgs84(feature):
        """Géométrie -> MultiPolygon 2D en WGS84. Les shapefiles ZAR sont en
        Lambert 93 (EPSG:2154) et peuvent porter un Z (Polygon25D côté
        Grand Est).

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
        # Réparation post-reprojection : le passage Lambert-93 -> WGS84 peut
        # introduire des auto-intersections sur les contours détaillés, qui
        # feraient ensuite échouer les ST_Intersects du simulateur.
        if not geom.valid:
            from django.db import connection

            with connection.cursor() as cur:
                cur.execute(
                    "SELECT ST_AsEWKB(ST_CollectionExtract(ST_MakeValid("
                    "ST_GeomFromEWKB(%s)), 3))",
                    [geom.ewkb],
                )
                (ewkb,) = cur.fetchone()
            geom = GEOSGeometry(memoryview(ewkb))
            if geom.geom_type == "Polygon":
                geom = MultiPolygon(geom, srid=geom.srid)
        return geom
