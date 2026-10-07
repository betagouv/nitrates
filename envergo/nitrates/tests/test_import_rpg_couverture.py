"""Tests complémentaires de `import_nitrates_rpg` : reprise (resumable),
import partiel/purge, filtre géométrique négatif, feature en erreur ignorée.
"""

import pytest
from django.core.management import call_command

from envergo.geodata.models import MAP_TYPES, Map
from envergo.nitrates.management.commands import import_nitrates_rpg
from envergo.nitrates.tests.test_import_commands import (
    make_department_shp,
    make_rpg_gpkg,
)

pytestmark = pytest.mark.django_db


def _dept_l_shape(path):
    """Département en forme de L : la bbox a un coin que le polygone ne couvre pas."""
    make_department_shp(
        path,
        [
            (
                "51",
                "POLYGON(("
                "770000 6900000, 790000 6900000, 790000 6910000, "
                "780000 6910000, 780000 6920000, 770000 6920000, 770000 6900000"
                "))",
            )
        ],
    )


def test_rpg_skip_si_deja_importe(tmp_path, capsys):
    _dept_l_shape(tmp_path / "DEPARTEMENT.shp")
    call_command(
        "import_nitrates_departments", "--file", str(tmp_path / "DEPARTEMENT.shp")
    )

    gpkg = tmp_path / "rpg.gpkg"
    make_rpg_gpkg(
        gpkg,
        [
            (
                "POLYGON((775000 6905000, 775100 6905000, 775100 6905100, 775000 6905100, 775000 6905000))",
                {
                    "ID_PARCEL": "P1",
                    "CODE_CULTU": "BTH",
                    "CODE_GROUP": "1",
                    "SURF_PARC": 1.0,
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
    assert m.zones.count() == 1

    call_command(
        "import_nitrates_rpg",
        "--file",
        str(gpkg),
        "--millesime",
        "2023",
        "--departments",
        "51",
    )
    assert "déjà importé" in capsys.readouterr().out
    m.refresh_from_db()
    assert m.zones.count() == 1


def test_rpg_import_partiel_est_purge_et_repris(tmp_path, capsys):
    _dept_l_shape(tmp_path / "DEPARTEMENT.shp")
    call_command(
        "import_nitrates_departments", "--file", str(tmp_path / "DEPARTEMENT.shp")
    )

    gpkg = tmp_path / "rpg.gpkg"
    make_rpg_gpkg(
        gpkg,
        [
            (
                "POLYGON((775000 6905000, 775100 6905000, 775100 6905100, 775000 6905100, 775000 6905000))",
                {
                    "ID_PARCEL": "P1",
                    "CODE_CULTU": "BTH",
                    "CODE_GROUP": "1",
                    "SURF_PARC": 1.0,
                },
            ),
            (
                "POLYGON((776000 6906000, 776100 6906000, 776100 6906100, 776000 6906100, 776000 6906000))",
                {
                    "ID_PARCEL": "P2",
                    "CODE_CULTU": "MIS",
                    "CODE_GROUP": "2",
                    "SURF_PARC": 1.0,
                },
            ),
            (
                "POLYGON((777000 6907000, 777100 6907000, 777100 6907100, 777000 6907100, 777000 6907000))",
                {
                    "ID_PARCEL": "P3",
                    "CODE_CULTU": "MIS",
                    "CODE_GROUP": "2",
                    "SURF_PARC": 1.0,
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
    assert m.zones.count() == 3
    capsys.readouterr()

    # On simule un import interrompu : une seule des trois zones reste
    # (int(0.95*3) == 2, donc 1 zone ne déclenche pas le skip "déjà importé").
    m.zones.exclude(attributes__ID_PARCEL="P1").delete()
    assert m.zones.count() == 1

    call_command(
        "import_nitrates_rpg",
        "--file",
        str(gpkg),
        "--millesime",
        "2023",
        "--departments",
        "51",
    )
    out = capsys.readouterr().out
    assert "import partiel détecté" in out
    m.refresh_from_db()
    assert m.zones.count() == 3


def test_rpg_filtre_geometrique_exclut_hors_polygone(tmp_path):
    """Une parcelle dans la bbox du département mais hors du polygone (le
    « creux » du L) ne doit pas être importée."""
    dept_path = tmp_path / "DEPARTEMENT.shp"
    _dept_l_shape(dept_path)
    call_command("import_nitrates_departments", "--file", str(dept_path))

    gpkg = tmp_path / "rpg.gpkg"
    make_rpg_gpkg(
        gpkg,
        [
            (
                # Dans la bbox (770000-790000, 6900000-6920000) mais dans le
                # creux du L (x>780000, y>6910000) -> hors polygone.
                "POLYGON((782000 6912000, 783000 6912000, 783000 6913000, 782000 6913000, 782000 6912000))",
                {
                    "ID_PARCEL": "HORS",
                    "CODE_CULTU": "MIS",
                    "CODE_GROUP": "2",
                    "SURF_PARC": 1.0,
                },
            ),
            (
                "POLYGON((775000 6905000, 775100 6905000, 775100 6905100, 775000 6905100, 775000 6905000))",
                {
                    "ID_PARCEL": "DANS",
                    "CODE_CULTU": "BTH",
                    "CODE_GROUP": "1",
                    "SURF_PARC": 1.0,
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
    ids = sorted(z.attributes["ID_PARCEL"] for z in m.zones.all())
    assert ids == ["DANS"]


def test_rpg_feature_en_erreur_est_ignoree_sans_planter(tmp_path, monkeypatch):
    """Une feature dont la géométrie fait planter GEOSGeometry est juste
    loggée en stderr et sautée ; les autres sont importées normalement."""
    gpkg = tmp_path / "rpg.gpkg"
    make_rpg_gpkg(
        gpkg,
        [
            (
                "POLYGON((775000 6908000, 775100 6908000, 775100 6908100, 775000 6908100, 775000 6908000))",
                {
                    "ID_PARCEL": "BAD",
                    "CODE_CULTU": "BTH",
                    "CODE_GROUP": "1",
                    "SURF_PARC": 1.0,
                },
            ),
            (
                "POLYGON((775200 6908200, 775300 6908200, 775300 6908300, 775200 6908300, 775200 6908200))",
                {
                    "ID_PARCEL": "OK",
                    "CODE_CULTU": "MIS",
                    "CODE_GROUP": "2",
                    "SURF_PARC": 1.0,
                },
            ),
        ],
    )

    real_geos = import_nitrates_rpg.GEOSGeometry
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("géométrie corrompue (test)")
        return real_geos(*args, **kwargs)

    monkeypatch.setattr(import_nitrates_rpg, "GEOSGeometry", flaky)

    call_command("import_nitrates_rpg", "--file", str(gpkg), "--millesime", "2023")
    m = Map.objects.get(map_type=MAP_TYPES.rpg_parcelle)
    assert m.zones.count() == 1
    assert m.zones.first().attributes["ID_PARCEL"] == "OK"
