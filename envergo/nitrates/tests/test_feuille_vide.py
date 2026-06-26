"""Type de feuille `feuille_vide` + `renvoi_arbre` : runtime, validation, editeur."""

import pytest

from envergo.nitrates.yaml_tree.parcours import ParcoursError, parcours
from envergo.nitrates.yaml_tree.validator import ValidationError, validate_arbre

pytestmark = pytest.mark.django_db


def _arbre(branche_false):
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
                            "id": "q_f",
                            "champ": "f",
                            "niveau": "complement",
                            "texte": "?",
                            "branches": [
                                {
                                    "valeur": True,
                                    "regle": {
                                        "id": "r_ok",
                                        "type": "interdiction",
                                        "periodes": [
                                            {
                                                "du": "01/07",
                                                "au": "15/02",
                                                "regime": "interdiction",
                                            }
                                        ],
                                    },
                                },
                                branche_false,
                            ],
                        },
                    }
                ],
            }
        }
    }


# ─── Runtime ────────────────────────────────────────────────────────────────


def test_feuille_vide_leve_parcours_error():
    """feuille_vide atteinte -> ParcoursError (= no-match -> fallback cascade)."""
    arbre = _arbre({"valeur": False, "feuille_vide": True})
    with pytest.raises(ParcoursError, match="feuille_vide"):
        parcours(arbre, {"en_zone_vulnerable": True, "f": False})


# ─── Validation ───────────────────────────────────────────────────────────


def test_feuille_vide_autorisee_zar_region():
    arbre = _arbre({"valeur": False, "feuille_vide": True})
    for scope in ("zar", "region"):
        try:
            validate_arbre(arbre, scope=scope)
        except ValidationError as e:
            assert not any("feuille_vide" in m for m in e.errors), e.errors


def test_feuille_vide_interdite_pan():
    arbre = _arbre({"valeur": False, "feuille_vide": True})
    with pytest.raises(ValidationError) as exc:
        validate_arbre(arbre, scope="national")
    assert any("feuille_vide" in m for m in exc.value.errors)


# ─── Editeur (grammar) ──────────────────────────────────────────────────────


def test_editeur_allowed_et_validation():
    from envergo.nitrates.yaml_admin import grammar

    arbre = _arbre({"valeur": False, "regle": {"id": "r_x"}})
    allowed = grammar.get_allowed_child_kinds(arbre, ("n_zvn", "q_f"))
    assert "feuille_vide" in allowed
    assert "renvoi_arbre" in allowed
    assert grammar.validate_node_local({"feuille_vide": True}, "feuille_vide").ok
    assert grammar.validate_node_local({"renvoi_arbre": "region"}, "renvoi_arbre").ok
    assert not grammar.validate_node_local({"renvoi_arbre": "xxx"}, "renvoi_arbre").ok
