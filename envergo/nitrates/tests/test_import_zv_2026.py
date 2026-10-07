"""Tests du millésime 2026 (livraisons DREAL par bassin) de `import_nitrates_zv`.

On fabrique l'arborescence attendue (`BASSINS_2026`) avec des petits fichiers
GPKG/Shapefile générés à la volée via fiona, en Lambert 93 (comme les
livraisons réelles), pour exercer le parcours complet : contrôle d'archive
complète, lecture par bassin (filtre `where`, fusion), réparation de
géométrie, versioning/bascule, téléchargement (mocké), résolution de racine.
"""

import io
import zipfile

import fiona
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from fiona.crs import CRS

from envergo.geodata.models import MAP_TYPES, Map
from envergo.nitrates.management.commands import import_nitrates_zv

pytestmark = pytest.mark.django_db

_CARRE_1 = "POLYGON((600000 6900000, 601000 6900000, 601000 6901000, 600000 6901000, 600000 6900000))"
_CARRE_2 = "POLYGON((602000 6900000, 603000 6900000, 603000 6901000, 602000 6901000, 602000 6900000))"
_CARRE_3 = "POLYGON((604000 6900000, 605000 6900000, 605000 6901000, 604000 6901000, 604000 6900000))"


def _poly(wkt):
    coords = wkt.split("((")[1].rsplit("))", 1)[0]
    pts = [tuple(map(float, p.strip().split())) for p in coords.split(",")]
    return {"type": "Polygon", "coordinates": [pts]}


def _write(path, driver, features, fields, layer=None, crs_epsg=2154):
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = {"geometry": "Polygon", "properties": fields}
    kwargs = {}
    if layer:
        kwargs["layer"] = layer
    with fiona.open(
        str(path),
        "w",
        driver=driver,
        crs=CRS.from_epsg(crs_epsg),
        schema=schema,
        **kwargs
    ) as dst:
        for wkt, props in features:
            dst.write({"geometry": _poly(wkt), "properties": props})


def build_dossier_2026(root, rhin_meuse_ok=True, loire_bretagne_ok=True):
    """Construit l'arborescence complète attendue par `BASSINS_2026`."""
    _write(
        root / "ZV_AdourGaronne_2026/zonevuln_délimitation_EU.gpkg",
        "GPKG",
        [(_CARRE_1, {"CdEuZoneVu": "x"})],
        {"CdEuZoneVu": "str"},
        layer="zv",
    )
    _write(
        root / "ZV_ArtoisPicardie_2026/ZoneVuln_designation_FRA_2026.gpkg",
        "GPKG",
        [(_CARRE_2, {"CdEuZoneVu": "x"})],
        {"CdEuZoneVu": "str"},
        layer="zv",
    )
    _write(
        root / "ZV_ArtoisPicardie_2026/ZoneVuln_designation_FRB2_2026.gpkg",
        "GPKG",
        [(_CARRE_3, {"CdEuZoneVu": "x"})],
        {"CdEuZoneVu": "str"},
        layer="zv",
    )
    if loire_bretagne_ok:
        _write(
            root
            / "ZV_LoireBretagne_2026/dataset/zonevuln2026_delimitation_FRG_RGF93.shp",
            "ESRI Shapefile",
            [
                (_CARRE_1, {"CdEuZoneVu": "FRG_ZV_2026_1"}),
                (_CARRE_2, {"CdEuZoneVu": "FRG_ZV_2026_2"}),
            ],
            {"CdEuZoneVu": "str"},
        )
    if rhin_meuse_ok:
        _write(
            root / "ZV_RhinMeuse_2026/ZV-RM-2026-bloc-v2.shp",
            "ESRI Shapefile",
            [(_CARRE_3, {"CdEuZoneVu": "x"})],
            {"CdEuZoneVu": "str"},
        )
    _write(
        root / "ZV_RhoneMed_2026/ZV2026_CommunesClasséesEtSectionsCadastrales_VF.shp",
        "ESRI Shapefile",
        [(_CARRE_1, {"CdEuZoneVu": "a"}), (_CARRE_2, {"CdEuZoneVu": "b"})],
        {"CdEuZoneVu": "str"},
    )
    _write(
        root
        / "ZV_SeineNormandie_2026/Couche SIG Limites communales/ZV_DIV_COM_FRH_2026.shp",
        "ESRI Shapefile",
        [(_CARRE_1, {"CdEuZoneVu": "a"}), (_CARRE_2, {"CdEuZoneVu": "b"})],
        {"CdEuZoneVu": "str"},
    )


# ─── Contrôle d'archive complète ───────────────────────────────────────────


def test_import_2026_dossier_introuvable(tmp_path):
    with pytest.raises(CommandError, match="Dossier introuvable"):
        call_command(
            "import_nitrates_zv",
            "--dossier",
            str(tmp_path / "nope"),
            "--millesime",
            "2026",
        )


def test_import_2026_fichiers_manquants_refuse(tmp_path):
    build_dossier_2026(tmp_path, rhin_meuse_ok=False)
    # Contrôle préalable, avant toute écriture : pas de millésime 2026 créé.
    with pytest.raises(CommandError, match="Fichiers absents"):
        call_command(
            "import_nitrates_zv", "--dossier", str(tmp_path), "--millesime", "2026"
        )
    assert not Map.objects.filter(
        name=import_nitrates_zv.MAP_NAME, version="2026"
    ).exists()


# ─── Import complet, filtre `where`, fusion ────────────────────────────────


def test_import_2026_cree_une_zone_par_bassin(tmp_path):
    build_dossier_2026(tmp_path)
    call_command(
        "import_nitrates_zv", "--dossier", str(tmp_path), "--millesime", "2026"
    )

    m = Map.objects.get(name=import_nitrates_zv.MAP_NAME, version="2026")
    assert m.map_type == MAP_TYPES.zv_nitrates
    assert m.is_active is True
    assert m.zones.count() == 7
    bassins = sorted(z.attributes["CdEuBassin"] for z in m.zones.all())
    assert bassins == sorted(b["bassin"] for b in import_nitrates_zv.BASSINS_2026)


def test_import_2026_filtre_where_loire_bretagne(tmp_path):
    """Seule la feature `FRG_ZV_2026_2` (désignation) doit être retenue."""
    build_dossier_2026(tmp_path)
    call_command(
        "import_nitrates_zv", "--dossier", str(tmp_path), "--millesime", "2026"
    )
    m = Map.objects.get(name=import_nitrates_zv.MAP_NAME, version="2026")
    frg = m.zones.get(attributes__CdEuBassin="FRG")
    assert frg.attributes["nb_features_source"] == 1


def test_import_2026_fusionne_les_mailles_rhone_mediterranee(tmp_path):
    build_dossier_2026(tmp_path)
    call_command(
        "import_nitrates_zv", "--dossier", str(tmp_path), "--millesime", "2026"
    )
    m = Map.objects.get(name=import_nitrates_zv.MAP_NAME, version="2026")
    frd = m.zones.get(attributes__CdEuBassin="FRD")
    assert frd.attributes["fusionne"] is True
    assert frd.attributes["nb_features_source"] == 2


def test_import_2026_no_activate_laisse_inactif(tmp_path):
    build_dossier_2026(tmp_path)
    call_command(
        "import_nitrates_zv",
        "--dossier",
        str(tmp_path),
        "--millesime",
        "2026",
        "--no-activate",
    )
    m = Map.objects.get(name=import_nitrates_zv.MAP_NAME, version="2026")
    assert m.is_active is False


def test_import_2026_bascule_desactive_ancien_millesime(tmp_path, capsys):
    ancienne = Map.objects.create(
        name=import_nitrates_zv.MAP_NAME,
        version="2021",
        map_type=MAP_TYPES.zv_nitrates,
        is_active=True,
    )
    build_dossier_2026(tmp_path)
    call_command(
        "import_nitrates_zv", "--dossier", str(tmp_path), "--millesime", "2026"
    )

    ancienne.refresh_from_db()
    assert ancienne.is_active is False
    nouvelle = Map.objects.get(name=import_nitrates_zv.MAP_NAME, version="2026")
    assert nouvelle.is_active is True
    assert "ACTIF" in capsys.readouterr().out


# ─── Idempotence et prune ───────────────────────────────────────────────────


def test_import_2026_est_idempotent(tmp_path):
    build_dossier_2026(tmp_path)
    call_command(
        "import_nitrates_zv", "--dossier", str(tmp_path), "--millesime", "2026"
    )
    call_command(
        "import_nitrates_zv", "--dossier", str(tmp_path), "--millesime", "2026"
    )
    assert (
        Map.objects.filter(name=import_nitrates_zv.MAP_NAME, version="2026").count()
        == 1
    )
    assert (
        Map.objects.get(name=import_nitrates_zv.MAP_NAME, version="2026").zones.count()
        == 7
    )


def test_import_2026_prune_zone_orpheline(tmp_path, capsys):
    build_dossier_2026(tmp_path)
    call_command(
        "import_nitrates_zv", "--dossier", str(tmp_path), "--millesime", "2026"
    )
    m = Map.objects.get(name=import_nitrates_zv.MAP_NAME, version="2026")

    # Zone orpheline (doublon d'un import précédent interrompu, par ex.) :
    # un code bassin qui n'existe plus dans le registre.
    from envergo.geodata.models import Zone

    Zone.objects.create(
        map=m, geometry=m.zones.first().geometry, attributes={"CdEuBassin": "ZZZ"}
    )
    assert m.zones.count() == 8

    call_command(
        "import_nitrates_zv", "--dossier", str(tmp_path), "--millesime", "2026"
    )
    m.refresh_from_db()
    assert m.zones.count() == 7
    assert "obsolète" in capsys.readouterr().out


# ─── Résolution de racine ───────────────────────────────────────────────────


def test_resoudre_racine_pointe_directement():
    cmd = import_nitrates_zv.Command()
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "ZV_AdourGaronne_2026").mkdir()
        assert cmd._resoudre_racine(root) == root


def test_resoudre_racine_descend_dans_le_sous_dossier_couches(tmp_path):
    cmd = import_nitrates_zv.Command()
    sous = tmp_path / "couches SIG ZV 2026"
    (sous / "ZV_AdourGaronne_2026").mkdir(parents=True)
    assert cmd._resoudre_racine(tmp_path) == sous


def test_resoudre_racine_ambigue_retourne_le_dossier_tel_quel(tmp_path):
    cmd = import_nitrates_zv.Command()
    (tmp_path / "autre_chose").mkdir()
    assert cmd._resoudre_racine(tmp_path) == tmp_path


# ─── Téléchargement (mocké, jamais de vrai réseau) ──────────────────────────


class _FakeResponse:
    def __init__(self, data: bytes):
        self._data = data
        self._offset = 0
        self.headers = {"Content-Length": str(len(data))}

    def read(self, n=-1):
        if n is None or n < 0:
            debut = self._offset
            chunk = self._data[debut:]
        else:
            debut, fin = self._offset, self._offset + n
            chunk = self._data[debut:fin]
        self._offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _zip_bytes(root):
    """Zippe récursivement `root` et renvoie les bytes de l'archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in root.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(root))
    return buf.getvalue()


def test_import_2026_telecharge_et_decompresse_l_archive(tmp_path, monkeypatch):
    source = tmp_path / "src"
    build_dossier_2026(source)
    data = _zip_bytes(source)

    monkeypatch.setattr(import_nitrates_zv, "urlopen", lambda req: _FakeResponse(data))

    call_command(
        "import_nitrates_zv",
        "--url",
        "https://example.invalid/zv.zip",
        "--millesime",
        "2026",
    )
    m = Map.objects.get(name=import_nitrates_zv.MAP_NAME, version="2026")
    assert m.zones.count() == 7


def test_import_sandre_telecharge_et_decompresse_le_shp(tmp_path, monkeypatch):
    from envergo.nitrates.tests.test_import_commands import make_zv_shapefile_eu

    shp = tmp_path / "zv.shp"
    make_zv_shapefile_eu(
        shp,
        [(_CARRE_1, {"name": "zone a", "inspireid": "FR.ZV.1"})],
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in shp.parent.glob("zv.*"):
            zf.write(p, p.name)
    data = buf.getvalue()

    monkeypatch.setattr(import_nitrates_zv, "urlopen", lambda req: _FakeResponse(data))

    call_command(
        "import_nitrates_zv",
        "--url",
        "https://example.invalid/sandre.zip",
        "--millesime",
        "2021",
    )
    m = Map.objects.get(name=import_nitrates_zv.MAP_NAME, version="2021")
    assert m.zones.count() == 1


def test_import_sandre_telechargement_sans_shp_echoue(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "pas de shp ici")
    monkeypatch.setattr(
        import_nitrates_zv, "urlopen", lambda req: _FakeResponse(buf.getvalue())
    )
    with pytest.raises(CommandError, match="Aucun .shp"):
        call_command(
            "import_nitrates_zv",
            "--url",
            "https://example.invalid/sandre.zip",
            "--millesime",
            "2021",
        )
