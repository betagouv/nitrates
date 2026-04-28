"""Tests de la vue GeoJSON ZV : sert les polygones simplifiés pour Leaflet."""

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.cache import cache
from django.urls import reverse

from envergo.geodata.models import MAP_TYPES, Map, Zone

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]


@pytest.fixture(autouse=True)
def clear_cache():
    """La vue GeoJSON est cachée 24h en prod, on vide le cache entre tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def zv_map():
    m = Map.objects.create(
        name="ZV test",
        map_type=MAP_TYPES.zv_nitrates,
        description="test",
        expected_geometries=2,
    )
    # Codes bassins fictifs (pas dans BASSIN_NAMES) pour que la vue retombe
    # sur le nom du shapefile.
    Zone.objects.create(
        map=m,
        geometry=MultiPolygon(
            Polygon(((0, 0), (1, 0), (1, 1), (0, 1), (0, 0))),
            srid=4326,
        ),
        attributes={"NomZoneVul": "ZV A", "CdEuBassin": "TEST_A"},
    )
    Zone.objects.create(
        map=m,
        geometry=MultiPolygon(
            Polygon(((2, 2), (3, 2), (3, 3), (2, 3), (2, 2))),
            srid=4326,
        ),
        attributes={"NomZoneVul": "ZV B", "CdEuBassin": "TEST_B"},
    )
    return m


def test_zv_geojson_empty_when_no_zone(client):
    resp = client.get(reverse("nitrates_zv_geojson"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert data["features"] == []


def test_zv_geojson_returns_features(client, zv_map):
    resp = client.get(reverse("nitrates_zv_geojson"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 2
    noms = sorted(f["properties"]["nom"] for f in data["features"])
    assert noms == ["ZV A", "ZV B"]


def test_zv_geojson_features_have_geometry(client, zv_map):
    resp = client.get(reverse("nitrates_zv_geojson"))
    feat = resp.json()["features"][0]
    assert feat["type"] == "Feature"
    assert feat["geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert "coordinates" in feat["geometry"]


def test_zv_geojson_only_returns_zv_type(client, zv_map):
    """Ne renvoie pas les zones d'autres map_types (ex: rpg_parcelle)."""
    rpg = Map.objects.create(
        name="RPG test",
        map_type=MAP_TYPES.rpg_parcelle,
        description="test",
        expected_geometries=1,
    )
    Zone.objects.create(
        map=rpg,
        geometry=MultiPolygon(
            Polygon(((10, 10), (11, 10), (11, 11), (10, 11), (10, 10))),
            srid=4326,
        ),
        attributes={"ID_PARCEL": "P1"},
    )
    resp = client.get(reverse("nitrates_zv_geojson"))
    data = resp.json()
    # Toujours 2 features ZV, jamais la parcelle RPG.
    assert len(data["features"]) == 2
