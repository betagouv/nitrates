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


def _evaluateur(**data):
    """Retourne l'evaluateur ArbreDecision pour un contexte de form donne
    (lat/lng Reims par defaut). Permet d'inspecter regle / questions /
    result / arbre_matche selon le cas teste."""
    base = {"lng": LNG_REIMS, "lat": LAT_REIMS}
    base.update(data)
    m = MoulinetteNitrates(form_kwargs={"data": base})
    reg = list(m.regulations)[0]
    crit = list(reg.criteria.all())[0]
    return crit._evaluator


def _regle_id(occupation_sol):
    return _evaluateur(occupation_sol=occupation_sol).regle.regle_id


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


# ─── renvoi_arbre AVEC remap_contexte (issue #227) ─────────────────────────


def _pan_deux_cultures():
    """PAN : racine ZV -> occupation_sol -> sous_culture (2 branches :
    autres_cultures et culture_printemps), chacune -> type_fertilisant.
    Modele minimal du PAN reel : la branche culture_printemps type_II est la
    cible du renvoi remappe depuis le PAR HdF legumes."""

    def _sous_culture_node():
        return {
            "type_noeud": "formulaire",
            "id": "q_sous_culture",
            "champ": "sous_culture",
            "niveau": "sous_culture",
            "texte": "Culture ?",
            "branches": [
                {
                    "valeur": "culture_printemps",
                    "noeud": {
                        "type_noeud": "formulaire",
                        "id": "q_printemps_fert",
                        "champ": "type_fertilisant",
                        "niveau": "type_fertilisant",
                        "texte": "Fertilisant ?",
                        "branches": [
                            _regle("r_pan_printemps_type_II", "type_II"),
                            _regle("r_pan_printemps_type_III", "type_III"),
                        ],
                    },
                },
            ],
        }

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
                            "texte": "Occupation ?",
                            "branches": [
                                {
                                    "valeur": "culture_principale",
                                    "noeud": _sous_culture_node(),
                                }
                            ],
                        },
                    },
                ],
            }
        }
    }


def _par_legumes_renvoi(remap=None, noeud_cible=None):
    """PAR HdF simplifie : racine ZV -> occupation_sol=culture_principale ->
    sous_culture=autres_cultures -> type_fertilisant. La branche type_II fait un
    renvoi_arbre vers le PAN, avec (ou sans) remap_contexte / noeud_cible."""
    branche_type_ii = {"valeur": "type_II", "renvoi_arbre": "national"}
    if remap is not None:
        branche_type_ii["remap_contexte"] = remap
    if noeud_cible is not None:
        branche_type_ii["noeud_cible"] = noeud_cible
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
                            "texte": "Occupation ?",
                            "branches": [
                                {
                                    "valeur": "culture_principale",
                                    "noeud": {
                                        "type_noeud": "formulaire",
                                        "id": "q_sous_culture",
                                        "champ": "sous_culture",
                                        "niveau": "sous_culture",
                                        "texte": "Culture ?",
                                        "branches": [
                                            {
                                                "valeur": "autres_cultures",
                                                "noeud": {
                                                    "type_noeud": "formulaire",
                                                    "id": "q_legumes_fert",
                                                    "champ": "type_fertilisant",
                                                    "niveau": "type_fertilisant",
                                                    "texte": "Fertilisant ?",
                                                    "branches": [branche_type_ii],
                                                },
                                            }
                                        ],
                                    },
                                }
                            ],
                        },
                    },
                ],
            }
        }
    }


def _poser_pan_et_par_renvoi(remap, noeud_cible=None):
    """Pose PAN (2 sous-cultures) + PAR HdF legumes qui renvoie au PAN sur
    type_II avec le remap donne. Region 44 (Reims) pour matcher le PAR."""
    _poser_geo_et_criterion()
    DecisionTree.objects.create(
        name="pan",
        status=DecisionTree.STATUS_ACTIVE,
        weight=1,
        contenu=_pan_deux_cultures(),
    )
    DecisionTree.objects.create(
        name="par",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_REGION,
        region_code="44",
        weight=10,
        contenu=_par_legumes_renvoi(remap, noeud_cible),
    )


@pytest.fixture
def cascade_remap(db):
    """PAR legumes (sous_culture=autres_cultures) renvoie au PAN avec un
    remap_contexte {sous_culture: culture_printemps, type_fertilisant: type_II}.
    Le PAN doit alors atteindre r_pan_printemps_type_II (et NON tomber en
    no-match faute de branche autres_cultures)."""
    _poser_pan_et_par_renvoi(
        {"sous_culture": "culture_printemps", "type_fertilisant": "type_II"}
    )


@pytest.fixture
def cascade_remap_absent(db):
    """Meme scenario SANS remap_contexte : le contexte cumulatif garde
    sous_culture=autres_cultures, que le PAN ne connait pas -> no-match ->
    non_disponible (preuve que sans remap le comportement est INCHANGE)."""
    _poser_pan_et_par_renvoi(None)


def test_renvoi_arbre_avec_remap_atteint_la_bonne_feuille_pan(cascade_remap):
    """Le remap transforme sous_culture=autres_cultures -> culture_printemps et
    pose type_fertilisant=type_II AVANT le re-parcours PAN : on atteint
    r_pan_printemps_type_II (branche que le contexte HdF d'origine ne matchait
    pas)."""
    ev = _evaluateur(
        occupation_sol="culture_principale",
        sous_culture="autres_cultures",
        type_fertilisant="type_II",
    )
    assert ev.regle is not None
    assert ev.regle.regle_id == "r_pan_printemps_type_II"


def test_renvoi_arbre_sans_remap_reste_no_match(cascade_remap_absent):
    """Non-regression : sans remap_contexte, le contexte n'est pas transforme.
    sous_culture=autres_cultures n'a pas de branche PAN -> no-match ->
    non_disponible. Prouve que le mecanisme remap est purement additif."""
    from envergo.evaluations.models import RESULTS

    ev = _evaluateur(
        occupation_sol="culture_principale",
        sous_culture="autres_cultures",
        type_fertilisant="type_II",
    )
    assert ev.regle is None
    assert ev._result == RESULTS.non_disponible


def test_remap_ne_pollue_pas_le_contexte_expose(cascade_remap):
    """Le remap doit s'appliquer sur une COPIE : apres resolution, le contexte
    final expose reflete bien les valeurs remappees (pour l'arbre cible), sans
    avoir mute le contexte d'un autre arbre. On verifie au moins que le contexte
    final porte la valeur remappee, coherente avec la feuille atteinte."""
    ev = _evaluateur(
        occupation_sol="culture_principale",
        sous_culture="autres_cultures",
        type_fertilisant="type_II",
    )
    assert ev.contexte.get("sous_culture") == "culture_printemps"
    assert ev.contexte.get("type_fertilisant") == "type_II"


@pytest.fixture
def cascade_noeud_cible(db):
    """PAR legumes renvoie au PAN en ciblant DIRECTEMENT le noeud
    q_printemps_fert (le fertilisant sous culture_printemps), sans re-parcourir
    le PAN depuis sa racine. Pas besoin de remapper sous_culture : on atterrit
    apres ce niveau. Le PAN doit atteindre r_pan_printemps_type_II."""
    _poser_pan_et_par_renvoi(remap=None, noeud_cible="q_printemps_fert")


def test_renvoi_arbre_noeud_cible_atterrit_directement(cascade_noeud_cible):
    """#222 : renvoi_arbre + noeud_cible fait demarrer le parcours de l'arbre
    cible AU noeud indique (q_printemps_fert), pas a sa racine. type_fertilisant
    etant deja dans le contexte, on atteint directement r_pan_printemps_type_II
    sans re-poser occupation_sol / sous_culture."""
    ev = _evaluateur(
        occupation_sol="culture_principale",
        sous_culture="autres_cultures",
        type_fertilisant="type_II",
    )
    assert ev.regle is not None
    assert ev.regle.regle_id == "r_pan_printemps_type_II"


# ─── Helpers communs aux fixtures cascade (geo + criterion) ────────────────


def _poser_geo_et_criterion(zar_bbox=BBOX_MARNE):
    """Pose le decor commun : departement Marne, ZV couvrante, couche ZAR
    (bbox parametrable), regulation + criterion directive_nitrates. Retourne
    (zv, zar_map). Factorise ce que chaque fixture cascade reconstruisait."""
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
    Zone.objects.create(map=zar_map, geometry=MultiPolygon(Polygon.from_bbox(zar_bbox)))
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
    return zv, zar_map


# ─── Axe 1 : report d'une vraie feuille_vide vers l'arbre inferieur ────────


@pytest.fixture
def cascade_feuille_vide(db):
    """ZAR couvre prairie via une feuille_vide EXPLICITE (pas une branche
    absente). Au runtime, feuille_vide = no-match -> la cascade doit reporter
    sur le PAN. Verifie le report via le vrai mecanisme feuille_vide, distinct
    du fallback par branche manquante deja couvert plus haut."""
    _, zar_map = _poser_geo_et_criterion()
    DecisionTree.objects.create(
        name="pan",
        status=DecisionTree.STATUS_ACTIVE,
        weight=1,
        contenu=_noeud_occupation([_regle("r_pan_prairie", "prairie")]),
    )
    DecisionTree.objects.create(
        name="zar",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_ZAR,
        region_code="44",
        activation_map=zar_map,
        weight=20,
        contenu=_noeud_occupation([{"valeur": "prairie", "feuille_vide": True}]),
    )


def test_feuille_vide_zar_reporte_sur_pan(cascade_feuille_vide):
    """ZAR prairie = feuille_vide -> report jusqu'au PAN (r_pan_prairie)."""
    assert _regle_id("prairie") == "r_pan_prairie"


# ─── Axe 2 : questions subsidiaires de l'arbre prioritaire priment ─────────


@pytest.fixture
def cascade_qc_priment(db):
    """ZAR prioritaire pose une QUESTION sur prairie (sous-noeud formulaire
    'fertirrigation' dont la valeur n'est pas dans le contexte) ; le PAN
    couvre prairie directement. La QC du ZAR doit PRIMER : l'evaluateur
    retourne des questions subsidiaires (arbre_matche = ZAR), il ne retombe
    PAS sur le resultat du PAN."""
    _, zar_map = _poser_geo_et_criterion()
    DecisionTree.objects.create(
        name="pan",
        status=DecisionTree.STATUS_ACTIVE,
        weight=1,
        contenu=_noeud_occupation([_regle("r_pan_prairie", "prairie")]),
    )
    # ZAR : prairie -> sous-question 'fertirrigation' (non repondue).
    zar_branche = {
        "valeur": "prairie",
        "noeud": {
            "type_noeud": "formulaire",
            "id": "q_fertirrigation",
            "champ": "fertirrigation",
            "niveau": "complement",
            "texte": "Fertirrigation ?",
            "branches": [
                _regle("r_zar_prairie_ferti", "oui"),
                _regle("r_zar_prairie_non_ferti", "non"),
            ],
        },
    }
    DecisionTree.objects.create(
        name="zar",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_ZAR,
        region_code="44",
        activation_map=zar_map,
        weight=20,
        contenu=_noeud_occupation([zar_branche]),
    )


def test_questions_subsidiaires_zar_priment_sur_pan(cascade_qc_priment):
    """L'arbre prioritaire (ZAR) qui pose une QC prime : on recoit la question,
    pas le resultat du PAN. Regression : si le fallback se declenchait a tort,
    on obtiendrait r_pan_prairie au lieu d'une question."""
    ev = _evaluateur(occupation_sol="prairie")
    # On a une question subsidiaire en attente, pas une regle finale.
    assert ev.questions_subsidiaires is not None
    champs = [q.champ for q in ev.questions_subsidiaires.questions]
    assert "fertirrigation" in champs
    # L'arbre qui a produit la question est bien le ZAR (le prioritaire),
    # pas le PAN.
    assert ev.arbre_matche is not None
    assert ev.arbre_matche.scope == DecisionTree.SCOPE_ZAR


def test_qc_repondue_zar_resout_sans_fallback(cascade_qc_priment):
    """Meme arbre, QC fertirrigation repondue : le ZAR resout sa feuille,
    toujours sans toucher au PAN."""
    rid = _evaluateur(occupation_sol="prairie", fertirrigation="oui").regle.regle_id
    assert rid == "r_zar_prairie_ferti"


# ─── Axe 4 : renvoi_arbre vers un scope sans arbre actif ───────────────────


@pytest.fixture
def cascade_renvoi_scope_absent(db):
    """ZAR renvoie 'renvoi_arbre: region' sur prairie, mais AUCUN arbre PAR
    (region) n'est actif. Le renvoi doit echouer proprement -> non_disponible,
    pas de crash ni de fallback silencieux sur le PAN."""
    _, zar_map = _poser_geo_et_criterion()
    # PAN present mais le renvoi explicite cible 'region' (absent), donc on ne
    # doit PAS y retomber.
    DecisionTree.objects.create(
        name="pan",
        status=DecisionTree.STATUS_ACTIVE,
        weight=1,
        contenu=_noeud_occupation([_regle("r_pan_prairie", "prairie")]),
    )
    DecisionTree.objects.create(
        name="zar",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_ZAR,
        region_code="44",
        activation_map=zar_map,
        weight=20,
        contenu=_noeud_occupation([{"valeur": "prairie", "renvoi_arbre": "region"}]),
    )


def test_renvoi_arbre_vers_scope_absent_non_disponible(cascade_renvoi_scope_absent):
    """renvoi_arbre vers un scope sans arbre actif -> non_disponible."""
    from envergo.moulinette.models import RESULTS

    ev = _evaluateur(occupation_sol="prairie")
    assert ev.result == RESULTS.non_disponible
