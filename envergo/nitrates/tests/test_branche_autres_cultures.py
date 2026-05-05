"""Couverture exhaustive de la branche `culture_principale` /
`autres_cultures` de l'arbre PAN.

Source de verite : screenshot Miro fourni par Max le 2026-05-05.
1 seule feuille : regle directe, sans noeud type_fertilisant
intermediaire. Tous types confondus (0, Ia, Ib, II, III) : interdit
15/12 -> 15/01.

Le user qui choisit autres_cultures saute la question "type de
fertilisant" dans le formulaire UI -- la regle est posee directement
sur la branche YAML.
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
        "sous_culture": "autres_cultures",
    }
    base.update(form_data)
    return MoulinetteNitrates(form_kwargs={"data": base})


def _evaluator(moulinette):
    regulation = list(moulinette.regulations)[0]
    criteres = list(regulation.criteria.all())
    assert len(criteres) == 1
    return criteres[0]._evaluator


# ─── Cas unique : regle directe, tous types confondus ──────────────────────


def test_autres_cultures_sans_type_fertilisant(setup):
    """Sans type_fertilisant : la regle est atteinte directement (la
    branche autres_cultures porte la regle sans noeud intermediaire)."""
    ev = _evaluator(_moulinette())
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_autres_cultures_tous_types"
    assert ev.regle.type == "interdiction"
    assert ev.regle.periodes == [{"du": "15/12", "au": "15/01"}]


def test_autres_cultures_avec_type_0_meme_resultat(setup):
    """Meme resultat avec type_fertilisant present : la regle ne
    depend pas du fertilisant pour autres_cultures."""
    ev = _evaluator(_moulinette(type_fertilisant="type_0"))
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_autres_cultures_tous_types"
    assert ev.regle.periodes == [{"du": "15/12", "au": "15/01"}]


@pytest.mark.parametrize(
    "type_fert", ["type_0", "type_Ia", "type_Ib", "type_I", "type_II", "type_III"]
)
def test_autres_cultures_tous_types_meme_regle(setup, type_fert):
    """Tous les types de fertilisant menent a la meme regle :
    `r_autres_cultures_tous_types` quelle que soit la valeur."""
    ev = _evaluator(_moulinette(type_fertilisant=type_fert))
    assert ev.result == RESULTS.interdit
    assert ev.regle.regle_id == "r_autres_cultures_tous_types"
    assert ev.regle.periodes == [{"du": "15/12", "au": "15/01"}]
