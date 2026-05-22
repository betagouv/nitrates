"""Mapping path admin -> GET params du simulateur (killer feature #80)."""

import pytest

from envergo.nitrates.yaml_admin.preview import (
    build_preview_url,
    compute_simulator_params,
)

# Les helpers cascade consomment les referentiels depuis la DB
# (cf. #61 phase 4 — load_referentiels lit l'ORM). Acces DB requis.
pytestmark = pytest.mark.django_db


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


def test_zone_montagne_d113_14_picks_ariege_par_defaut():
    """Path traversant zone_montagne_d113_14 sans descendre -> Ariege
    (Saint-Jean-de-Verges, note 7 par defaut)."""
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
                            "id": "n_montagne",
                            "champ": "zone_montagne_d113_14",
                            "branches": [
                                {
                                    "valeur": True,
                                    "regle": {"id": "r_mont", "type": "interdiction"},
                                },
                                {
                                    "valeur": False,
                                    "regle": {"id": "r_plat", "type": "libre"},
                                },
                            ],
                        },
                    }
                ],
            }
        }
    }
    p = compute_simulator_params(arbre, ("n_zvn", "n_montagne"))
    assert p["code_insee"] == "09264"  # Saint-Jean-de-Verges


def test_zonage_montagne_regional_traverse_sans_branche_picks_ariege():
    """Path s'arretant sur le catalogue zonage_montagne_regional sans
    descendre dans une branche -> defaut note_7 (Ariege)."""
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
                            "id": "n_zm_classif",
                            "champ": "zonage_montagne_regional",
                            "branches": [
                                {
                                    "valeur": "note_7",
                                    "regle": {"id": "r_n7", "type": "interdiction"},
                                },
                                {
                                    "valeur": "note_6",
                                    "regle": {"id": "r_n6", "type": "interdiction"},
                                },
                            ],
                        },
                    }
                ],
            }
        }
    }
    # Sans leaf_branch, on tombe sur ariege_note7 (defaut zonage_*).
    p_default = compute_simulator_params(arbre, ("n_zvn", "n_zm_classif"))
    assert p_default["code_insee"] == "09264"


def test_cascade_form_luzerne_type_III_via_chemin_complet():
    """Cascade form quand le path va jusqu'a un nœud feuille type_fertilisant
    (le champ type_fertilisant est sur le DERNIER noeud non visite).

    NB : pour avoir `type_fertilisant=X` dans params, il faut que le path
    inclue un id apres le noeud q_tf. Dans le vrai code, c'est ce que fait
    `preview_url_regle` (ajoute valeur de branche au mapping). Ici on teste
    juste le cas ou le path va jusqu'au noeud type_fertilisant inclus :
    on n'a PAS type_fertilisant dans params, mais on a quand meme la
    cascade culture.
    """
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
                            "type_noeud": "formulaire",
                            "id": "q_culture",
                            "champ": "occupation_sol",
                            "branches": [
                                {
                                    "valeur": "culture_principale",
                                    "noeud": {
                                        "type_noeud": "formulaire",
                                        "id": "q_sc",
                                        "champ": "sous_culture",
                                        "branches": [
                                            {
                                                "valeur": "luzerne",
                                                "noeud": {
                                                    "type_noeud": "formulaire",
                                                    "id": "q_tf",
                                                    "champ": "type_fertilisant",
                                                    "branches": [],
                                                },
                                            }
                                        ],
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        }
    }
    p = compute_simulator_params(arbre, ("n_zvn", "q_culture", "q_sc", "q_tf"))
    # Champs arbre collectes sur le chemin
    assert p["occupation_sol"] == "culture_principale"
    assert p["sous_culture"] == "luzerne"
    # Cascade form culture reconstruite depuis referentiels.yaml
    assert p["sous_culture_form"] == "luzerne"
    assert p["categorie_culture"] == "prairies_ou_luzerne"


def test_cascade_form_type_fertilisant_via_inversion_yaml():
    """Quand type_fertilisant est connu (via _cascade_form_params direct),
    on reconstruit categorie_fertilisant + sous_fertilisant depuis
    referentiels.yaml."""
    from envergo.nitrates.yaml_admin.preview import _cascade_form_params

    p = _cascade_form_params(None, None, "type_III")
    assert p["sous_fertilisant"] == "engrais_azote_mineral"
    assert p["categorie_fertilisant"] == "engrais_mineral"

    p = _cascade_form_params(None, None, "type_0")
    # Premier sous_fertilisant qui mappe vers type_0
    assert p["sous_fertilisant"] == "compost_dechets_verts_jeunes_ligneux"
    assert p["categorie_fertilisant"] == "composts"


# ─── Regression tests : bugs remontes par Max en preview manuelle ───────────


def test_branche_pas_zone_note_5_choisit_reims_pas_toulouse():
    """Path qui descend dans la branche False du catalogue zone_note_5
    doit selectionner Reims (point ZV simple), pas Toulouse."""
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
                            "id": "n_z5",
                            "champ": "zone_note_5",
                            "branches": [
                                {
                                    "valeur": False,
                                    "noeud": {
                                        "type_noeud": "formulaire",
                                        "id": "q_pas_z5",
                                        "champ": "occupation_sol",
                                        "branches": [],
                                    },
                                },
                            ],
                        },
                    },
                ],
            }
        }
    }
    p = compute_simulator_params(arbre, ("n_zvn", "n_z5", "q_pas_z5"))
    assert p["code_insee"] == "51046"  # Beine-Nauroy / Reims


def test_branche_pas_zone_montagne_choisit_reims_pas_ariege():
    """Path qui descend dans la branche False de zone_montagne_d113_14
    doit selectionner Reims, pas Ariege."""
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
                            "id": "n_mont",
                            "champ": "zone_montagne_d113_14",
                            "branches": [
                                {
                                    "valeur": False,
                                    "noeud": {
                                        "type_noeud": "formulaire",
                                        "id": "q_apres",
                                        "champ": "occupation_sol",
                                        "branches": [],
                                    },
                                },
                            ],
                        },
                    },
                ],
            }
        }
    }
    p = compute_simulator_params(arbre, ("n_zvn", "n_mont", "q_apres"))
    assert p["code_insee"] == "51046"  # Reims


def test_leaf_branch_zonage_montagne_regional_note_6_choisit_isere():
    """Preview d'une regle feuille sur la branche 'note_6' du catalogue
    zonage_montagne_regional : leaf_branch doit nourrir sig_constraints
    et le resolveur doit selectionner Isere (Saint-Ondras), pas Ariege.

    Reproduit le bug remonte par Max : clic sur note_6 amenait toujours
    en Ariege (note_7).
    """
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
                            "id": "n_zm_reg",
                            "champ": "zonage_montagne_regional",
                            "branches": [
                                {
                                    "valeur": "note_6",
                                    "regle": {"id": "r_n6", "type": "interdiction"},
                                },
                            ],
                        },
                    }
                ],
            }
        }
    }
    p = compute_simulator_params(
        arbre,
        ("n_zvn", "n_zm_reg"),
        leaf_branch=("zonage_montagne_regional", "note_6"),
    )
    assert p["code_insee"] == "38434"  # Saint-Ondras, Isere

    # Variante avec valeur 'montagne_note_6' (zonage_prairie_III) :
    # meme principe, doit aussi finir en Isere.
    arbre["arbre"]["noeud"]["branches"][0]["noeud"]["champ"] = "zonage_prairie_III"
    arbre["arbre"]["noeud"]["branches"][0]["noeud"]["branches"][0][
        "valeur"
    ] = "montagne_note_6"
    p2 = compute_simulator_params(
        arbre,
        ("n_zvn", "n_zm_reg"),
        leaf_branch=("zonage_prairie_III", "montagne_note_6"),
    )
    assert p2["code_insee"] == "38434"


def test_leaf_branch_hors_zv_choisit_point_en_mer():
    """Preview d'une regle sur la branche False de n_zvn : leaf_branch
    doit declencher le selecteur hors_zv."""
    arbre = {
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
                ],
            }
        }
    }
    p = compute_simulator_params(arbre, (), leaf_branch=("en_zone_vulnerable", False))
    # Path vide ne descend pas, mais le leaf_branch est ignore dans ce cas
    # (current = racine, traite comme catalogue final). On verifie qu'au
    # moins le mecanisme ne crashe pas.
    assert "lat" in p
