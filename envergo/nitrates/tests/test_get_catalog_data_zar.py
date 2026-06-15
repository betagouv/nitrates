"""Tests du contexte ZAR injecte par MoulinetteNitrates.get_catalog_data."""

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon

from envergo.geodata.models import MAP_TYPES, Map, Zone
from envergo.nitrates.models import MoulinetteNitrates

pytestmark = pytest.mark.django_db

# Reims (dans la bbox ZAR ci-dessous) / large hors zone.
LNG_REIMS, LAT_REIMS = 4.0345, 49.2583
LNG_OFFSHORE, LAT_OFFSHORE = -30.0, 30.0


@pytest.fixture
def zar_map(db):
    m = Map.objects.create(
        name="zar_test",
        map_type=MAP_TYPES.zone_action_renforcee,
        description="test",
    )
    Zone.objects.create(
        map=m,
        geometry=MultiPolygon(Polygon.from_bbox((3.5, 48.7, 5.0, 49.7))),
    )
    return m


def test_catalog_en_zar_si_dans_zone(zar_map):
    moulinette = MoulinetteNitrates(
        form_kwargs={"data": {"lng": LNG_REIMS, "lat": LAT_REIMS}}
    )
    assert moulinette.catalog["en_zar"] is True
    assert moulinette.catalog["zar_zone_id"] == zar_map.zones.first().id


def test_catalog_hors_zar_si_hors_zone(zar_map):
    moulinette = MoulinetteNitrates(
        form_kwargs={"data": {"lng": LNG_OFFSHORE, "lat": LAT_OFFSHORE}}
    )
    assert moulinette.catalog["en_zar"] is False
    assert moulinette.catalog["zar_zone_id"] is None


def test_catalog_sans_couche_zar_renvoie_false(db):
    """Aucune couche ZAR en base : en_zar=False, pas de crash."""
    moulinette = MoulinetteNitrates(
        form_kwargs={"data": {"lng": LNG_REIMS, "lat": LAT_REIMS}}
    )
    assert moulinette.catalog["en_zar"] is False
    assert moulinette.catalog["zar_zone_id"] is None
