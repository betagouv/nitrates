"""Patch des prescriptions conditionnees sur une branche renvoi_vers (#142)."""

import pytest

from envergo.nitrates.yaml_tree.parcours import Resultat, parcours

pytestmark = pytest.mark.django_db


def _arbre():
    return {
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
                            "id": "q_occ",
                            "champ": "occupation_sol",
                            "niveau": "culture",
                            "texte": "?",
                            "branches": [
                                {
                                    "valeur": "cine_a",
                                    "noeud": {
                                        "type_noeud": "formulaire",
                                        "id": "n_cine_avant3112",
                                        "champ": "tf",
                                        "niveau": "type_fertilisant",
                                        "texte": "?",
                                        "branches": [
                                            {
                                                "valeur": "type_II",
                                                "regle": {
                                                    "id": "r_cine_ii",
                                                    "type": "plafonnement",
                                                    "code_prescription": "pc12",
                                                },
                                            }
                                        ],
                                    },
                                },
                                {
                                    "valeur": "cie_b",
                                    "renvoi_vers": "n_cine_avant3112",
                                    "patch": {"code_prescription": {"pc12": "pc14"}},
                                },
                            ],
                        },
                    }
                ],
            }
        }
    }


def test_sans_patch_pc_inchange():
    r = parcours(
        _arbre(),
        {"en_zone_vulnerable": True, "occupation_sol": "cine_a", "tf": "type_II"},
    )
    assert isinstance(r, Resultat)
    assert r.code_prescription == "pc12"


def test_patch_remap_pc12_vers_pc14():
    """La branche renvoi_vers + patch reutilise le sous-arbre mais remappe
    pc12 -> pc14 sur la feuille atteinte."""
    r = parcours(
        _arbre(),
        {"en_zone_vulnerable": True, "occupation_sol": "cie_b", "tf": "type_II"},
    )
    assert isinstance(r, Resultat)
    assert r.regle_id == "r_cine_ii"  # meme feuille (sous-arbre reutilise)
    assert r.code_prescription == "pc14"  # mais PC remappe
