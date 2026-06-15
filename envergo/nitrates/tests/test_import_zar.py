"""Tests de la commande d'import ZAR (Zone d'Action Renforcée, carte #34).

On génère à la volée des shapefiles ZAR de test via fiona, en Lambert 93
(comme la source réelle), pour exercer le parcours complet : création de Map,
zones, idempotence, gestion des doublons de NOMZAR, prune.
"""

import fiona
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from fiona.crs import CRS

from envergo.geodata.models import MAP_TYPES, Map

pytestmark = pytest.mark.django_db

# Petits carrés en Lambert 93 (autour du Grand Est, coords plausibles).
_CARRE_1 = "POLYGON((900000 6900000, 901000 6900000, 901000 6901000, 900000 6901000, 900000 6900000))"
_CARRE_2 = "POLYGON((902000 6900000, 903000 6900000, 903000 6901000, 902000 6901000, 902000 6900000))"
_CARRE_3 = "POLYGON((904000 6900000, 905000 6900000, 905000 6901000, 904000 6901000, 904000 6900000))"


def _poly(wkt):
    coords = wkt.split("((")[1].rsplit("))", 1)[0]
    pts = [tuple(map(float, p.strip().split())) for p in coords.split(",")]
    return {"type": "Polygon", "coordinates": [pts]}


def make_zar_shapefile(path, features):
    """Génère un .shp Lambert 93 avec les champs ZAR (NOMZAR, etc.).

    `features` : liste de (wkt, props_dict).
    """
    schema = {
        "geometry": "Polygon",
        "properties": {
            "NOMZAR": "str",
            "NOMCOMPL": "str",
            "TYPABRG": "str",
            "CDDEPT": "str",
        },
    }
    with fiona.open(
        str(path),
        "w",
        driver="ESRI Shapefile",
        crs=CRS.from_epsg(2154),
        schema=schema,
    ) as dst:
        for wkt, props in features:
            dst.write({"geometry": _poly(wkt), "properties": props})


def _props(nom, dept="08"):
    return {
        "NOMZAR": nom,
        "NOMCOMPL": f"{nom} (complet)",
        "TYPABRG": "AAC",
        "CDDEPT": dept,
    }


# ─── Fichier manquant ───────────────────────────────────────────────────────


def test_import_zar_missing_file_raises():
    with pytest.raises(CommandError, match="introuvable"):
        call_command("import_nitrates_zar", "--file", "/does/not/exist.shp")


# ─── Création ───────────────────────────────────────────────────────────────


def test_import_zar_cree_map_et_zones(tmp_path):
    shp = tmp_path / "zar.shp"
    make_zar_shapefile(
        shp,
        [
            (_CARRE_1, _props("AAC A")),
            (_CARRE_2, _props("AAC B")),
        ],
    )
    call_command("import_nitrates_zar", "--file", str(shp))

    m = Map.objects.get(name="zar_par7_grand_est")
    assert m.map_type == MAP_TYPES.zone_action_renforcee
    assert m.zones.count() == 2
    # Géométrie reprojetée en WGS84 (geography), pas en Lambert 93.
    z = m.zones.first()
    assert z.geometry is not None


def test_import_zar_geometrie_reprojetee_wgs84(tmp_path):
    shp = tmp_path / "zar.shp"
    make_zar_shapefile(shp, [(_CARRE_1, _props("AAC A"))])
    call_command("import_nitrates_zar", "--file", str(shp))
    z = Map.objects.get(name="zar_par7_grand_est").zones.first()
    # Les coords doivent être des longitudes/latitudes (France ~ lng 4-8, lat 47-50),
    # pas des coords Lambert 93 (~900000 / 6900000).
    centroid = z.geometry.centroid
    assert -10 < centroid.x < 12
    assert 40 < centroid.y < 55


# ─── Idempotence ────────────────────────────────────────────────────────────


def test_import_zar_idempotent(tmp_path):
    shp = tmp_path / "zar.shp"
    make_zar_shapefile(shp, [(_CARRE_1, _props("AAC A")), (_CARRE_2, _props("AAC B"))])
    call_command("import_nitrates_zar", "--file", str(shp))
    call_command("import_nitrates_zar", "--file", str(shp))
    call_command("import_nitrates_zar", "--file", str(shp))
    # 3 passages -> toujours 2 zones, pas 6.
    assert Map.objects.filter(name="zar_par7_grand_est").count() == 1
    assert Map.objects.get(name="zar_par7_grand_est").zones.count() == 2


# ─── Doublon de NOMZAR (collision) ─────────────────────────────────────────


def test_import_zar_doublon_nomzar_garde_zones_distinctes(tmp_path):
    """Deux zones de même NOMZAR doivent rester distinctes (suffixe #n),
    pas être fusionnées."""
    shp = tmp_path / "zar.shp"
    make_zar_shapefile(
        shp,
        [
            (_CARRE_1, _props("PPE-Doublon")),
            (_CARRE_2, _props("PPE-Doublon")),  # même nom
            (_CARRE_3, _props("AAC Unique")),
        ],
    )
    call_command("import_nitrates_zar", "--file", str(shp))
    m = Map.objects.get(name="zar_par7_grand_est")
    # 3 zones distinctes malgré le doublon de nom.
    assert m.zones.count() == 3
    cles = sorted(z.attributes.get("_cle_naturelle") for z in m.zones.all())
    assert cles == ["AAC Unique", "PPE-Doublon", "PPE-Doublon#2"]


def test_import_zar_doublon_idempotent(tmp_path):
    """Le doublon ne doit pas casser l'idempotence : rejouer = même état."""
    shp = tmp_path / "zar.shp"
    make_zar_shapefile(
        shp,
        [(_CARRE_1, _props("PPE-Doublon")), (_CARRE_2, _props("PPE-Doublon"))],
    )
    call_command("import_nitrates_zar", "--file", str(shp))
    call_command("import_nitrates_zar", "--file", str(shp))
    assert Map.objects.get(name="zar_par7_grand_est").zones.count() == 2


# ─── Prune ──────────────────────────────────────────────────────────────────


def test_import_zar_prune_zones_disparues(tmp_path):
    shp1 = tmp_path / "zar1.shp"
    make_zar_shapefile(shp1, [(_CARRE_1, _props("AAC A")), (_CARRE_2, _props("AAC B"))])
    call_command("import_nitrates_zar", "--file", str(shp1))
    assert Map.objects.get(name="zar_par7_grand_est").zones.count() == 2

    # Nouvelle source sans AAC B -> doit être supprimée.
    shp2 = tmp_path / "zar2.shp"
    make_zar_shapefile(shp2, [(_CARRE_1, _props("AAC A"))])
    call_command("import_nitrates_zar", "--file", str(shp2))
    m = Map.objects.get(name="zar_par7_grand_est")
    assert m.zones.count() == 1
    assert m.zones.first().attributes.get("NOMZAR") == "AAC A"


# ─── GeoJSON endpoint ───────────────────────────────────────────────────────


def test_zar_geojson_endpoint(client, tmp_path):
    from django.core.cache import cache

    shp = tmp_path / "zar.shp"
    make_zar_shapefile(
        shp, [(_CARRE_1, _props("AAC A")), (_CARRE_2, _props("AAC B", dept="51"))]
    )
    call_command("import_nitrates_zar", "--file", str(shp))

    # L'endpoint est cache_page en non-DEBUG : on vide pour lire l'état courant.
    cache.clear()
    r = client.get("/geojson/zar/")
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 2
    props = data["features"][0]["properties"]
    assert "nom" in props
    assert "departement" in props


def test_zar_geojson_vide_si_pas_de_zar(client):
    from django.core.cache import cache

    cache.clear()
    r = client.get("/geojson/zar/")
    assert r.status_code == 200
    assert r.json()["features"] == []
