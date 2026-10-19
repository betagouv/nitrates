"""Liens de preview de l'editeur (#584) : le point doit activer l'arbre
previsualise, et la cascade form satisfaire les expressions du chemin."""

from urllib.parse import parse_qsl, urlparse

import pytest
from django.contrib.gis.geos import MultiPolygon, Point, Polygon

from envergo.geodata.models import MAP_TYPES, Department, Map, Zone
from envergo.nitrates.models import DecisionTree
from envergo.nitrates.templatetags.yaml_admin_extras import (
    preview_url,
    preview_url_regle,
)
from envergo.nitrates.yaml_admin.preview import compute_simulator_params

pytestmark = pytest.mark.django_db


def _carre(lng, lat, d=0.2):
    return MultiPolygon(
        Polygon(
            (
                (lng - d, lat - d),
                (lng + d, lat - d),
                (lng + d, lat + d),
                (lng - d, lat + d),
                (lng - d, lat - d),
            )
        ),
        srid=4326,
    )


@pytest.fixture
def geo(db):
    """ZV sur toute la France, departements autour de points connus du
    reservoir (Marne, Cher, Loire), une ZAR en Auvergne-Rhone-Alpes."""
    DecisionTree.objects.all().delete()
    zv = Map.objects.create(
        name="zv", map_type=MAP_TYPES.zv_nitrates, description="", is_active=True
    )
    Zone.objects.create(
        map=zv,
        geometry=MultiPolygon(
            Polygon(((-5, 41), (10, 41), (10, 51.5), (-5, 51.5), (-5, 41))), srid=4326
        ),
    )
    Department.objects.create(department="51", geometry=_carre(4.21806, 49.22298))
    Department.objects.create(department="18", geometry=_carre(2.4601, 47.2828))
    Department.objects.create(department="42", geometry=_carre(4.2378, 45.51245, 0.5))
    zar = Map.objects.create(
        name="zar ara",
        map_type=MAP_TYPES.zone_action_renforcee,
        description="",
        is_active=True,
    )
    Zone.objects.create(map=zar, geometry=_carre(4.2378, 45.51245, 0.05))
    return {"zar": zar}


def _arbre(feuille_id):
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
                        "valeur": False,
                        "regle": {"id": "r_hors", "type": "non_applicable"},
                    },
                    {
                        "valeur": True,
                        "noeud": {
                            "type_noeud": "formulaire",
                            "id": "q_occupation_sol",
                            "champ": "occupation_sol",
                            "niveau": "culture",
                            "branches": [
                                {
                                    "valeur": "sol_non_cultive",
                                    "regle": {"id": feuille_id, "type": "libre"},
                                }
                            ],
                        },
                    },
                ],
            }
        }
    }


def _point(url):
    params = dict(parse_qsl(urlparse(url).query))
    return Point(float(params["lng"]), float(params["lat"]), srid=4326)


def test_zar_hors_grand_est_tombe_dans_sa_propre_couche(geo):
    tree = DecisionTree.objects.create(
        name="zar ara",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_ZAR,
        region_code="84",
        activation_map=geo["zar"],
        weight=20,
        contenu=_arbre("r_zar"),
    )
    url = preview_url_regle(
        tree.contenu, "n_zvn/q_occupation_sol", "sol_non_cultive", tree.pk, "active"
    )
    assert geo["zar"].zones.first().geometry.intersects(_point(url))


def test_feuille_du_pan_evite_la_region_d_un_par_actif(geo):
    pan = DecisionTree.objects.create(
        name="pan", status=DecisionTree.STATUS_ACTIVE, weight=1, contenu=_arbre("r_pan")
    )
    DecisionTree.objects.create(
        name="par ge",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_REGION,
        region_code="44",
        weight=10,
        contenu=_arbre("r_par"),
    )
    url = preview_url(pan.contenu, "n_zvn/q_occupation_sol", pan.pk, "active")
    marne = Department.objects.get(department="51").geometry
    pt = _point(url)
    assert not marne.intersects(pt)
    assert Department.objects.filter(geometry__intersects=pt).exists()


def test_sans_par_actif_le_pan_garde_son_point_historique(geo):
    pan = DecisionTree.objects.create(
        name="pan", status=DecisionTree.STATUS_ACTIVE, weight=1, contenu=_arbre("r_pan")
    )
    url = preview_url(pan.contenu, "n_zvn/q_occupation_sol", pan.pk, "active")
    assert Department.objects.get(department="51").geometry.intersects(_point(url))


def _arbre_expression(expression, champ_qc=None):
    """culture principale > type II > catalogue_parametre (expression)."""
    feuille = {
        "valeur": "oui",
        "expression": expression,
        "regle": {"id": "r_x", "type": "libre"},
    }
    noeud_param = {
        "type_noeud": "catalogue_parametre",
        "id": "n_param",
        "champ": "resolution_param",
        "branches": [feuille],
    }
    branche_type = {"valeur": "type_II", "noeud": noeud_param}
    if champ_qc:
        branche_type = {
            "valeur": "type_II",
            "noeud": {
                "type_noeud": "formulaire",
                "id": "q_qc",
                "champ": champ_qc,
                "niveau": "complement",
                "branches": [{"valeur": True, "noeud": noeud_param}],
            },
        }
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "id": "q_occ",
                "champ": "occupation_sol",
                "niveau": "culture",
                "branches": [
                    {
                        "valeur": "culture_principale",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "id": "q_sc",
                            "champ": "sous_culture",
                            "niveau": "sous_culture",
                            "branches": [
                                {
                                    "valeur": "culture_hiver_hors_colza",
                                    "noeud": {
                                        "type_noeud": "formulaire",
                                        "id": "q_tf",
                                        "champ": "type_fertilisant",
                                        "niveau": "type_fertilisant",
                                        "branches": [branche_type],
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        }
    }


def test_expression_sur_la_categorie_de_fertilisant_est_satisfaite():
    arbre = _arbre_expression("categorie_fertilisant == 'digestats'")
    params = compute_simulator_params(
        arbre,
        ("q_occ", "q_sc", "q_tf", "n_param"),
        leaf_branch=("resolution_param", "oui"),
    )
    assert params["categorie_fertilisant"] == "digestats"
    assert params["type_fertilisant"] == "type_II"


def test_drapeau_effluent_peu_charge_du_chemin_choisit_le_bon_fertilisant():
    arbre = _arbre_expression("True", champ_qc="effluent_peu_charge")
    params = compute_simulator_params(
        arbre,
        ("q_occ", "q_sc", "q_tf", "q_qc", "n_param"),
        leaf_branch=("resolution_param", "oui"),
    )
    assert params["effluent_peu_charge"] == "True"
    assert params["sous_fertilisant"].startswith("effluents_peu_charges")


def test_champ_parametre_homonyme_d_un_drapeau_n_est_pas_un_drapeau():
    # PAR Grand Est : catalogue_parametre `effluent_peu_charge_elevage` (meme
    # nom que le drapeau du fertilisant) avec une etiquette de branche, puis
    # une expression digestats. Le solveur doit trouver un digestat de type II.
    arbre = _arbre_expression("categorie_fertilisant == 'digestats'")
    noeud_tf = arbre["arbre"]["noeud"]["branches"][0]["noeud"]["branches"][0]["noeud"]
    param_digestat = noeud_tf["branches"][0]["noeud"]
    noeud_tf["branches"][0]["noeud"] = {
        "type_noeud": "catalogue_parametre",
        "id": "n_epc",
        "champ": "effluent_peu_charge_elevage",
        "branches": [
            {
                "valeur": "pas_effluent_peu_charge_issus_elevage",
                "expression": "sous_fertilisant != 'effluents_peu_charges_elevage'",
                "noeud": param_digestat,
            }
        ],
    }
    params = compute_simulator_params(
        arbre,
        ("q_occ", "q_sc", "q_tf", "n_epc", "n_param"),
        leaf_branch=("resolution_param", "oui"),
    )
    assert params["categorie_fertilisant"] == "digestats"
