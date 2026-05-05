"""Couverture exhaustive de la branche `culture_principale` /
`culture_hiver_hors_colza` de l'arbre PAN.

Source de verite : screenshot Miro fourni par Max le 2026-05-05.
6 feuilles, toutes en interdiction stricte. Pas de PC sur le screenshot.

Cas couverts :
  1.  type_0                              -> r_hiver_hors_colza_type_0       (15/12 -> 15/01)
  2.  type_I                              -> r_hiver_hors_colza_type_I       (15/11 -> 15/01)
  3a. type_II + zone note 5 oui           -> r_hiver_hors_colza_type_II_note5    (01/10 -> 15/01)
  3b. type_II + zone note 5 non           -> r_hiver_hors_colza_type_II_autres   (01/10 -> 31/01)
  4a. type_III + zone note 5 oui          -> r_hiver_hors_colza_type_III_note5   (01/09 -> 15/01)
  4b. type_III + zone note 5 non          -> r_hiver_hors_colza_type_III_autres  (01/09 -> 31/01)
"""

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon

from envergo.evaluations.models import RESULTS
from envergo.geodata.models import MAP_TYPES, Department, Map, Zone
from envergo.moulinette.models import Criterion, Regulation
from envergo.nitrates.models import MoulinetteNitrates

LNG_REIMS = 4.0345
LAT_REIMS = 49.2583

INSEE_TOULOUSE_31 = "31555"  # Occitanie -> note_5
INSEE_BORDEAUX_33 = "33063"  # Gironde -> note_5
INSEE_REIMS_51 = "51454"  # Marne -> hors note_5


@pytest.fixture
def setup(db):
    Department.objects.create(
        department="51",
        geometry=MultiPolygon(Polygon.from_bbox((3.5, 48.7, 5.0, 49.7))),
    )
    m, _ = Map.objects.get_or_create(
        map_type=MAP_TYPES.zv_nitrates,
        defaults={"name": "ZV test", "description": "test"},
    )
    Zone.objects.create(
        map=m,
        geometry=MultiPolygon(Polygon.from_bbox((-1.5, 42.5, 7.5, 51.0))),
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
            "envergo.nitrates.regulations.arbre_decision.ArbreDecisionEvaluator"
        ),
        defaults={
            "backend_title": "Arbre decision",
            "title": "Periodes epandage",
            "activation_map": m,
        },
    )
    return m


def _moulinette(**form_data):
    base = {
        "lng": LNG_REIMS,
        "lat": LAT_REIMS,
        "occupation_sol": "culture_principale",
        "sous_culture": "culture_hiver_hors_colza",
    }
    base.update(form_data)
    return MoulinetteNitrates(form_kwargs={"data": base})


def _evaluator(moulinette):
    regulation = list(moulinette.regulations)[0]
    criteres = list(regulation.criteria.all())
    assert len(criteres) == 1
    return criteres[0]._evaluator


# ─── 1. type_0 ─────────────────────────────────────────────────────────────


def test_culture_hiver_hors_colza_type_0(setup):
    """Type 0 : interdit 15/12 -> 15/01."""
    ev = _evaluator(_moulinette(type_fertilisant="type_0"))
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_hiver_hors_colza_type_0"
    assert ev.regle.type == "interdiction"
    assert ev.regle.periodes == [{"du": "15/12", "au": "15/01"}]


# ─── 2. type_I ─────────────────────────────────────────────────────────────


def test_culture_hiver_hors_colza_type_I(setup):
    """Type I : interdit 15/11 -> 15/01."""
    ev = _evaluator(_moulinette(type_fertilisant="type_I"))
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_hiver_hors_colza_type_I"
    assert ev.regle.periodes == [{"du": "15/11", "au": "15/01"}]


def test_culture_hiver_hors_colza_type_Ia_fallback(setup):
    """Fallback type_Ia -> branche type_I."""
    ev = _evaluator(_moulinette(type_fertilisant="type_Ia"))
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_hiver_hors_colza_type_I"


# ─── 3a. type_II + zone note 5 (Toulouse Occitanie) ────────────────────────


def test_culture_hiver_hors_colza_type_II_zone_note_5(setup):
    """Type II + zone note 5 (Toulouse) : interdit 01/10 -> 15/01."""
    ev = _evaluator(
        _moulinette(type_fertilisant="type_II", code_insee=INSEE_TOULOUSE_31)
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_hiver_hors_colza_type_II_note5"
    assert ev.regle.note == "note_5"
    assert ev.regle.periodes == [{"du": "01/10", "au": "15/01"}]


# ─── 3b. type_II + hors zone note 5 (Reims) ────────────────────────────────


def test_culture_hiver_hors_colza_type_II_hors_note_5(setup):
    """Type II + Reims (hors note 5) : interdit 01/10 -> 31/01."""
    ev = _evaluator(_moulinette(type_fertilisant="type_II", code_insee=INSEE_REIMS_51))
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_hiver_hors_colza_type_II_autres"
    assert ev.regle.periodes == [{"du": "01/10", "au": "31/01"}]


# ─── 4a. type_III + zone note 5 (Bordeaux 33) ──────────────────────────────


def test_culture_hiver_hors_colza_type_III_zone_note_5(setup):
    """Type III + zone note 5 (Bordeaux 33) : interdit 01/09 -> 15/01."""
    ev = _evaluator(
        _moulinette(type_fertilisant="type_III", code_insee=INSEE_BORDEAUX_33)
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_hiver_hors_colza_type_III_note5"
    assert ev.regle.note == "note_5"
    assert ev.regle.periodes == [{"du": "01/09", "au": "15/01"}]


# ─── 4b. type_III + hors zone note 5 (Reims) ───────────────────────────────


def test_culture_hiver_hors_colza_type_III_hors_note_5(setup):
    """Type III + Reims (hors note 5) : interdit 01/09 -> 31/01."""
    ev = _evaluator(_moulinette(type_fertilisant="type_III", code_insee=INSEE_REIMS_51))
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_hiver_hors_colza_type_III_autres"
    assert ev.regle.periodes == [{"du": "01/09", "au": "31/01"}]
