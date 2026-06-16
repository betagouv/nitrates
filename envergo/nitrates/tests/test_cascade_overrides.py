"""Tests de la CASCADE d'overrides (LOT 1b).

Plusieurs arbres actifs (PAN / PAR / ZAR) ; on parcourt le plus specifique
ENTIEREMENT ; s'il ne mene a aucune feuille (no-match), on recommence sur
l'arbre suivant avec le meme contexte cumulatif. Le PAN (couvrant) est le filet.

On teste via l'evaluateur reel (resolution geo + cascade), avec des arbres
squelette poses en base.
"""

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon

from envergo.geodata.models import MAP_TYPES, Department, Map, Zone
from envergo.moulinette.models import Criterion, Regulation
from envergo.nitrates.models import DecisionTree, MoulinetteNitrates

pytestmark = pytest.mark.django_db

# Reims (Grand Est, region 44).
LNG_REIMS, LAT_REIMS = 4.0345, 49.2583
BBOX_MARNE = (3.5, 48.7, 5.0, 49.7)


def _noeud_occupation(branches):
    """Arbre minimal : racine ZV -> noeud formulaire occupation_sol -> branches."""
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
                "source": "sig",
                "reference": "zone_vulnerable_nitrates",
                "branches": [
                    {
                        "valeur": True,
                        "noeud": {
                            "type_noeud": "formulaire",
                            "id": "q_occupation_sol",
                            "champ": "occupation_sol",
                            "niveau": "culture",
                            "texte": "Occupation du sol ?",
                            "branches": branches,
                        },
                    },
                ],
            }
        }
    }


def _regle(rid, valeur):
    return {
        "valeur": valeur,
        "regle": {"id": rid, "type": "interdiction", "message": rid},
    }


@pytest.fixture
def cascade(db):
    """PAN (2 branches: prairie, culture_principale) + PAR (prairie seule) +
    ZAR (prairie seule), tous actifs. Le PAR/ZAR ne couvre QUE prairie -> sur
    culture_principale, fallback PAN."""
    DecisionTree.objects.all().delete()
    Department.objects.create(
        department="51", geometry=MultiPolygon(Polygon.from_bbox(BBOX_MARNE))
    )
    zv, _ = Map.objects.get_or_create(
        map_type=MAP_TYPES.zv_nitrates,
        defaults={"name": "ZV", "description": "t"},
    )
    Zone.objects.create(
        map=zv,
        geometry=MultiPolygon(Polygon.from_bbox(BBOX_MARNE)),
        attributes={"CdEuBassin": "FRB1"},
    )
    zar_map = Map.objects.create(
        name="zar_test",
        map_type=MAP_TYPES.zone_action_renforcee,
        description="t",
    )
    zar_zone = Zone.objects.create(
        map=zar_map, geometry=MultiPolygon(Polygon.from_bbox(BBOX_MARNE))
    )
    reg, _ = Regulation.objects.get_or_create(
        regulation="directive_nitrates",
        defaults={
            "evaluator": (
                "envergo.nitrates.regulations.directive_nitrates."
                "DirectiveNitratesEvaluator"
            )
        },
    )
    Criterion.objects.get_or_create(
        regulation=reg,
        evaluator="envergo.nitrates.regulations.arbre_decision.ArbreDecisionEvaluator",
        defaults={"backend_title": "a", "title": "b", "activation_map": zv},
    )

    DecisionTree.objects.create(
        name="pan",
        status=DecisionTree.STATUS_ACTIVE,
        weight=1,
        contenu=_noeud_occupation(
            [
                _regle("r_pan_prairie", "prairie"),
                _regle("r_pan_culture", "culture_principale"),
            ]
        ),
    )
    DecisionTree.objects.create(
        name="par",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_REGION,
        region_code="44",
        weight=10,
        contenu=_noeud_occupation([_regle("r_par_prairie", "prairie")]),
    )
    DecisionTree.objects.create(
        name="zar",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_ZAR,
        region_code="44",
        activation_map=zar_map,
        weight=20,
        contenu=_noeud_occupation([_regle("r_zar_prairie", "prairie")]),
    )
    return {"zar_zone": zar_zone}


def _regle_id(occupation_sol):
    m = MoulinetteNitrates(
        form_kwargs={
            "data": {
                "lng": LNG_REIMS,
                "lat": LAT_REIMS,
                "occupation_sol": occupation_sol,
            }
        }
    )
    reg = list(m.regulations)[0]
    crit = list(reg.criteria.all())[0]
    return crit._evaluator.regle.regle_id


def test_zar_gagne_quand_couvert(cascade):
    """Point en ZAR + prairie : la regle ZAR (poids max) gagne."""
    assert _regle_id("prairie") == "r_zar_prairie"


def test_fallback_zar_vers_pan_si_zar_ne_couvre_pas(cascade):
    """Point en ZAR mais culture_principale : ni ZAR ni PAR ne couvrent cette
    branche -> cascade jusqu'au PAN."""
    assert _regle_id("culture_principale") == "r_pan_culture"


@pytest.fixture
def cascade_hors_zar(cascade):
    """Variante : la zone ZAR ne couvre PAS Reims (bbox au sud-ouest, loin).
    Le point reste en ZV + region 44 -> niveau PAR, pas ZAR."""
    zone = cascade["zar_zone"]
    zone.geometry = MultiPolygon(Polygon.from_bbox((3.5, 48.7, 3.6, 48.8)))
    zone.save(update_fields=["geometry"])
    return cascade


def test_par_gagne_quand_hors_zar(cascade_hors_zar):
    """Point en region 44 + ZV mais HORS de la couche ZAR : la regle PAR
    (poids 10) gagne sur le PAN (poids 1)."""
    assert _regle_id("prairie") == "r_par_prairie"


def test_fallback_par_vers_pan_si_par_ne_couvre_pas(cascade_hors_zar):
    """Hors ZAR, culture_principale : le PAR ne couvre que prairie -> PAN."""
    assert _regle_id("culture_principale") == "r_pan_culture"


@pytest.fixture
def cascade_renvoi(db):
    """ZAR fait un renvoi EXPLICITE vers le PAR (renvoi_arbre: region) sur la
    branche prairie. Le PAR resout prairie -> r_par_prairie. (Cas des captures :
    'go to arbre PAR GE'.)"""
    DecisionTree.objects.all().delete()
    Department.objects.create(
        department="51", geometry=MultiPolygon(Polygon.from_bbox(BBOX_MARNE))
    )
    zv, _ = Map.objects.get_or_create(
        map_type=MAP_TYPES.zv_nitrates, defaults={"name": "ZV", "description": "t"}
    )
    Zone.objects.create(
        map=zv,
        geometry=MultiPolygon(Polygon.from_bbox(BBOX_MARNE)),
        attributes={"CdEuBassin": "FRB1"},
    )
    zar_map = Map.objects.create(
        name="zar_test", map_type=MAP_TYPES.zone_action_renforcee, description="t"
    )
    Zone.objects.create(
        map=zar_map, geometry=MultiPolygon(Polygon.from_bbox(BBOX_MARNE))
    )
    reg, _ = Regulation.objects.get_or_create(
        regulation="directive_nitrates",
        defaults={
            "evaluator": (
                "envergo.nitrates.regulations.directive_nitrates."
                "DirectiveNitratesEvaluator"
            )
        },
    )
    Criterion.objects.get_or_create(
        regulation=reg,
        evaluator="envergo.nitrates.regulations.arbre_decision.ArbreDecisionEvaluator",
        defaults={"backend_title": "a", "title": "b", "activation_map": zv},
    )
    DecisionTree.objects.create(
        name="pan",
        status=DecisionTree.STATUS_ACTIVE,
        weight=1,
        contenu=_noeud_occupation([_regle("r_pan_prairie", "prairie")]),
    )
    DecisionTree.objects.create(
        name="par",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_REGION,
        region_code="44",
        weight=10,
        contenu=_noeud_occupation([_regle("r_par_prairie", "prairie")]),
    )
    # ZAR : branche prairie -> renvoi_arbre vers le PAR (region).
    DecisionTree.objects.create(
        name="zar",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_ZAR,
        region_code="44",
        activation_map=zar_map,
        weight=20,
        contenu=_noeud_occupation([{"valeur": "prairie", "renvoi_arbre": "region"}]),
    )


def test_renvoi_arbre_zar_vers_par(cascade_renvoi):
    """ZAR atteint 'renvoi_arbre: region' -> bascule sur le PAR, qui resout."""
    assert _regle_id("prairie") == "r_par_prairie"
