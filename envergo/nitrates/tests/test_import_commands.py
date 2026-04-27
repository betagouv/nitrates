"""Tests des commandes d'import ZV, RPG, départements.

On génère à la volée des petits fichiers shapefile / gpkg de test via fiona
pour tester le parcours réel (création de Map, Zone, Department, resume).
"""

import fiona
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from fiona.crs import CRS

from envergo.geodata.models import MAP_TYPES, Department, Map, Zone

pytestmark = pytest.mark.django_db


# ---------- helpers de génération de fichiers SIG de test ----------


def _polygon_to_geom(wkt_polygon: str) -> dict:
    """Parse un POLYGON WKT simple vers GeoJSON."""
    # ex: "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"
    coords_str = wkt_polygon.strip()
    coords_str = coords_str.split("((")[1].rsplit("))", 1)[0]
    points = [tuple(map(float, p.strip().split())) for p in coords_str.split(",")]
    return {"type": "Polygon", "coordinates": [points]}


def make_zv_shapefile(path, features):
    """Génère un .shp WGS84 avec les champs ZV attendus."""
    schema = {
        "geometry": "Polygon",
        "properties": {
            "CdEuZoneVu": "str",
            "NomZoneVul": "str",
            "CdEuBassin": "str",
        },
    }
    with fiona.open(
        str(path), "w", driver="ESRI Shapefile", crs=CRS.from_epsg(4326), schema=schema
    ) as dst:
        for wkt, props in features:
            dst.write(
                {
                    "geometry": _polygon_to_geom(wkt),
                    "properties": props,
                }
            )


def make_rpg_gpkg(path, features):
    """Génère un .gpkg Lambert 93 avec les champs RPG attendus."""
    schema = {
        "geometry": "Polygon",
        "properties": {
            "ID_PARCEL": "str",
            "SURF_PARC": "float",
            "CODE_CULTU": "str",
            "CODE_GROUP": "str",
        },
    }
    with fiona.open(
        str(path),
        "w",
        driver="GPKG",
        layer="PARCELLES_GRAPHIQUES",
        crs=CRS.from_epsg(2154),
        schema=schema,
    ) as dst:
        for wkt, props in features:
            dst.write(
                {
                    "geometry": _polygon_to_geom(wkt),
                    "properties": props,
                }
            )


def make_department_shp(path, departments):
    """Génère DEPARTEMENT.shp en Lambert 93 (polygones donnés en Lambert 93 direct)."""
    schema = {
        "geometry": "Polygon",
        "properties": {"INSEE_DEP": "str"},
    }
    with fiona.open(
        str(path), "w", driver="ESRI Shapefile", crs=CRS.from_epsg(2154), schema=schema
    ) as dst:
        for code, wkt in departments:
            dst.write(
                {
                    "geometry": _polygon_to_geom(wkt),
                    "properties": {"INSEE_DEP": code},
                }
            )


# ---------- tests missing file ----------


def test_import_zv_missing_file_raises():
    with pytest.raises(CommandError, match="introuvable"):
        call_command("import_nitrates_zv", "--file", "/does/not/exist.shp")


def test_import_rpg_missing_file_raises():
    with pytest.raises(CommandError, match="introuvable"):
        call_command("import_nitrates_rpg", "--file", "/does/not/exist.gpkg")


def test_import_departments_missing_file_raises():
    with pytest.raises(CommandError, match="introuvable"):
        call_command("import_nitrates_departments", "--file", "/does/not/exist.shp")


# ---------- tests import ZV ----------


def test_import_zv_creates_map_and_zones(tmp_path):
    shp = tmp_path / "zv.shp"
    make_zv_shapefile(
        shp,
        [
            (
                "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
                {"CdEuZoneVu": "FRA_1", "NomZoneVul": "ZV test 1", "CdEuBassin": "FRA"},
            ),
            (
                "POLYGON((2 2, 3 2, 3 3, 2 3, 2 2))",
                {"CdEuZoneVu": "FRB_2", "NomZoneVul": "ZV test 2", "CdEuBassin": "FRB"},
            ),
        ],
    )
    call_command("import_nitrates_zv", "--file", str(shp))

    assert Map.objects.filter(map_type=MAP_TYPES.zv_nitrates).count() == 1
    m = Map.objects.get(map_type=MAP_TYPES.zv_nitrates)
    assert m.zones.count() == 2
    names = sorted(z.attributes["NomZoneVul"] for z in m.zones.all())
    assert names == ["ZV test 1", "ZV test 2"]


def test_import_zv_is_resumable(tmp_path):
    shp = tmp_path / "zv.shp"
    make_zv_shapefile(
        shp,
        [
            (
                "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
                {"CdEuZoneVu": "FRA_1", "NomZoneVul": "ZV test", "CdEuBassin": "FRA"},
            ),
        ],
    )
    call_command("import_nitrates_zv", "--file", str(shp))
    call_command("import_nitrates_zv", "--file", str(shp))  # second run
    assert Zone.objects.filter(map__map_type=MAP_TYPES.zv_nitrates).count() == 1


# ---------- tests import départements ----------


def test_import_departments_creates_entities(tmp_path):
    shp = tmp_path / "DEPARTEMENT.shp"
    # Polygones fournis en Lambert 93 direct (ADMIN EXPRESS format)
    make_department_shp(
        shp,
        [
            (
                "51",
                "POLYGON((775000 6900000, 800000 6900000, 800000 6920000, 775000 6920000, 775000 6900000))",
            ),
            (
                "35",
                "POLYGON((330000 6780000, 360000 6780000, 360000 6800000, 330000 6800000, 330000 6780000))",
            ),
        ],
    )
    call_command("import_nitrates_departments", "--file", str(shp))

    assert Department.objects.count() == 2
    codes = sorted(Department.objects.values_list("department", flat=True))
    assert codes == ["35", "51"]
    for d in Department.objects.all():
        assert d.geometry is not None


def test_import_departments_is_idempotent(tmp_path):
    shp = tmp_path / "DEPARTEMENT.shp"
    make_department_shp(
        shp,
        [
            (
                "51",
                "POLYGON((775000 6900000, 800000 6900000, 800000 6920000, 775000 6920000, 775000 6900000))",
            )
        ],
    )
    call_command("import_nitrates_departments", "--file", str(shp))
    call_command("import_nitrates_departments", "--file", str(shp))
    assert Department.objects.count() == 1


# ---------- tests import RPG ----------


def test_import_rpg_creates_map_and_zones(tmp_path):
    gpkg = tmp_path / "rpg.gpkg"
    # Coordonnées en Lambert 93
    make_rpg_gpkg(
        gpkg,
        [
            (
                "POLYGON((775000 6908000, 775100 6908000, 775100 6908100, 775000 6908100, 775000 6908000))",
                {
                    "ID_PARCEL": "P001",
                    "CODE_CULTU": "BTH",
                    "CODE_GROUP": "1",
                    "SURF_PARC": 1.0,
                },
            ),
            (
                "POLYGON((775200 6908200, 775300 6908200, 775300 6908300, 775200 6908300, 775200 6908200))",
                {
                    "ID_PARCEL": "P002",
                    "CODE_CULTU": "MIS",
                    "CODE_GROUP": "2",
                    "SURF_PARC": 2.0,
                },
            ),
        ],
    )
    call_command("import_nitrates_rpg", "--file", str(gpkg), "--millesime", "2023")

    m = Map.objects.get(map_type=MAP_TYPES.rpg_parcelle)
    assert m.zones.count() == 2
    codes = sorted(z.attributes["CODE_CULTU"] for z in m.zones.all())
    assert codes == ["BTH", "MIS"]


def test_import_rpg_filter_by_department(tmp_path):
    """Seules les parcelles qui intersectent le dept demandé sont importées."""
    dept_shp = tmp_path / "DEPARTEMENT.shp"
    # Département "51" avec bbox autour de Reims
    make_department_shp(
        dept_shp,
        [
            (
                "51",
                "POLYGON((770000 6900000, 800000 6900000, 800000 6920000, 770000 6920000, 770000 6900000))",
            )
        ],
    )
    call_command("import_nitrates_departments", "--file", str(dept_shp))

    gpkg = tmp_path / "rpg.gpkg"
    # P_IN dans le département 51, P_OUT loin (Bretagne)
    make_rpg_gpkg(
        gpkg,
        [
            (
                "POLYGON((775000 6908000, 775100 6908000, 775100 6908100, 775000 6908100, 775000 6908000))",
                {
                    "ID_PARCEL": "IN_51",
                    "CODE_CULTU": "BTH",
                    "CODE_GROUP": "1",
                    "SURF_PARC": 1.0,
                },
            ),
            (
                "POLYGON((340000 6790000, 340100 6790000, 340100 6790100, 340000 6790100, 340000 6790000))",
                {
                    "ID_PARCEL": "OUT_35",
                    "CODE_CULTU": "MIS",
                    "CODE_GROUP": "2",
                    "SURF_PARC": 2.0,
                },
            ),
        ],
    )
    call_command(
        "import_nitrates_rpg",
        "--file",
        str(gpkg),
        "--millesime",
        "2023",
        "--departments",
        "51",
    )

    m = Map.objects.get(map_type=MAP_TYPES.rpg_parcelle)
    parcels = list(m.zones.all())
    assert len(parcels) == 1
    assert parcels[0].attributes["ID_PARCEL"] == "IN_51"


def test_import_rpg_filter_missing_department_raises(tmp_path):
    gpkg = tmp_path / "rpg.gpkg"
    make_rpg_gpkg(
        gpkg,
        [
            (
                "POLYGON((775000 6908000, 775100 6908000, 775100 6908100, 775000 6908100, 775000 6908000))",
                {
                    "ID_PARCEL": "P1",
                    "CODE_CULTU": "BTH",
                    "CODE_GROUP": "1",
                    "SURF_PARC": 1.0,
                },
            ),
        ],
    )
    with pytest.raises(CommandError, match="Départements introuvables"):
        call_command(
            "import_nitrates_rpg",
            "--file",
            str(gpkg),
            "--departments",
            "99",
        )
