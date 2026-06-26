"""Tests de la resolution dynamique d'arbre (select_active_tree).

Coeur du LOT 1a : etant donne un catalog geographique, on retient l'arbre
actif le plus specifique (poids max) parmi PAN / PAR / ZAR.
"""

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon

from envergo.geodata.models import MAP_TYPES, Map, Zone
from envergo.nitrates.models import DecisionTree
from envergo.nitrates.yaml_tree import select_active_tree

pytestmark = pytest.mark.django_db


def _tree(name, scope, *, weight, region_code="", activation_map=None):
    return DecisionTree.objects.create(
        name=name,
        status=DecisionTree.STATUS_ACTIVE,
        scope=scope,
        region_code=region_code,
        activation_map=activation_map,
        weight=weight,
        contenu={"arbre": {"noeud": {"id": f"n_{name}"}}},
    )


@pytest.fixture(autouse=True)
def _purge():
    """La migration data cree un PAN au 1er migrate -> on purge."""
    DecisionTree.objects.all().delete()


@pytest.fixture
def zar_map(db):
    """Une couche ZAR avec une zone geometrique connue (bbox Grand Est)."""
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


@pytest.fixture
def trois_arbres(zar_map):
    """PAN (w1) + PAR Grand Est (w10) + ZAR Grand Est (w20)."""
    pan = _tree("pan", DecisionTree.SCOPE_NATIONAL, weight=1)
    par = _tree("par_ge", DecisionTree.SCOPE_REGION, weight=10, region_code="44")
    zar = _tree(
        "zar_ge",
        DecisionTree.SCOPE_ZAR,
        weight=20,
        region_code="44",
        activation_map=zar_map,
    )
    zar_zone_id = zar_map.zones.first().id
    return {"pan": pan, "par": par, "zar": zar, "zar_zone_id": zar_zone_id}


def _contenu_id(contenu) -> str:
    return contenu["arbre"]["noeud"]["id"]


def test_grand_est_en_zar_retourne_zar(trois_arbres):
    catalog = {"region_code": "44", "zar_zone_id": trois_arbres["zar_zone_id"]}
    assert _contenu_id(select_active_tree(catalog)) == "n_zar_ge"


def test_grand_est_hors_zar_retourne_par(trois_arbres):
    catalog = {"region_code": "44", "zar_zone_id": None}
    assert _contenu_id(select_active_tree(catalog)) == "n_par_ge"


def test_hors_grand_est_retourne_pan(trois_arbres):
    catalog = {"region_code": "32", "zar_zone_id": None}
    assert _contenu_id(select_active_tree(catalog)) == "n_pan"


def test_region_inconnue_retourne_pan(trois_arbres):
    catalog = {"region_code": None, "zar_zone_id": None}
    assert _contenu_id(select_active_tree(catalog)) == "n_pan"


def test_poids_max_gagne(trois_arbres):
    """ZAR et PAR matchent simultanement (R44 + zar) -> ZAR (w20 > w10)."""
    catalog = {"region_code": "44", "zar_zone_id": trois_arbres["zar_zone_id"]}
    assert _contenu_id(select_active_tree(catalog)) == "n_zar_ge"


def test_pan_absent_leve_doesnotexist():
    """Aucun arbre national actif -> DoesNotExist (filet de securite)."""
    _tree("par_seul", DecisionTree.SCOPE_REGION, weight=10, region_code="44")
    with pytest.raises(DecisionTree.DoesNotExist):
        select_active_tree({"region_code": "32", "zar_zone_id": None})


def test_seul_pan_actif_retourne_pan():
    """Cas nominal actuel (un seul PAN) : select retourne le PAN."""
    _tree("pan", DecisionTree.SCOPE_NATIONAL, weight=1)
    assert _contenu_id(select_active_tree({"region_code": "44"})) == "n_pan"
