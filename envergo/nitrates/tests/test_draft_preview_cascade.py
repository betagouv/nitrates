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


def _arbre_qc_apres_catalogue_sig():
    """Arbre : ZVN -> QC1 (plan_epandage) -> catalogue SIG zone_note_5 -> QC2
    (detail). zone_note_5 est resolu par la moulinette (pas dans l'URL).
    Reproduit le motif du bug #187 pour le panneau recap gauche."""
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
                            "id": "q_plan",
                            "champ": "plan_epandage",
                            "niveau": "complement",
                            "texte": "Plan d'epandage ?",
                            "branches": [
                                {
                                    "valeur": "icpe_a",
                                    "noeud": {
                                        "type_noeud": "catalogue",
                                        "id": "n_zn5",
                                        "champ": "zone_note_5",
                                        "source": "sig",
                                        "reference": "zone_note_5",
                                        "branches": [
                                            {
                                                "valeur": True,
                                                "noeud": {
                                                    "type_noeud": "formulaire",
                                                    "id": "q_detail",
                                                    "champ": "detail_apres_sig",
                                                    "niveau": "complement",
                                                    "texte": "Detail ?",
                                                    "branches": [
                                                        {
                                                            "valeur": "x",
                                                            "regle": {
                                                                "id": "r_fin",
                                                                "type": "libre",
                                                            },
                                                        }
                                                    ],
                                                },
                                            },
                                            {
                                                "valeur": False,
                                                "noeud": {
                                                    "type_noeud": "formulaire",
                                                    "id": "q_detail_bis",
                                                    "champ": "detail_apres_sig",
                                                    "niveau": "complement",
                                                    "texte": "Detail ?",
                                                    "branches": [
                                                        {
                                                            "valeur": "x",
                                                            "regle": {
                                                                "id": "r_fin_bis",
                                                                "type": "libre",
                                                            },
                                                        }
                                                    ],
                                                },
                                            },
                                        ],
                                    },
                                },
                            ],
                        },
                    },
                ],
            }
        }
    }


def test_bug_187_recap_qc_resolu_par_callback_sig(actif_et_draft):
    """#187 : le panneau recap gauche doit voir la QC descendante (detail_apres_sig)
    meme quand un catalogue SIG (zone_note_5) la separe de la QC parente. Le
    catalogue SIG n'est pas dans l'URL : le callback `_resoudre_catalogue_pour_collecte`
    de l'evaluateur le resout a la volee (geo-deterministe) pour aplatir le
    sous-arbre. C'est le cablage reel de la vue."""
    from envergo.nitrates.yaml_tree import collecter_qc_du_chemin

    actif, _ = actif_et_draft
    actif.contenu = _arbre_qc_apres_catalogue_sig()
    actif.save()

    data = {
        "lng": LNG_REIMS,
        "lat": LAT_REIMS,
        "plan_epandage": "icpe_a",
    }
    m = MoulinetteNitrates(form_kwargs={"data": data})
    if not m.is_evaluated():
        m.evaluate()
    ev = list(list(m.regulations)[0].criteria.all())[0]._evaluator
    arbre = ev.arbre_courant

    # SANS callback : contexte = GET brut, zone_note_5 absent -> la descente
    # s'arrete au catalogue SIG, detail_apres_sig invisible (symptome du bug).
    ctx_url = dict(data)
    ctx_url.setdefault("en_zone_vulnerable", True)
    champs_url = {q.champ for q in collecter_qc_du_chemin(arbre, ctx_url)}
    assert "detail_apres_sig" not in champs_url

    # AVEC le callback de l'evaluateur (comme la vue) : zone_note_5 est resolu a
    # la volee via code_insee/geo -> le catalogue devient transparent et la QC
    # descendante est prefetchee, sans que zone_note_5 soit dans l'URL.
    resoudre = ev._resoudre_catalogue_pour_collecte
    champs_fix = {
        q.champ for q in collecter_qc_du_chemin(arbre, dict(ctx_url), resoudre)
    }
    assert "plan_epandage" in champs_fix
    assert "detail_apres_sig" in champs_fix
