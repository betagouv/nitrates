"""Couverture exhaustive de la branche `culture_principale` /
`culture_de_printemps` de l'arbre PAN.

Source de verite : screenshot Miro fourni par Max le 2026-05-04. Une
classe par feuille (8 feuilles). Chaque test valide regle_id, type,
periodes (dates exactes + regime quand present) et code_prescription.

Cas couverts :
  1. type_0                                 -> r_printemps_type_0
  2. type_Ia                                -> r_printemps_type_Ia
  3. type_Ib                                -> r_printemps_type_Ib
  4. type_II + fertirrigation oui           -> r_printemps_II_peu_charge_fertirrig
  5. type_II + fertirrigation non           -> r_printemps_II_peu_charge_sans_fertirrig
  6. type_III + irriguee oui + mais         -> r_printemps_III_mais_irrigue
  7. type_III + irriguee oui + autre        -> r_printemps_III_autre_irrigue
  8. type_III + irriguee non                -> r_printemps_III_non_irrigue
"""

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon

from envergo.evaluations.models import RESULTS
from envergo.geodata.models import MAP_TYPES, Department, Map, Zone
from envergo.moulinette.models import Criterion, Regulation
from envergo.nitrates.models import MoulinetteNitrates

LNG_REIMS = 4.0345
LAT_REIMS = 49.2583


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
        "sous_culture": "culture_printemps",
    }
    base.update(form_data)
    return MoulinetteNitrates(form_kwargs={"data": base})


def _evaluator(moulinette):
    regulation = list(moulinette.regulations)[0]
    criteres = list(regulation.criteria.all())
    assert len(criteres) == 1
    return criteres[0]._evaluator


# ─── 1. type_0 ─────────────────────────────────────────────────────────────


def test_printemps_type_0(setup):
    """Type 0 : interdit du 15/12 au 15/01."""
    ev = _evaluator(_moulinette(type_fertilisant="type_0"))
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_printemps_type_0"
    assert ev.regle.type == "interdiction"
    assert ev.regle.periodes == [{"du": "15/12", "au": "15/01"}]
    assert ev.regle.code_prescription is None


# ─── 2. type_Ia ────────────────────────────────────────────────────────────


def test_printemps_type_Ia_deux_periodes(setup):
    """Type Ia : 2 periodes distinctes — 01/07->31/08 puis 15/11->15/01."""
    ev = _evaluator(_moulinette(type_fertilisant="type_Ia"))
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_printemps_type_Ia"
    assert ev.regle.type == "interdiction"
    assert ev.regle.periodes == [
        {"du": "01/07", "au": "31/08"},
        {"du": "15/11", "au": "15/01"},
    ]


# ─── 3. type_Ib ────────────────────────────────────────────────────────────


def test_printemps_type_Ib(setup):
    """Type Ib : interdit du 01/07 au 15/01."""
    ev = _evaluator(_moulinette(type_fertilisant="type_Ib"))
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_printemps_type_Ib"
    assert ev.regle.periodes == [{"du": "01/07", "au": "15/01"}]


# ─── 4. type_II + fertirrigation = Oui ─────────────────────────────────────


def test_printemps_type_II_fertirrigation_oui(setup):
    """Type II + fertirrigation Oui : 2 periodes avec regimes mixtes
    + code_prescription pc6."""
    ev = _evaluator(
        _moulinette(
            type_fertilisant="type_II_effluents_peu_charges",
            fertirrigation="true",
        )
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_printemps_II_peu_charge_fertirrig"
    assert ev.regle.code_prescription == "pc6"
    assert ev.regle.periodes == [
        {
            "du": "01/07",
            "au": "31/08",
            "regime": "autorisation_sous_condition",
        },
        {"du": "31/08", "au": "31/01", "regime": "interdiction"},
    ]


# ─── 5. type_II + fertirrigation = Non ─────────────────────────────────────


def test_printemps_type_II_fertirrigation_non(setup):
    """Type II + fertirrigation Non : interdit du 01/07 au 31/01 (pas
    de code prescription)."""
    ev = _evaluator(
        _moulinette(
            type_fertilisant="type_II_effluents_peu_charges",
            fertirrigation="false",
        )
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_printemps_II_peu_charge_sans_fertirrig"
    assert ev.regle.code_prescription is None
    assert ev.regle.periodes == [{"du": "01/07", "au": "31/01"}]


# ─── 6. type_III + culture_irriguee = Oui + Mais ───────────────────────────


def test_printemps_type_III_irriguee_mais(setup):
    """Type III + irriguee Oui + Mais : interdit 15/07 -> 15/02, pc5.
    + message specifique sur l'extension phenologique brunissement
    des soies (cf. spec PC5)."""
    ev = _evaluator(
        _moulinette(
            type_fertilisant="type_III",
            culture_irriguee="true",
            culture_irriguee_type="mais",
        )
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_printemps_III_mais_irrigue"
    assert ev.regle.code_prescription == "pc5"
    assert ev.regle.periodes == [{"du": "15/07", "au": "15/02"}]
    # Message specifique mais (extension phenologique).
    assert ev.regle.message is not None
    assert "brunissement des soies" in ev.regle.message


# ─── 7. type_III + culture_irriguee = Oui + Autre ──────────────────────────


def test_printemps_type_III_irriguee_autre(setup):
    """Type III + irriguee Oui + Autre : interdit 15/07 -> 15/02, pc5."""
    ev = _evaluator(
        _moulinette(
            type_fertilisant="type_III",
            culture_irriguee="true",
            culture_irriguee_type="autre",
        )
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_printemps_III_autre_irrigue"
    assert ev.regle.code_prescription == "pc5"
    assert ev.regle.periodes == [{"du": "15/07", "au": "15/02"}]


# ─── 8. type_III + culture_irriguee = Non ──────────────────────────────────


def test_printemps_type_III_non_irriguee(setup):
    """Type III + irriguee Non : interdit 01/07 -> 15/02, pas de pc."""
    ev = _evaluator(
        _moulinette(
            type_fertilisant="type_III",
            culture_irriguee="false",
        )
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_printemps_III_non_irrigue"
    assert ev.regle.code_prescription is None
    assert ev.regle.periodes == [{"du": "01/07", "au": "15/02"}]
