"""Importe les couches SIG des Zones Vulnérables (ZV) nitrates.

**Deux sources possibles, selon le millésime.**

*Millésime 2021 et antérieurs* : une couche nationale homogène publiée par
le Sandre (`ZoneVuln_delimitation_EU`), téléchargée via son WFS. Une seule
requête, un seul schéma.

*Millésime 2026* : le Sandre n'a pas encore consolidé le millésime. On
travaille donc sur les livraisons des DREAL, bassin par bassin, agrégées
dans une archive déposée sur le bucket S3 du projet. Ces fichiers sont
hétérogènes (GPKG et Shapefile, schémas d'attributs différents, mailles
différentes), d'où le registre `BASSINS_2026` ci-dessous qui décrit
comment lire chacun.

Le produit, lui, ne voit qu'une chose : une Map active de type
`zv_nitrates` contenant une zone par bassin, chacune portant son code
bassin DCE. C'est ce code qui détermine le PAR applicable, donc chaque
zone doit en porter un et un seul.

Usage :

    # Millésime courant (2026) depuis le bucket S3 :
    docker compose run --rm django python manage.py import_nitrates_zv

    # Depuis l'archive locale (dev offline) :
    docker compose run --rm django python manage.py import_nitrates_zv \\
        --dossier "/chemin/vers/couches SIG ZV 2026"

    # Millésime 2021 (couche Sandre nationale) :
    docker compose run --rm django python manage.py import_nitrates_zv \\
        --millesime 2021

    # Import sans bascule (prépare le millésime, ne le sert pas encore) :
    docker compose run --rm django python manage.py import_nitrates_zv \\
        --no-activate

**Versioning** : l'import remplit la Map du millésime cible puis l'active,
ce qui désactive les millésimes précédents SANS supprimer leurs zones.
Rollback instantané via `manage.py millesimes_sig --activer 2021`.

**Agrégation** : Rhône-Méditerranée et Seine-Normandie sont livrés en maille
communale / cadastrale (3 843 et 7 785 polygones). On les fusionne en une
zone par bassin, pour rester cohérent avec les autres bassins et avec la
façon dont le produit interroge la couche (un point -> un bassin). Le
détail communal reste disponible dans les fichiers source.
"""

import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from django.contrib.gis.gdal import DataSource
from django.contrib.gis.gdal.error import GDALException
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from envergo.geodata.models import MAP_TYPES, Zone
from envergo.nitrates.sig_versioning import activer_millesime, get_or_create_millesime

MAP_NAME = "ZV nitrates — national"

BUCKET = "https://bucket-nitrates.cellar-c2.services.clever-cloud.com/sig"

# Archive des livraisons DREAL 2026 (agrégat des 6 bassins), déposée sur le
# bucket. 39 Mo zippés : trop pour le dépôt git, d'où le bucket.
URL_ZV_2026 = f"{BUCKET}/couches_sig_zv_2026.zip"

# URL officielle Sandre (WFS GetFeature, format shapefile zip), pour les
# millésimes consolidés. Cf. la page metadata
# https://www.sandre.eaufrance.fr/atlas/srv/fre/catalog.search
# #/metadata/8ddc0f01-6708-4b23-a79a-e9bac3beeee6
URL_SANDRE = (
    "https://services.sandre.eaufrance.fr/geo/zrpe"
    "?service=WFS&version=2.0.0&request=GetFeature"
    "&typeNames=sa:ZoneVuln_delimitation_EU"
    "&outputFormat=application/shapefile"
)

# Champs candidats pour la clé naturelle Sandre, dans l'ordre de préférence.
# Gère 2 schémas : `inspireid` (delimitation_EU, depuis 2021) et
# `CdEuZoneVu` (delimitation_FXX, fixtures historiques).
NATURAL_KEY_FIELDS = ("inspireid", "CdEuZoneVu")


# ─── Registre des livraisons DREAL 2026 ────────────────────────────────────
#
# Une entrée par zone ZV à créer. `chemin` est relatif à la racine de
# l'archive. `bassin` est le code DCE qui pilote le choix du PAR : c'est la
# donnée critique, elle est fixée ici et non devinée depuis les attributs
# (les schémas sources sont trop hétérogènes pour ça).
#
# `where` filtre les features à retenir ; `fusionner` indique qu'il faut
# agréger tous les polygones en une seule zone (mailles communales).
BASSINS_2026 = [
    {
        "bassin": "FRF",
        "nom": "ZV bassin Adour-Garonne",
        "chemin": "ZV_AdourGaronne_2026/zonevuln_délimitation_EU.gpkg",
        "where": None,
        "fusionner": False,
    },
    {
        "bassin": "FRA",
        "nom": "ZV bassin Artois-Picardie Escaut",
        "chemin": "ZV_ArtoisPicardie_2026/ZoneVuln_designation_FRA_2026.gpkg",
        "where": None,
        "fusionner": False,
    },
    {
        "bassin": "FRB2",
        "nom": "ZV bassin Artois-Picardie Sambre",
        "chemin": "ZV_ArtoisPicardie_2026/ZoneVuln_designation_FRB2_2026.gpkg",
        "where": None,
        "fusionner": False,
    },
    {
        # 2 features : « délimitation » (FRG_ZV_2026_1, 1 635 km², un
        # sous-ensemble) et « désignation » (FRG_ZV_2026_2, 111 584 km²).
        # C'est la désignation qui fait foi pour le classement en ZV.
        "bassin": "FRG",
        "nom": "ZV bassin Loire-Bretagne",
        "chemin": (
            "ZV_LoireBretagne_2026/dataset/" "zonevuln2026_delimitation_FRG_RGF93.shp"
        ),
        "where": ("CdEuZoneVu", "FRG_ZV_2026_2"),
        "fusionner": False,
    },
    {
        # Livraison v2 (23/09/2026). La v1 (`zonvulnfus_s_r44`) était un
        # découpage RÉGIONAL Grand Est fusionnant 4 bassins, qui débordait
        # de 25 000 km² sur Seine-Normandie et Rhône-Méditerranée. La v2 ne
        # couvre que le périmètre Rhin-Meuse.
        #
        # Elle reste livrée d'un bloc pour les DEUX bassins DCE Rhin (FRC)
        # et Meuse (FRB1), sans frontière entre eux. On ne peut donc pas
        # attribuer un code unique sans se tromper sur la moitié du
        # territoire : le code `FRB1-FRC` et le libellé explicite disent la
        # vérité de la source plutôt que d'en inventer une.
        #
        # Sans conséquence fonctionnelle : le choix de l'arbre PAR se fait
        # sur `region_code`/`zar_zone_id` (cf. `_activation_q`), pas sur le
        # bassin, qui ne sert qu'à l'affichage.
        "bassin": "FRB1-FRC",
        "nom": "Rhin-Meuse",
        "chemin": "ZV_RhinMeuse_2026/ZV-RM-2026-bloc-v2.shp",
        "where": None,
        "fusionner": False,
    },
    {
        # 3 843 sections cadastrales -> 1 zone.
        "bassin": "FRD",
        "nom": "ZV bassin Rhône-Méditerranée",
        "chemin": (
            "ZV_RhoneMed_2026/" "ZV2026_CommunesClasséesEtSectionsCadastrales_VF.shp"
        ),
        "where": None,
        "fusionner": True,
    },
    {
        # 7 785 communes -> 1 zone. Toutes sont en ZV (TYPE_CLASS toujours
        # renseigné) ; `ZV2026=2026` marque les 310 nouvellement classées.
        "bassin": "FRH",
        "nom": "ZV bassin Seine-Normandie",
        "chemin": (
            "ZV_SeineNormandie_2026/Couche SIG Limites communales/"
            "ZV_DIV_COM_FRH_2026.shp"
        ),
        "where": None,
        "fusionner": True,
    },
]

MILLESIME_DEFAUT = "2026"


class Command(BaseCommand):
    help = (
        "Importe les zones vulnérables nitrates dans une Map versionnée. "
        "Millésime 2026 : livraisons DREAL par bassin. 2021 : couche Sandre."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--millesime",
            default=MILLESIME_DEFAUT,
            help=f"Millésime cible (défaut : {MILLESIME_DEFAUT}).",
        )
        source = parser.add_mutually_exclusive_group()
        source.add_argument(
            "--dossier",
            type=Path,
            help=(
                "Dossier local contenant les livraisons DREAL décompressées "
                "(millésime 2026, dev offline)."
            ),
        )
        source.add_argument(
            "--file",
            type=Path,
            help="Chemin vers un .shp local (millésime Sandre mono-couche).",
        )
        source.add_argument(
            "--url",
            help="URL d'un .zip (défaut : bucket S3 ou Sandre selon millésime).",
        )
        parser.add_argument(
            "--no-activate",
            action="store_true",
            help="Importe sans basculer : l'ancien millésime reste servi.",
        )

    def handle(self, *args, **options):
        millesime = options["millesime"]
        tmpdir: Path | None = None
        try:
            if millesime == "2026":
                dossier = options.get("dossier")
                if dossier is None:
                    url = options.get("url") or URL_ZV_2026
                    tmpdir, dossier = self._telecharger_archive(url)
                if not dossier.exists():
                    raise CommandError(f"Dossier introuvable : {dossier}")
                self._import_2026(dossier, millesime, options)
            else:
                shp = options.get("file")
                if shp is None:
                    url = options.get("url") or URL_SANDRE
                    tmpdir, shp = self._telecharger_shp(url)
                if not shp.exists():
                    raise CommandError(f"Fichier introuvable : {shp}")
                self._import_sandre(shp, millesime, options)
        finally:
            if tmpdir is not None and tmpdir.exists():
                shutil.rmtree(tmpdir, ignore_errors=True)

    # ─── Millésime 2026 : livraisons DREAL par bassin ──────────────────────

    def _import_2026(self, dossier: Path, millesime: str, options) -> None:
        racine = self._resoudre_racine(dossier)

        # Contrôle préalable : on vérifie que TOUS les fichiers sont là avant
        # de toucher la base. Un import partiel de la ZV donnerait des trous
        # géographiques silencieux (des points « hors ZV » à tort).
        manquants = [
            b["chemin"] for b in BASSINS_2026 if not (racine / b["chemin"]).exists()
        ]
        if manquants:
            raise CommandError(
                "Fichiers absents de la livraison :\n  - "
                + "\n  - ".join(manquants)
                + f"\n(racine testée : {racine})"
            )

        map_obj, created = get_or_create_millesime(
            name=MAP_NAME,
            version=millesime,
            defaults={
                "display_name": "Zones vulnérables nitrates (France métropole)",
                "map_type": MAP_TYPES.zv_nitrates,
                "source": "Livraisons DREAL par bassin, agrégées.",
                "description": (
                    "Zones vulnérables nitrates métropole, millésime 2026. "
                    "Une zone par bassin DCE. Sources : DREAL de bassin."
                ),
                "expected_geometries": len(BASSINS_2026),
            },
        )
        verb = "Créé" if created else "Réutilisé"
        self.stdout.write(f"{verb} : Map id={map_obj.id} version={millesime}")

        crees = maj = 0
        # Ids des zones ECRITES par cet import. Tout ce qui n'y figure pas
        # sera supprime en fin de transaction.
        ids_ecrits: list[int] = []

        with transaction.atomic():
            # Index construit DANS la transaction, et verrouille : deux
            # imports concurrents sur le meme millesime se serialisent au
            # lieu de creer chacun leur jeu de zones (constate en dev, ou
            # un import interrompu avait laisse des doublons).
            existants = {}
            for z in map_obj.zones.select_for_update().all():
                code = (z.attributes or {}).get("CdEuBassin")
                if code and code not in existants:
                    existants[code] = z.id

            for conf in BASSINS_2026:
                chemin = racine / conf["chemin"]
                geom, nb_features = self._lire_bassin(chemin, conf)

                attributes = {
                    # Clé naturelle ET donnée métier : le code bassin DCE
                    # pilote le choix du PAR régional.
                    "CdEuBassin": conf["bassin"],
                    "NomZoneVul": conf["nom"],
                    "millesime": millesime,
                    "source_fichier": conf["chemin"],
                    "nb_features_source": nb_features,
                    "fusionne": conf["fusionner"],
                }
                if conf["bassin"] in existants:
                    zone_id = existants[conf["bassin"]]
                    Zone.objects.filter(id=zone_id).update(
                        geometry=geom, attributes=attributes
                    )
                    maj += 1
                    etat = "maj"
                else:
                    zone = Zone.objects.create(
                        map=map_obj, geometry=geom, attributes=attributes
                    )
                    zone_id = zone.id
                    crees += 1
                    etat = "créée"
                ids_ecrits.append(zone_id)

                detail = (
                    f"{nb_features} features fusionnées"
                    if conf["fusionner"]
                    else f"{nb_features} feature(s)"
                )
                self.stdout.write(
                    f"  {conf['bassin']:<5} {conf['nom'][:38]:<38} "
                    f"{detail:<26} {etat}"
                )

            # Prune EXHAUSTIF : tout ce que cet import n'a pas écrit
            # disparaît. Couvre les bassins retirés de la source, mais aussi
            # les doublons laissés par un import précédent interrompu, que
            # l'ancien prune (limité aux clés connues) ne rattrapait pas.
            supprimes, _ = map_obj.zones.exclude(id__in=ids_ecrits).delete()
            if supprimes:
                self.stdout.write(
                    self.style.WARNING(
                        f"  {supprimes} zone(s) obsolète(s) supprimée(s) "
                        "de ce millésime."
                    )
                )

        map_obj.imported_geometries = crees + maj
        map_obj.expected_geometries = len(BASSINS_2026)
        map_obj.save(update_fields=["imported_geometries", "expected_geometries"])

        self.stdout.write(
            self.style.SUCCESS(
                f"OK : {crees} créées, {maj} mises à jour, {supprimes} supprimées."
            )
        )
        self._finaliser(map_obj, millesime, options)

    def _resoudre_racine(self, dossier: Path) -> Path:
        """L'archive contient un dossier « couches SIG ZV 2026 ». Selon qu'on
        pointe dessus ou sur son parent, on ajuste."""
        if (dossier / "ZV_AdourGaronne_2026").exists():
            return dossier
        candidats = [
            p for p in dossier.iterdir() if p.is_dir() and p.name.startswith("couches")
        ]
        if len(candidats) == 1:
            return candidats[0]
        return dossier

    def _lire_bassin(self, chemin: Path, conf: dict):
        """Lit une couche DREAL et retourne (MultiPolygon WGS84, nb_features).

        Fusionne les polygones quand la livraison est en maille communale."""
        ds = DataSource(str(chemin))
        layer = ds[0]

        geoms = []
        nb = 0
        vides = 0
        for feature in layer:
            if conf["where"]:
                champ, attendu = conf["where"]
                if str(feature.get(champ)) != attendu:
                    continue
            # Certaines livraisons portent des features sans géométrie
            # (constaté côté Rhône-Méditerranée). On les saute plutôt que
            # de planter : ce sont des lignes de table sans contour.
            try:
                geom = self._to_geos(feature)
            except GDALException:
                vides += 1
                continue
            nb += 1
            geoms.append(geom)

        if vides:
            self.stdout.write(
                self.style.WARNING(
                    f"  {chemin.name} : {vides} feature(s) sans géométrie ignorée(s)."
                )
            )

        if not geoms:
            raise CommandError(
                f"Aucune feature retenue dans {chemin.name} "
                f"(filtre : {conf['where']})."
            )

        if len(geoms) == 1:
            fusion = geoms[0]
        else:
            # Union déléguée à PostGIS : `ST_Union` en agrégat traite les
            # 7 785 communes de Seine-Normandie en quelques secondes, là où
            # une boucle `a.union(b)` en Python prend des dizaines de minutes
            # (chaque étape recopie une géométrie qui grossit).
            fusion = self._union_postgis(geoms)

        # Réparation post-reprojection. Les fichiers DREAL sont valides en
        # Lambert-93, mais le passage en WGS84 peut introduire des
        # auto-intersections sur les contours très détaillés (constaté sur
        # Rhin-Meuse). Une géométrie invalide fait échouer les ST_Intersects
        # du simulateur avec une TopologyException : on répare ici plutôt que
        # de laisser une bombe à retardement en base.
        fusion = self._reparer(fusion)

        if fusion.geom_type == "Polygon":
            fusion = MultiPolygon(fusion, srid=fusion.srid)
        return fusion, nb

    @staticmethod
    def _reparer(geom):
        """Rend la géométrie valide si besoin, via `ST_MakeValid` (PostGIS).

        Retourne la géométrie inchangée si elle est déjà valide — on ne
        touche pas aux contours réglementaires sans raison."""
        if geom.valid:
            return geom

        from django.db import connection

        with connection.cursor() as cur:
            cur.execute(
                "SELECT ST_AsEWKB(ST_CollectionExtract(ST_MakeValid("
                "ST_GeomFromEWKB(%s)), 3))",
                [geom.ewkb],
            )
            (ewkb,) = cur.fetchone()
        return GEOSGeometry(memoryview(ewkb))

    @staticmethod
    def _union_postgis(geoms):
        """Union d'une liste de géométries via PostGIS, sans table de travail.

        `ST_UnaryUnion(ST_Collect(...))` sur une seule ligne : on passe les
        WKB en paramètres et on récupère le résultat, sans rien écrire."""
        from django.db import connection

        with connection.cursor() as cur:
            placeholders = ", ".join(["ST_GeomFromEWKB(%s)"] * len(geoms))
            cur.execute(
                f"SELECT ST_AsEWKB(ST_UnaryUnion(ST_Collect(ARRAY[{placeholders}])))",
                [g.ewkb for g in geoms],
            )
            (ewkb,) = cur.fetchone()
        # `memoryview` : GEOSGeometry traite `bytes` comme du texte à décoder
        # (et lève un DjangoUnicodeDecodeError sur du WKB binaire).
        return GEOSGeometry(memoryview(ewkb))

    @staticmethod
    def _to_geos(feature):
        """OGR -> GEOS MultiPolygon WGS84, Z aplati au niveau OGR."""
        ogr_geom = feature.geom
        if ogr_geom.coord_dim == 3:
            ogr_geom = ogr_geom.clone()
            ogr_geom.coord_dim = 2
        geom = GEOSGeometry(ogr_geom.wkb, srid=ogr_geom.srid or 2154)
        if geom.srid and geom.srid != 4326:
            geom.transform(4326)
        return geom

    # ─── Millésimes Sandre (couche nationale mono-fichier) ─────────────────

    def _import_sandre(self, shp_path: Path, millesime: str, options) -> None:
        ds = DataSource(str(shp_path))
        layer = ds[0]
        total = len(layer)
        self.stdout.write(f"{total} features dans {shp_path.name}")

        map_obj, created = get_or_create_millesime(
            name=MAP_NAME,
            version=millesime,
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
        verb = "Créé" if created else "Réutilisé"
        self.stdout.write(f"{verb} : Map id={map_obj.id} version={millesime}")

        crees = maj = sans_cle = 0
        ids_ecrits: list[int] = []

        with transaction.atomic():
            # Index construit DANS la transaction et verrouillé (cf. le même
            # motif dans `_import_2026`) : évite les doublons quand deux
            # imports se chevauchent ou qu'un précédent s'est interrompu.
            existants = {}
            for z in map_obj.zones.select_for_update().all():
                code = self._natural_key(z.attributes)
                if code and code not in existants:
                    existants[code] = z.id

            for feature in layer:
                attributes = {f: feature.get(f) for f in feature.fields}
                attributes = {
                    k: (v.isoformat() if hasattr(v, "isoformat") else v)
                    for k, v in attributes.items()
                }
                code = self._natural_key(attributes)
                if not code:
                    sans_cle += 1
                    continue

                geom = self._reparer(self._to_geos(feature))
                if geom.geom_type == "Polygon":
                    geom = MultiPolygon(geom, srid=geom.srid)

                if code in existants:
                    zone_id = existants[code]
                    Zone.objects.filter(id=zone_id).update(
                        geometry=geom, attributes=attributes
                    )
                    maj += 1
                else:
                    zone = Zone.objects.create(
                        map=map_obj, geometry=geom, attributes=attributes
                    )
                    zone_id = zone.id
                    crees += 1
                ids_ecrits.append(zone_id)

            # Prune exhaustif (cf. `_import_2026`).
            supprimes, _ = map_obj.zones.exclude(id__in=ids_ecrits).delete()

        map_obj.imported_geometries = crees + maj
        map_obj.save(update_fields=["imported_geometries"])

        resume = f"OK : {crees} créées, {maj} mises à jour, {supprimes} supprimées"
        if sans_cle:
            resume += f", {sans_cle} ignorées (sans clé naturelle)"
        self.stdout.write(self.style.SUCCESS(resume + "."))
        self._finaliser(map_obj, millesime, options)

    @staticmethod
    def _natural_key(attributes):
        if not attributes:
            return None
        for field in NATURAL_KEY_FIELDS:
            val = attributes.get(field)
            if val:
                return val
        return None

    # ─── Téléchargement ────────────────────────────────────────────────────

    def _telecharger_archive(self, url: str) -> tuple[Path, Path]:
        tmpdir = Path(tempfile.mkdtemp(prefix="nitrates_zv_"))
        zip_path = self._download(url, tmpdir)
        self.stdout.write(f"Décompression : {zip_path.name}")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmpdir)
        zip_path.unlink()
        return tmpdir, self._resoudre_racine(tmpdir)

    def _telecharger_shp(self, url: str) -> tuple[Path, Path]:
        tmpdir = Path(tempfile.mkdtemp(prefix="nitrates_zv_"))
        zip_path = self._download(url, tmpdir)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmpdir)
        zip_path.unlink()
        shps = list(tmpdir.rglob("*.shp"))
        if not shps:
            raise CommandError(f"Aucun .shp dans le zip téléchargé ({tmpdir}).")
        return tmpdir, shps[0]

    def _download(self, url: str, tmpdir: Path) -> Path:
        zip_path = tmpdir / "download.zip"
        self.stdout.write(f"Téléchargement : {url}")
        req = Request(url, headers={"User-Agent": "envergo-nitrates/1.0"})
        with urlopen(req) as resp, open(zip_path, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            while True:
                chunk = resp.read(1024 * 1024)
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
        return zip_path

    # ─── Bascule ───────────────────────────────────────────────────────────

    def _finaliser(self, map_obj, millesime: str, options) -> None:
        if options.get("no_activate"):
            self.stdout.write(
                self.style.WARNING(
                    f"--no-activate : millésime {millesime} importé mais NON "
                    f"servi. Bascule avec :\n"
                    f"  manage.py millesimes_sig --couche "
                    f'"{map_obj.name}" --activer {millesime}'
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
                    f"Millésime {millesime} ACTIF. Désactivé : {detail}. "
                    "Les zones sont conservées (rollback possible)."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"Millésime {millesime} ACTIF."))
