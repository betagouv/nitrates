"""Couverture exhaustive de la branche `culture_principale` / `luzerne`
de l'arbre PAN.

Source de verite : screenshots Miro fournis par Max le 2026-05-05.
Branche la plus complexe : 12 cas, 7 feuilles directes + 5 renvoi_vers,
3 niveaux de questions (Q1 plan_epandage, Q2 fertilisant_iaa) et 2
catalogues SIG imbriques sur Type III IAA (zone_montagne_d113_14 +
zone_note_7_vs_note_6).

Cas couverts :
  1.  type_0                                                 -> renvoi prairie+6 type_0
  2a. type_I + ICPE A + IAA                                  -> r_luzerne_I_icpe_a_iaa (calculatrice, pc10)
  2b. type_I + ICPE A + non IAA                              -> r_luzerne_I_icpe_a_sans_iaa (interdit)
  2c. type_I + autre plan epandage                           -> r_luzerne_I_autre (interdit)
  3a. type_II + ICPE A + IAA                                 -> r_luzerne_II_icpe_a_iaa (calculatrice, pc10)
  3b. type_II + ICPE A + non IAA                             -> renvoi prairie+6 type_II
  3c. type_II + autre                                        -> renvoi prairie+6 type_II
  4a. type_III + ICPE A + IAA + montagne + note 7            -> r_luzerne_III_iaa_montagne_note7
  4b. type_III + ICPE A + IAA + montagne + note 6            -> r_luzerne_III_iaa_montagne_note6
  4c. type_III + ICPE A + IAA + non montagne                 -> r_luzerne_III_iaa_non_montagne
  4d. type_III + ICPE A + non IAA                            -> renvoi prairie+6 type_III
  4e. type_III + autre                                       -> renvoi prairie+6 type_III
"""

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon

from envergo.evaluations.models import RESULTS
from envergo.geodata.models import MAP_TYPES, Department, Map, Zone
from envergo.moulinette.models import Criterion, Regulation
from envergo.nitrates.models import MoulinetteNitrates

LNG_REIMS = 4.0345
LAT_REIMS = 49.2583

# Communes utilisees pour la branche Type III + IAA + montagne :
INSEE_ACCOUS_64 = "64006"  # PA, montagne, variante elargie -> note_7
INSEE_AIGUEBELETTE_73 = "73001"  # Savoie, montagne, hors PA -> note_6
INSEE_REIMS_51 = "51454"  # Marne, hors montagne -> non_montagne


@pytest.fixture
def setup(db):
    """Map ZV qui couvre l'hexagone (bbox large) pour que les
    coordonnees de toutes les communes testees soient en ZV."""
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
        "sous_culture": "luzerne",
    }
    base.update(form_data)
    return MoulinetteNitrates(form_kwargs={"data": base})


def _evaluator(moulinette):
    regulation = list(moulinette.regulations)[0]
    criteres = list(regulation.criteria.all())
    assert len(criteres) == 1
    return criteres[0]._evaluator


# ─── 1. type_0 -> renvoi prairie+6 type_0 ─────────────────────────────────


def test_luzerne_type_0_renvoi_prairie(setup):
    """Type 0 + plan_epandage=autre : renvoi vers le sous-arbre prairie+6
    type_0 ICPE. Avec plan_epandage=autre, on tombe sur la regle
    r_prairie_plus_6_type_0 (interdit 15/12 -> 15/01).
    Note 2026-05-12 : la luzerne type_0 renvoie maintenant vers le NOEUD
    q_prairie_plus6_type_0_icpe (au lieu de la regle directe), donc on a
    une QC `plan_epandage` a fournir."""
    ev = _evaluator(_moulinette(type_fertilisant="type_0", plan_epandage="autre"))
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_prairie_plus_6_type_0"
    assert ev.regle.periodes == [{"du": "15/12", "au": "15/01"}]


# ─── 2a. type_I + ICPE A + IAA -> calculatrice ────────────────────────────


def test_luzerne_type_I_icpe_a_iaa(setup):
    """Type I + ICPE A + IAA : regime mixte (interdiction 15/12 -> 15/01
    + autorisation_sous_condition derniere_coupe_luzerne -> 15/01), pc10.
    Note 2026-05-12 : passe de calculatrice -> mixte suite a validation
    metier (cf. issue #44 "autorise sous condition apres derniere coupe")."""
    ev = _evaluator(
        _moulinette(
            type_fertilisant="type_I",
            plan_epandage="icpe_a",
            fertilisant_iaa="true",
        )
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_luzerne_I_icpe_a_iaa"
    assert ev.regle.type == "mixte"


# ─── 2b. type_I + ICPE A + non IAA -> interdit ────────────────────────────


def test_luzerne_type_I_icpe_a_sans_iaa(setup):
    """Type I + ICPE A + non IAA : interdit 15/12 -> 15/01."""
    ev = _evaluator(
        _moulinette(
            type_fertilisant="type_I",
            plan_epandage="icpe_a",
            fertilisant_iaa="false",
        )
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_luzerne_I_icpe_a_sans_iaa"
    assert ev.regle.periodes == [{"du": "15/12", "au": "15/01"}]


# ─── 2c. type_I + autre -> interdit ───────────────────────────────────────


def test_luzerne_type_I_autre(setup):
    """Type I + autre plan d'epandage : interdit 15/12 -> 15/01."""
    ev = _evaluator(_moulinette(type_fertilisant="type_I", plan_epandage="autre"))
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_luzerne_I_autre"
    assert ev.regle.periodes == [{"du": "15/12", "au": "15/01"}]


# ─── 3a. type_II + ICPE A + IAA -> calculatrice ───────────────────────────


def test_luzerne_type_II_icpe_a_iaa(setup):
    """Type II + ICPE A + IAA : regime mixte (interdiction 15/11 -> 15/01
    + autorisation_sous_condition derniere_coupe_luzerne -> 15/01), pc10."""
    ev = _evaluator(
        _moulinette(
            type_fertilisant="type_II",
            plan_epandage="icpe_a",
            fertilisant_iaa="true",
        )
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_luzerne_II_icpe_a_iaa"
    assert ev.regle.type == "mixte"


# ─── 3b. type_II + ICPE A + non IAA -> renvoi prairie+6 type_II ───────────


def test_luzerne_type_II_icpe_a_sans_iaa_renvoi(setup):
    """Type II + ICPE A + non IAA + effluent_peu_charge=false : renvoi
    vers q_prairie_plus6_II_effluent qui pose la QC effluent_peu_charge.
    Avec effluent_peu_charge=false -> r_prairie_plus_6_type_II
    (interdit 15/11 -> 15/01).
    Note 2026-05-12 : la luzerne II non IAA renvoie maintenant vers le
    NOEUD q_prairie_plus6_II_effluent (au lieu de r_prairie_plus_6_type_II
    direct), donc une QC supplementaire est demandee."""
    ev = _evaluator(
        _moulinette(
            type_fertilisant="type_II",
            plan_epandage="icpe_a",
            fertilisant_iaa="false",
            effluent_peu_charge="false",
        )
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_prairie_plus_6_type_II"
    assert ev.regle.periodes == [{"du": "15/11", "au": "15/01"}]


# ─── 3c. type_II + autre -> renvoi prairie+6 type_II ──────────────────────


def test_luzerne_type_II_autre_renvoi(setup):
    """Type II + autre plan d'epandage + effluent_peu_charge=false : renvoi
    vers q_prairie_plus6_II_effluent, puis r_prairie_plus_6_type_II.
    Note 2026-05-12 : ajoute effluent_peu_charge dans le contexte car la
    luzerne II non-icpe renvoie aussi vers le noeud effluent."""
    ev = _evaluator(
        _moulinette(
            type_fertilisant="type_II",
            plan_epandage="autre",
            effluent_peu_charge="false",
        )
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_prairie_plus_6_type_II"
    assert ev.regle.periodes == [{"du": "15/11", "au": "15/01"}]


# ─── 4a. type_III + ICPE A + IAA + montagne note 7 (Accous 64) ────────────


def test_luzerne_type_III_iaa_montagne_note_7(setup):
    """Type III + ICPE A + IAA + montagne PA (Accous 64006) : regime mixte
    (interdiction 01/10 -> 15/02 + autorisation_sous_condition apres
    derniere coupe luzerne), pc10, note_7."""
    ev = _evaluator(
        _moulinette(
            type_fertilisant="type_III",
            plan_epandage="icpe_a",
            fertilisant_iaa="true",
            code_insee=INSEE_ACCOUS_64,
        )
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_luzerne_III_iaa_montagne_note7"
    assert ev.regle.type == "mixte"


# ─── 4b. type_III + ICPE A + IAA + montagne note 6 (Aiguebelette 73) ──────


def test_luzerne_type_III_iaa_montagne_note_6(setup):
    """Type III + ICPE A + IAA + montagne Savoie (73001) : regime mixte
    (interdiction 01/10 -> 28/02 + autorisation_sous_condition apres
    derniere coupe luzerne), pc10, note_6."""
    ev = _evaluator(
        _moulinette(
            type_fertilisant="type_III",
            plan_epandage="icpe_a",
            fertilisant_iaa="true",
            code_insee=INSEE_AIGUEBELETTE_73,
        )
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_luzerne_III_iaa_montagne_note6"
    assert ev.regle.type == "mixte"


# ─── 4c. type_III + ICPE A + IAA + non montagne (Reims 51) ────────────────


def test_luzerne_type_III_iaa_non_montagne(setup):
    """Type III + ICPE A + IAA + Reims (hors montagne) : regime mixte
    (interdiction 01/10 -> 31/01 + autorisation_sous_condition apres
    derniere coupe luzerne), pc10."""
    ev = _evaluator(
        _moulinette(
            type_fertilisant="type_III",
            plan_epandage="icpe_a",
            fertilisant_iaa="true",
            code_insee=INSEE_REIMS_51,
        )
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_luzerne_III_iaa_non_montagne"
    assert ev.regle.type == "mixte"


# ─── 4d. type_III + ICPE A + non IAA -> renvoi prairie+6 type_III ─────────


def test_luzerne_type_III_icpe_a_sans_iaa_renvoi(setup):
    """Type III + ICPE A + non IAA : renvoi r_prairie_plus_6_type_III.
    Cas non montagne : interdit 01/10 -> 15/01 (cf. test prairie+6)."""
    ev = _evaluator(
        _moulinette(
            type_fertilisant="type_III",
            plan_epandage="icpe_a",
            fertilisant_iaa="false",
            code_insee=INSEE_REIMS_51,
        )
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_prairie_plus_6_type_III"
    assert ev.regle.periodes == [{"du": "01/10", "au": "15/01"}]


# ─── 4e. type_III + autre -> renvoi prairie+6 type_III ────────────────────


def test_luzerne_type_III_autre_renvoi(setup):
    """Type III + autre plan d'epandage : renvoi r_prairie_plus_6_type_III."""
    ev = _evaluator(
        _moulinette(
            type_fertilisant="type_III",
            plan_epandage="autre",
            code_insee=INSEE_REIMS_51,
        )
    )
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_prairie_plus_6_type_III"
    assert ev.regle.periodes == [{"du": "01/10", "au": "15/01"}]
