"""Tests de la MoulinetteNitrates : instanciation, catalog, regulations."""

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon

from envergo.geodata.models import MAP_TYPES, Department, Map, Zone
from envergo.moulinette.models import Criterion, Regulation
from envergo.nitrates.models import MoulinetteNitrates

# Reims : 4.0345, 49.2583
LNG_REIMS = 4.0345
LAT_REIMS = 49.2583
# Quelque part en mer atlantique loin de la France (-30, 30)
LNG_OFFSHORE = -30.0
LAT_OFFSHORE = 30.0


@pytest.fixture
def department_marne(db):
    """Polygone simple autour de Reims qui couvre 51."""
    return Department.objects.create(
        department="51",
        geometry=MultiPolygon(Polygon.from_bbox((3.5, 48.7, 5.0, 49.7))),
    )


@pytest.fixture
def zv_map(db):
    """Map ZV avec une zone qui couvre Reims. La migration data 0002 cree
    deja cette map en prod, mais en test pytest-django reset les donnees
    entre runs sans rejouer les migrations data -- on get_or_create donc.
    Idem pour Regulation+Criterion : si la migration n'a pas tourne, on
    les recree pour que la moulinette les retrouve."""
    m, _ = Map.objects.get_or_create(
        map_type=MAP_TYPES.zv_nitrates,
        defaults={"name": "ZV test", "description": "test"},
    )
    Zone.objects.create(
        map=m,
        geometry=MultiPolygon(Polygon.from_bbox((3.5, 48.7, 5.0, 49.7))),
        attributes={"CdEuBassin": "FRB1", "NomZoneVul": "Test"},
    )
    regulation, _ = Regulation.objects.get_or_create(
        regulation="directive_nitrates",
        defaults={
            "evaluator": (
                "envergo.nitrates.regulations.directive_nitrates."
                "DirectiveNitratesEvaluator"
            ),
        },
    )
    Criterion.objects.get_or_create(
        regulation=regulation,
        evaluator=(
            "envergo.nitrates.regulations.arbre_decision." "ArbreDecisionEvaluator"
        ),
        defaults={
            "backend_title": "Arbre de decision PAN",
            "title": "Periodes d'epandage azote",
            "activation_map": m,
        },
    )
    return m


# ─── Instanciation ─────────────────────────────────────────────────────────


def test_moulinette_s_instancie_avec_lat_lng(department_marne, zv_map):
    moulinette = MoulinetteNitrates(
        form_kwargs={"data": {"lng": LNG_REIMS, "lat": LAT_REIMS}}
    )
    assert moulinette.is_evaluated()


def test_catalog_contient_point_dept_region(department_marne, zv_map):
    moulinette = MoulinetteNitrates(
        form_kwargs={"data": {"lng": LNG_REIMS, "lat": LAT_REIMS}}
    )
    assert moulinette.catalog["lng_lat"].x == pytest.approx(LNG_REIMS)
    assert moulinette.catalog["lng_lat"].y == pytest.approx(LAT_REIMS)
    assert moulinette.catalog["department_code"] == "51"
    assert moulinette.catalog["region_code"] == "44"
    assert moulinette.catalog["region_label"] == "Grand Est"


def test_catalog_resout_zv_si_dans_zone(department_marne, zv_map):
    moulinette = MoulinetteNitrates(
        form_kwargs={"data": {"lng": LNG_REIMS, "lat": LAT_REIMS}}
    )
    assert moulinette.catalog["en_zone_vulnerable"] is True
    assert moulinette.catalog["bassin"] == "FRB1"


def test_catalog_resout_hors_zv_si_hors_zone(zv_map):
    moulinette = MoulinetteNitrates(
        form_kwargs={"data": {"lng": LNG_OFFSHORE, "lat": LAT_OFFSHORE}}
    )
    assert moulinette.catalog["en_zone_vulnerable"] is False
    assert moulinette.catalog["bassin"] is None


def test_catalog_sans_zv_map_renvoie_false(db):
    """Aucune zone ZV intersectant le point : en_zone_vulnerable=False."""
    moulinette = MoulinetteNitrates(
        form_kwargs={"data": {"lng": LNG_REIMS, "lat": LAT_REIMS}}
    )
    assert moulinette.catalog["en_zone_vulnerable"] is False


# ─── Regulations / Criteria ────────────────────────────────────────────────


def test_regulation_directive_nitrates_chargee(department_marne, zv_map):
    """La migration data 0002 a cree la regulation et le criterion ;
    la moulinette doit les retrouver depuis la DB."""
    moulinette = MoulinetteNitrates(
        form_kwargs={"data": {"lng": LNG_REIMS, "lat": LAT_REIMS}}
    )
    regulations = list(moulinette.regulations)
    assert len(regulations) == 1
    assert regulations[0].slug == "directive_nitrates"


def test_critere_arbre_decision_present_et_evalue(department_marne, zv_map):
    moulinette = MoulinetteNitrates(
        form_kwargs={"data": {"lng": LNG_REIMS, "lat": LAT_REIMS}}
    )
    regulation = list(moulinette.regulations)[0]
    criteres = list(regulation.criteria.all())
    assert len(criteres) == 1
    assert criteres[0].slug == "arbre_decision"
    # Sans reponses cascade, l'arbre renvoie des questions subsidiaires
    # donc non_disponible. Le branchement detail est teste dans
    # test_arbre_decision_evaluator.py.
    assert criteres[0].result == "non_disponible"


# ─── Config / activation ───────────────────────────────────────────────────


def test_get_config_renvoie_none(department_marne, zv_map):
    """MVP : pas de ConfigNitrates."""
    moulinette = MoulinetteNitrates(
        form_kwargs={"data": {"lng": LNG_REIMS, "lat": LAT_REIMS}}
    )
    assert moulinette.config is None


def test_is_evaluation_available_avec_point_valide(department_marne, zv_map):
    moulinette = MoulinetteNitrates(
        form_kwargs={"data": {"lng": LNG_REIMS, "lat": LAT_REIMS}}
    )
    assert moulinette.is_evaluation_available()
