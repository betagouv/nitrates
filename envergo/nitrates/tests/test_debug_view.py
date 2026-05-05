"""Tests de la vue debug : résout dept/région/ZV depuis un point.

Le RPG a été retiré de cet endpoint en 0.0.3 (la zone d'activation
utilise désormais le cadastre IGN, résolu côté front au clic carte).
"""

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.urls import reverse

from envergo.geodata.models import MAP_TYPES, Department, Map, Zone

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]


@pytest.fixture
def marne_department():
    """Département 51 (Grand Est — R44) avec un polygone autour de Reims."""
    geom = MultiPolygon(
        Polygon(((3.5, 48.5), (5.0, 48.5), (5.0, 49.5), (3.5, 49.5), (3.5, 48.5))),
        srid=4326,
    )
    return Department.objects.create(department="51", geometry=geom)


@pytest.fixture
def zv_map(marne_department):
    """Map ZV avec un gros polygone qui couvre toute la Marne."""
    m = Map.objects.create(
        name="ZV test",
        map_type=MAP_TYPES.zv_nitrates,
        description="test",
        expected_geometries=1,
    )
    Zone.objects.create(
        map=m,
        geometry=MultiPolygon(
            Polygon(((3.5, 48.5), (5.0, 48.5), (5.0, 49.5), (3.5, 49.5), (3.5, 48.5))),
            srid=4326,
        ),
        attributes={
            "NomZoneVul": "ZV Seine-Normandie",
            "CdEuBassin": "FRH",
        },
    )
    return m


def test_debug_requires_lng_lat(client):
    resp = client.get(reverse("nitrates_debug"))
    assert resp.status_code == 400


def test_debug_invalid_coords(client):
    resp = client.get(reverse("nitrates_debug"), {"lng": "abc", "lat": "xyz"})
    assert resp.status_code == 400


def test_debug_point_in_marne_resolves_department_and_region(client, marne_department):
    resp = client.get(reverse("nitrates_debug"), {"lng": 4.0, "lat": 49.2})
    assert resp.status_code == 200
    data = resp.json()
    assert data["department_code"] == "51"
    assert data["region_code"] == "44"
    assert "Grand" in data["region_label"]
    assert data["en_zone_vulnerable"] is False


def test_debug_point_in_zv(client, marne_department, zv_map):
    resp = client.get(reverse("nitrates_debug"), {"lng": 4.0, "lat": 49.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["en_zone_vulnerable"] is True
    # Le nom officiel du bassin FRH écrase ce que le shapefile contient
    assert data["zv_info"]["nom"] == "Seine-Normandie"
    assert data["zv_info"]["bassin"] == "FRH"


def test_debug_point_outside_everything(client):
    """Point dans l'Atlantique, pas de dept, pas de ZV."""
    resp = client.get(reverse("nitrates_debug"), {"lng": -10.0, "lat": 45.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["department_code"] is None
    assert data["region_code"] is None
    assert data["en_zone_vulnerable"] is False


def test_debug_response_does_not_include_rpg_parcelle(client, marne_department):
    """Le RPG a été retiré du payload en 0.0.3 (sera remonté côté front
    via l'API IGN cadastre). Si quelqu'un le réintroduit, ce test
    signale qu'il faut adapter le contrat avec le frontend."""
    resp = client.get(reverse("nitrates_debug"), {"lng": 4.0, "lat": 49.2})
    assert "rpg_parcelle" not in resp.json()
