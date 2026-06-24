"""Couverture exhaustive de la branche `culture_principale` /
`prairie_plus_6_mois` de l'arbre PAN.

Source de verite : screenshot Miro fourni par Max le 2026-05-04. Une
classe par feuille (8 feuilles). Chaque test valide regle_id, type,
periodes (dates exactes + regime quand present) et code_prescription.

Cas couverts :
  1a. type_0 + plan_epandage=icpe_a       -> r_prairie_plus_6_type_0_icpe_a (pc1)
  1b. type_0 + plan_epandage=autre        -> r_prairie_plus_6_type_0
  2.  type_I                              -> r_prairie_plus_6_type_I
  3a. type_II + effluent_peu_charge=oui   -> r_prairie_plus_6_type_II_peu_charge (pc7)
  3b. type_II + effluent_peu_charge=non   -> r_prairie_plus_6_type_II
  4a. type_III + zone montagne note_7     -> r_prairie_plus_6_type_III_montagne_note7
  4b. type_III + zone montagne note_6     -> r_prairie_plus_6_type_III_montagne_note6
  4c. type_III + non montagne             -> r_prairie_plus_6_type_III

Note 7 (zone montagne prairie+6) utilise la variante "pyrenees_atl"
(PACA + Occitanie + 64 seul), pas la variante elargie (5 dept).
"""

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon

from envergo.evaluations.models import RESULTS
from envergo.geodata.models import MAP_TYPES, Department, Map, Zone
from envergo.moulinette.models import Criterion, Regulation
from envergo.nitrates.models import MoulinetteNitrates

# Reims (Marne, Grand Est, ZV bassin Seine-Normandie) : non_montagne.
LNG_REIMS = 4.0345
LAT_REIMS = 49.2583

# Accous (Pyrenees-Atlantiques 64006) : montagne note_7 (variante
# pyrenees_atl ET elargie).
INSEE_ACCOUS_64 = "64006"

# Aiguebelette-le-Lac (Savoie 73001) : montagne note_6 (Savoie en
# Auvergne-Rhone-Alpes, hors PACA/Occitanie/64).
INSEE_AIGUEBELETTE_73 = "73001"


@pytest.fixture
def setup(db):
    """Map ZV qui couvre l'hexagone (bbox large) pour que les
    coordonnees Reims/Accous/Savoie soient toutes en ZV."""
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
        "sous_culture": "prairie_plus_6_mois",
    }
    base.update(form_data)
    return MoulinetteNitrates(form_kwargs={"data": base})


def _evaluator(moulinette):
    regulation = list(moulinette.regulations)[0]
    criteres = list(regulation.criteria.all())
    assert len(criteres) == 1
    return criteres[0]._evaluator


# ─── 1a. type_0 + plan_epandage=icpe_a ─────────────────────────────────────


def test_prairie_plus_6_type_0_icpe_a(setup):
    """Type 0 + ICPE A : autorise sous condition 15/12 -> 15/01, pc1."""
    ev = _evaluator(_moulinette(type_fertilisant="type_0", plan_epandage="icpe_a"))
    assert ev.result == RESULTS.action_requise
    assert ev.regle.regle_id == "r_prairie_plus_6_type_0_icpe_a"
    assert ev.regle.type == "autorisation_sous_condition"
    assert ev.regle.periodes == [{"du": "15/12", "au": "15/01"}]
    assert ev.regle.code_prescription == "pc1"


# ─── 1b. type_0 + plan_epandage=autre ──────────────────────────────────────


def test_prairie_plus_6_type_0_autre(setup):
    """Type 0 + plan epandage autre : interdit 15/12 -> 15/01."""
    ev = _evaluator(_moulinette(type_fertilisant="type_0", plan_epandage="autre"))
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_prairie_plus_6_type_0"
    assert ev.regle.type == "interdiction"
    assert ev.regle.periodes == [{"du": "15/12", "au": "15/01"}]


# ─── 2. type_I ─────────────────────────────────────────────────────────────


def test_prairie_plus_6_type_I(setup):
    """Type I : interdit 15/12 -> 15/01."""
    ev = _evaluator(_moulinette(type_fertilisant="type_I"))
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_prairie_plus_6_type_I"
    assert ev.regle.periodes == [{"du": "15/12", "au": "15/01"}]


# ─── 3a. type_II + effluent_peu_charge=oui ─────────────────────────────────


def test_prairie_plus_6_type_II_peu_charge(setup):
    """Type II + effluents peu charges : autorise sous condition
    15/11 -> 15/01, pc7.

    Depuis #98, la branche "peu charge" n'est plus pilotee par un champ
    effluent_peu_charge=true/false mais par une expression catalogue_parametre
    sur `sous_fertilisant in (effluents_peu_charges_elevage,
    effluents_peu_charges_non_elevage)`. On pousse donc le sous_fertilisant
    correspondant (le contrat metier resultant est inchange)."""
    ev = _evaluator(
        _moulinette(
            type_fertilisant="type_II",
            sous_fertilisant="effluents_peu_charges_elevage",
        )
    )
    assert ev.result == RESULTS.action_requise
    assert ev.regle.regle_id == "r_prairie_plus_6_type_II_peu_charge"
    assert ev.regle.type == "autorisation_sous_condition"
    assert ev.regle.periodes == [{"du": "15/11", "au": "15/01"}]
    assert ev.regle.code_prescription == "pc7"


# ─── 3b. type_II + effluent_peu_charge=non ─────────────────────────────────


def test_prairie_plus_6_type_II_non_peu_charge(setup):
    """Type II + effluents peu charges Non : interdit 15/11 -> 15/01."""
    ev = _evaluator(
        _moulinette(type_fertilisant="type_II", effluent_peu_charge="false")
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_prairie_plus_6_type_II"
    assert ev.regle.periodes == [{"du": "15/11", "au": "15/01"}]


# ─── 3c/3d. Carte #98 : inference via flags du fertilisant ─────────────────


def test_prairie_plus_6_effluent_eleve_infere_la_question(setup):
    """Carte #98 : « effluents peu chargés issus d'élevage » -> la branche
    catalogue_parametre infère "peu chargé" via sous_fertilisant -> même
    feuille que le 3a (r_prairie_plus_6_type_II_peu_charge)."""
    ev = _evaluator(
        _moulinette(
            type_fertilisant="type_II",
            sous_fertilisant="effluents_peu_charges_elevage",
        )
    )
    assert ev.result == RESULTS.action_requise
    assert ev.regle.regle_id == "r_prairie_plus_6_type_II_peu_charge"
    assert ev.regle.code_prescription == "pc7"


def test_prairie_plus_6_effluent_non_eleve_infere_la_question(setup):
    """« Effluents peu chargés non issus d'élevage » : la branche prairie+6 ne
    distingue pas l'origine élevage -> même feuille peu chargé que pour
    l'élevage (l'expression catalogue_parametre accepte les deux valeurs)."""
    ev = _evaluator(
        _moulinette(
            type_fertilisant="type_II",
            sous_fertilisant="effluents_peu_charges_non_elevage",
        )
    )
    assert ev.result == RESULTS.action_requise
    assert ev.regle.regle_id == "r_prairie_plus_6_type_II_peu_charge"


# ─── 4a. type_III + montagne note 7 (Pyrenees-Atlantiques 64) ─────────────


def test_prairie_plus_6_type_III_montagne_note_7(setup):
    """Type III + commune montagne en Pyrenees-Atlantiques (64006 Accous) :
    interdit 01/10 -> 15/02, note_7."""
    ev = _evaluator(
        _moulinette(type_fertilisant="type_III", code_insee=INSEE_ACCOUS_64)
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_prairie_plus_6_type_III_montagne_note7"
    assert ev.regle.periodes == [{"du": "01/10", "au": "15/02"}]
    assert ev.regle.note == "note_7"


# ─── 4b. type_III + montagne note 6 (Savoie 73) ────────────────────────────


def test_prairie_plus_6_type_III_montagne_note_6(setup):
    """Type III + commune montagne Savoie (73001 Aiguebelette) : interdit
    01/10 -> 28/02, note_6 (montagne hors Set A pyrenees_atl)."""
    ev = _evaluator(
        _moulinette(type_fertilisant="type_III", code_insee=INSEE_AIGUEBELETTE_73)
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_prairie_plus_6_type_III_montagne_note6"
    assert ev.regle.periodes == [{"du": "01/10", "au": "28/02"}]
    assert ev.regle.note == "note_6"


# ─── 4c. type_III + non montagne (Reims, Marne) ────────────────────────────


def test_prairie_plus_6_type_III_non_montagne(setup):
    """Type III + commune non montagne (Reims) : interdit 01/10 -> 31/01."""
    ev = _evaluator(_moulinette(type_fertilisant="type_III", code_insee="51454"))
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_prairie_plus_6_type_III"
    assert ev.regle.periodes == [{"du": "01/10", "au": "31/01"}]
