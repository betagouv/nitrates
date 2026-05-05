"""Tests du mapping commune INSEE -> classification zone montagne D113-14
+ integration via l'ArbreDecisionEvaluator (parcours complet)."""

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon

from envergo.evaluations.models import RESULTS
from envergo.geodata.models import MAP_TYPES, Department, Map, Zone
from envergo.moulinette.models import Criterion, Regulation
from envergo.nitrates.models import MoulinetteNitrates
from envergo.nitrates.zonage_montagne import _mapping, zonage_montagne_pour_commune


def test_mapping_charge_5789_communes_montagne():
    """Le CSV juriste contient 5789 communes flaggees zone_montagne=C
    (verifie via `awk` sur la source). Si ce nombre change apres une
    mise a jour de l'asset, ce test signale qu'il faut revoir les
    valeurs attendues dans l'arbre."""
    nb_montagne = sum(1 for v in _mapping().values() if v["montagne"])
    assert nb_montagne == 5789


def test_paca_dept_04_renvoie_note_7():
    # Aiglun (04001), region 93 PACA -> Note 7
    assert zonage_montagne_pour_commune("04001") == "montagne_note_7"


def test_aquitaine_dept_64_renvoie_note_7():
    # Accous (64006), dept 64 dans la liste Aquitaine note_7
    assert zonage_montagne_pour_commune("64006") == "montagne_note_7"


def test_savoie_dept_73_renvoie_note_6():
    # Aiguebelette-le-Lac (73001), region 84 Auvergne-Rhone-Alpes
    # -> montagne mais pas note_7
    assert zonage_montagne_pour_commune("73001") == "montagne_note_6"


def test_commune_non_montagne_renvoie_non_montagne():
    # Trois Lacs (27676), Normandie : pas en montagne
    assert zonage_montagne_pour_commune("27676") == "non_montagne"


def test_code_insee_inconnu_renvoie_non_montagne():
    """Si le code INSEE est absent du CSV (ex : nouvelle commune,
    fusion) on retourne `non_montagne` plutot que de planter."""
    assert zonage_montagne_pour_commune("99999") == "non_montagne"


def test_code_insee_none_renvoie_non_montagne():
    assert zonage_montagne_pour_commune(None) == "non_montagne"


def test_code_insee_vide_renvoie_non_montagne():
    assert zonage_montagne_pour_commune("") == "non_montagne"


@pytest.mark.parametrize(
    "code,attendu",
    [
        ("04001", "montagne_note_7"),  # PACA
        ("64006", "montagne_note_7"),  # Aquitaine 64
        ("73001", "montagne_note_6"),  # ARA
        ("27676", "non_montagne"),
    ],
)
def test_zonage_montagne_param(code, attendu):
    assert zonage_montagne_pour_commune(code) == attendu


# ─── Tests d'integration : parcours complet via ArbreDecisionEvaluator ──────


@pytest.fixture
def setup_zv_marne(db):
    """Setup minimal pour un parcours en ZV : dept Marne + map ZV
    couvrant Reims + regulation/criterion attaches a la map. Le
    code_insee, lui, est juste dans les query params (pas dependant
    d'un dataset PostGIS pour la zone montagne)."""
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


def _evaluator(mou):
    regulation = list(mou.regulations)[0]
    crit = list(regulation.criteria.all())[0]
    return crit._evaluator


@pytest.mark.parametrize(
    "code_insee,regle_attendue",
    [
        # PACA -> note_7 -> regle interdiction 01/10 - 15/02
        ("04001", "r_prairie_plus_6_type_III_montagne_note7"),
        # Savoie -> note_6 -> regle interdiction 01/10 - 28/02
        ("73001", "r_prairie_plus_6_type_III_montagne_note6"),
        # Marne (51XXX) -> non_montagne
        ("51454", "r_prairie_plus_6_type_III"),
    ],
)
def test_parcours_prairie_III_resoud_zone_montagne(
    setup_zv_marne, code_insee, regle_attendue
):
    """Le parcours d'une prairie de plus de 6 mois en type_III doit
    atteindre la regle correspondant a la zone montagne (note_7,
    note_6 ou non_montagne) selon le code INSEE pousse par le front."""
    mou = MoulinetteNitrates(
        form_kwargs={
            "data": {
                "lng": 4.0345,
                "lat": 49.2583,
                "code_insee": code_insee,
                "occupation_sol": "culture_principale",
                "sous_culture": "prairie_plus_6_mois",
                "type_fertilisant": "type_III",
            }
        }
    )
    ev = _evaluator(mou)
    assert ev.result == RESULTS.interdit
    assert ev.regle is not None
    assert ev.regle.regle_id == regle_attendue


def test_parcours_prairie_III_sans_code_insee_renvoie_non_montagne(setup_zv_marne):
    """Si le code INSEE est absent (ex : utilisateur n'a pas cliqué sur
    la carte), on retombe par defaut sur `non_montagne` plutot que de
    bloquer le parcours."""
    mou = MoulinetteNitrates(
        form_kwargs={
            "data": {
                "lng": 4.0345,
                "lat": 49.2583,
                "occupation_sol": "culture_principale",
                "sous_culture": "prairie_plus_6_mois",
                "type_fertilisant": "type_III",
            }
        }
    )
    ev = _evaluator(mou)
    assert ev.regle is not None
    assert ev.regle.regle_id == "r_prairie_plus_6_type_III"
