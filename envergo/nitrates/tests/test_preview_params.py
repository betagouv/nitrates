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
    """Path vide -> dict vide."""
    assert compute_simulator_params(arbre_minimal, ()) == {}


def test_racine_seule(arbre_minimal):
    """Path = (racine,) seule -> dict vide (rien a accumuler)."""
    assert compute_simulator_params(arbre_minimal, ("n_zvn",)) == {}


def test_descente_jusqu_a_culture(arbre_minimal):
    """Path n_zvn -> q_occupation_sol : on collecte en_zone_vulnerable=True."""
    params = compute_simulator_params(arbre_minimal, ("n_zvn", "q_occupation_sol"))
    assert params == {"en_zone_vulnerable": "True"}


def test_descente_jusqu_a_fertilisant(arbre_minimal):
    """Path n_zvn -> q_occupation_sol -> q_colza_fertilisant : on a aussi
    occupation_sol=colza."""
    params = compute_simulator_params(
        arbre_minimal,
        ("n_zvn", "q_occupation_sol", "q_colza_fertilisant"),
    )
    assert params == {
        "en_zone_vulnerable": "True",
        "occupation_sol": "colza",
    }


def test_path_inconnu_fallback(arbre_minimal):
    """Si le path est casse au milieu, on retourne ce qu'on a accumule."""
    params = compute_simulator_params(
        arbre_minimal,
        ("n_zvn", "q_occupation_sol", "q_inexistant_xxx"),
    )
    assert params == {"en_zone_vulnerable": "True"}


def test_path_ne_demarre_pas_racine(arbre_minimal):
    """Si le path ne demarre pas a la racine, on s'abstient."""
    assert compute_simulator_params(arbre_minimal, ("q_inexistant",)) == {}


def test_branche_false_n_zvn(arbre_minimal):
    """Path qui descend dans la branche False de la racine -> on en_zone_vulnerable=False."""
    # Ici la branche False n'a pas de noeud (elle a une regle), donc on
    # ne descend pas mais on a quand meme enregistre la valeur.
    # On simule un path qui essaie d'aller plus loin -> break, retourne
    # ce qu'on a (rien, car la racine est catalogue et on n'a pas trouve
    # de branche menant a un noeud d'id "inexistant").
    # En pratique on testera plutot un arbre avec un sous-noeud sous false.
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
    params = compute_simulator_params(arbre, ("n_zvn", "q_hors"))
    assert params == {"en_zone_vulnerable": "False"}


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
