"""Regression : preview d'un draft (`?draft_tree_id=<pk>`) via l'evaluateur.

La cascade attend des ArbreCandidat (.scope/.contenu/.pk...). Le chemin draft
preview renvoyait un tuple ("draft", contenu) -> 'tuple' object has no attribute
'scope'. On verifie ici que la preview passe par la cascade sans crash et
applique bien la regle du DRAFT (pas de l'actif).
"""

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon

from envergo.geodata.models import MAP_TYPES, Department, Map, Zone
from envergo.moulinette.models import Criterion, Regulation
from envergo.nitrates.models import DecisionTree, MoulinetteNitrates

pytestmark = pytest.mark.django_db

LNG_REIMS, LAT_REIMS = 4.0345, 49.2583
BBOX_MARNE = (3.5, 48.7, 5.0, 49.7)


def _arbre(rid, valeur):
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
                            "branches": [
                                {
                                    "valeur": valeur,
                                    "regle": {
                                        "id": rid,
                                        "type": "interdiction",
                                        "message": rid,
                                    },
                                }
                            ],
                        },
                    },
                ],
            }
        }
    }


@pytest.fixture
def actif_et_draft(db):
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
    actif = DecisionTree.objects.create(
        name="pan",
        status=DecisionTree.STATUS_ACTIVE,
        weight=1,
        contenu=_arbre("r_actif", "prairie"),
    )
    draft = DecisionTree.objects.create(
        name="pan",
        status=DecisionTree.STATUS_DRAFT,
        parent=actif,
        contenu=_arbre("r_draft", "prairie"),
    )
    return actif, draft


def _regle_id(data):
    m = MoulinetteNitrates(form_kwargs={"data": data})
    reg = list(m.regulations)[0]
    crit = list(reg.criteria.all())[0]
    return crit._evaluator.regle.regle_id


def test_draft_preview_applique_la_regle_du_draft(actif_et_draft):
    """draft_tree_id route l'evaluation sur le draft, pas l'actif (et ne
    crashe pas : le draft est bien enveloppe en ArbreCandidat)."""
    _, draft = actif_et_draft
    rid = _regle_id(
        {
            "lng": LNG_REIMS,
            "lat": LAT_REIMS,
            "occupation_sol": "prairie",
            "draft_tree_id": str(draft.pk),
        }
    )
    assert rid == "r_draft"


def test_sans_draft_id_applique_lactif(actif_et_draft):
    rid = _regle_id({"lng": LNG_REIMS, "lat": LAT_REIMS, "occupation_sol": "prairie"})
    assert rid == "r_actif"


def test_draft_id_inconnu_fallback_actif(actif_et_draft):
    """draft_tree_id pointant sur un pk inexistant -> fallback cascade active."""
    rid = _regle_id(
        {
            "lng": LNG_REIMS,
            "lat": LAT_REIMS,
            "occupation_sol": "prairie",
            "draft_tree_id": "999999",
        }
    )
    assert rid == "r_actif"
