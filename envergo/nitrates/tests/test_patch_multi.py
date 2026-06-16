"""Patch multi-remap : plusieurs PC remappes vers plusieurs autres (#142)."""

import pytest

from envergo.nitrates.yaml_tree.parcours import parcours

pytestmark = pytest.mark.django_db


def _arbre(patch):
    cible = {
        "type_noeud": "formulaire",
        "id": "n_cible",
        "champ": "x",
        "niveau": "complement",
        "texte": "?",
        "branches": [
            {
                "valeur": "v1",
                "regle": {
                    "id": "r1",
                    "type": "plafonnement",
                    "code_prescription": "pc12",
                },
            },
            {
                "valeur": "v2",
                "regle": {
                    "id": "r2",
                    "type": "plafonnement",
                    "code_prescription": "pc13",
                },
            },
        ],
    }
    q = {
        "type_noeud": "formulaire",
        "id": "q",
        "champ": "tf",
        "niveau": "type_fertilisant",
        "texte": "?",
        "branches": [
            {"valeur": "a", "noeud": cible},
            {"valeur": "b", "renvoi_vers": "n_cible", "patch": patch},
        ],
    }
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
                "branches": [{"valeur": True, "noeud": q}],
            }
        }
    }


def test_multi_remap():
    """Un patch peut remapper plusieurs PC d'un coup (data structure = dict)."""
    a = _arbre({"code_prescription": {"pc12": "pc14", "pc13": "pc16"}})
    r1 = parcours(a, {"en_zone_vulnerable": True, "tf": "b", "x": "v1"})
    r2 = parcours(a, {"en_zone_vulnerable": True, "tf": "b", "x": "v2"})
    assert r1.code_prescription == "pc14"
    assert r2.code_prescription == "pc16"
