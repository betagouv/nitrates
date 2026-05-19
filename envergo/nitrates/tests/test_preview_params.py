"""Mapping path admin -> GET params du simulateur (killer feature #80)."""

import pytest

from envergo.nitrates.yaml_admin.preview import (
    build_preview_url,
    compute_simulator_params,
)


@pytest.fixture
def arbre_minimal():
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
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
                            "niveau": "culture",
                            "champ": "occupation_sol",
                            "branches": [
                                {
                                    "valeur": "colza",
                                    "noeud": {
                                        "type_noeud": "formulaire",
                                        "id": "q_colza_fertilisant",
                                        "niveau": "type_fertilisant",
                                        "champ": "type_fertilisant",
                                        "branches": [
                                            {
                                                "valeur": "type_0",
                                                "regle": {
                                                    "id": "r_colza_type_0",
                                                    "type": "interdiction",
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


def test_empty_path(arbre_minimal):
    """Path vide -> juste un point de reference par defaut (Reims, ZV oui)."""
    p = compute_simulator_params(arbre_minimal, ())
    assert "lat" in p and "lng" in p and "code_insee" in p
    # Pas de champ formulaire collecte
    assert "occupation_sol" not in p
    assert "type_fertilisant" not in p


def test_racine_seule(arbre_minimal):
    """Path = (racine,) seule : pas de descente -> point par defaut seul."""
    p = compute_simulator_params(arbre_minimal, ("n_zvn",))
    assert "lat" in p
    assert "occupation_sol" not in p


def test_descente_jusqu_a_culture(arbre_minimal):
    """Path n_zvn -> q_occupation_sol : en_zone_vulnerable=True + point ZV."""
    p = compute_simulator_params(arbre_minimal, ("n_zvn", "q_occupation_sol"))
    assert p["en_zone_vulnerable"] == "True"
    assert p["lat"]  # point ZV ajoute
    assert p["lng"]


def test_descente_jusqu_a_fertilisant(arbre_minimal):
    """Path n_zvn -> q_occupation_sol -> q_colza_fertilisant : on a aussi
    occupation_sol=colza."""
    p = compute_simulator_params(
        arbre_minimal,
        ("n_zvn", "q_occupation_sol", "q_colza_fertilisant"),
    )
    assert p["en_zone_vulnerable"] == "True"
    assert p["occupation_sol"] == "colza"
    assert p["lat"]  # toujours injecte


def test_path_inconnu_fallback(arbre_minimal):
    """Si le path est casse au milieu, on retourne ce qu'on a accumule
    + le point par defaut."""
    p = compute_simulator_params(
        arbre_minimal,
        ("n_zvn", "q_occupation_sol", "q_inexistant_xxx"),
    )
    assert p["en_zone_vulnerable"] == "True"
    assert "lat" in p


def test_path_ne_demarre_pas_racine(arbre_minimal):
    """Si le path ne demarre pas a la racine, on s'abstient (juste point)."""
    p = compute_simulator_params(arbre_minimal, ("q_inexistant",))
    # On a au moins un point de reference (le simulateur n'a rien pour parcourir)
    assert "lat" in p
    assert "occupation_sol" not in p


def test_branche_false_n_zvn():
    """Path qui descend dans la branche False de la racine -> en_zone_vulnerable=False
    et point hors ZV."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
                "branches": [
                    {
                        "valeur": False,
                        "noeud": {
                            "type_noeud": "formulaire",
                            "id": "q_hors",
                            "champ": "raison",
                            "branches": [],
                        },
                    },
                ],
            }
        }
    }
    p = compute_simulator_params(arbre, ("n_zvn", "q_hors"))
    assert p["en_zone_vulnerable"] == "False"
    # Point hors ZV : lat/lng en mer (hors France)
    assert p["lat"] == "30.0"


def test_zone_note_5_picks_toulouse():
    """Si le path passe par une branche `true` d'un nœud catalogue de
    type *_zone_note_5, on choisit un point en Occitanie (Toulouse) qui
    resout zone_note_5=True."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
                "branches": [
                    {
                        "valeur": True,
                        "noeud": {
                            "type_noeud": "catalogue",
                            "id": "n_zone_note_5",
                            "champ": "zone_note_5",
                            "branches": [
                                {
                                    "valeur": True,
                                    "regle": {
                                        "id": "r_note5",
                                        "type": "interdiction",
                                    },
                                },
                                {
                                    "valeur": False,
                                    "regle": {
                                        "id": "r_hors_note5",
                                        "type": "libre",
                                    },
                                },
                            ],
                        },
                    },
                ],
            }
        }
    }
    p = compute_simulator_params(arbre, ("n_zvn", "n_zone_note_5"))
    # Toulouse : Haute-Garonne (31)
    assert p["code_insee"] == "31555"


def test_build_preview_url_format():
    """L'URL est `/simulateur/?draft_tree_id=<pk>&...autres params`."""
    url = build_preview_url(
        tree_pk=42,
        params={"en_zone_vulnerable": "True", "occupation_sol": "colza"},
    )
    assert url.startswith("/simulateur/?")
    assert "draft_tree_id=42" in url
    assert "en_zone_vulnerable=True" in url
    assert "occupation_sol=colza" in url


def test_arbre_vide():
    """Tree vide / None -> dict vide, pas de crash."""
    assert compute_simulator_params({}, ("n_zvn",)) == {}
    assert compute_simulator_params(None, ("n_zvn",)) == {}
