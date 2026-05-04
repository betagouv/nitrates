"""Tests de la grammaire d'edition (validation locale + allowed children).

Module independant de Django : tests unitaires sur des dicts. On marque
quand meme django_db pour cohabiter avec la fixture session-autouse qui
configure le Site testserver (cf envergo/conftest.py).
"""

import pytest

from envergo.nitrates.yaml_admin.grammar import (
    get_allowed_child_kinds,
    validate_node_local,
)

pytestmark = pytest.mark.django_db


# Arbre de reference pour les tests de contexte.
SAMPLE_ARBRE = {
    "arbre": {
        "noeud": {
            "type_noeud": "catalogue",
            "id": "n_root",
            "champ": "z",
            "source": "sig",
            "branches": [
                {
                    "valeur": True,
                    "noeud": {
                        "type_noeud": "formulaire",
                        "niveau": "culture",
                        "id": "q_culture",
                        "champ": "c",
                        "texte": "Culture ?",
                        "branches": [
                            {
                                "valeur": "colza",
                                "noeud": {
                                    "type_noeud": "formulaire",
                                    "niveau": "type_fertilisant",
                                    "id": "q_fert",
                                    "champ": "f",
                                    "texte": "Fert ?",
                                    "branches": [
                                        {
                                            "valeur": "type_0",
                                            "regle": {
                                                "id": "r_t0",
                                                "type": "interdiction",
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


# ─── validate_node_local : noeud formulaire ─────────────────────────────────


def test_noeud_formulaire_valide():
    data = {
        "id": "q_test",
        "niveau": "culture",
        "texte": "Quelle culture ?",
        "champ": "culture",
    }
    res = validate_node_local(data, "noeud_formulaire")
    assert res.ok


def test_noeud_formulaire_id_invalide():
    data = {"id": "wrong_id", "niveau": "culture", "texte": "x", "champ": "c"}
    res = validate_node_local(data, "noeud_formulaire")
    assert not res.ok
    fields = [e.field for e in res.errors]
    assert "id" in fields


def test_noeud_formulaire_niveau_inconnu():
    data = {
        "id": "q_test",
        "niveau": "inexistant",
        "texte": "x",
        "champ": "c",
    }
    res = validate_node_local(data, "noeud_formulaire")
    assert not res.ok
    assert any(e.field == "niveau" for e in res.errors)


def test_noeud_formulaire_champs_requis():
    res = validate_node_local({}, "noeud_formulaire")
    fields = {e.field for e in res.errors}
    assert {"id", "niveau", "texte", "champ"} <= fields


# ─── validate_node_local : noeud catalogue ──────────────────────────────────


def test_noeud_catalogue_valide():
    data = {"id": "n_x", "champ": "y", "source": "sig"}
    res = validate_node_local(data, "noeud_catalogue")
    assert res.ok


def test_noeud_catalogue_source_inconnue():
    data = {"id": "n_x", "champ": "y", "source": "fictif"}
    res = validate_node_local(data, "noeud_catalogue")
    assert not res.ok
    assert any(e.field == "source" for e in res.errors)


def test_noeud_catalogue_id_invalide():
    data = {"id": "q_wrong_prefix", "champ": "c", "source": "sig"}
    res = validate_node_local(data, "noeud_catalogue")
    assert not res.ok


# ─── validate_node_local : regle ────────────────────────────────────────────


def test_regle_interdiction_valide():
    data = {"id": "r_x", "type": "interdiction"}
    res = validate_node_local(data, "regle")
    assert res.ok


def test_regle_a_completer_sans_type_ok():
    """Une regle marquee a_completer peut ne pas avoir de type encore."""
    data = {"id": "r_todo", "a_completer": True}
    res = validate_node_local(data, "regle")
    assert res.ok


def test_regle_sans_type_ni_a_completer_ko():
    data = {"id": "r_x"}
    res = validate_node_local(data, "regle")
    assert not res.ok
    assert any(e.field == "type" for e in res.errors)


def test_regle_id_invalide():
    data = {"id": "wrong", "type": "interdiction"}
    res = validate_node_local(data, "regle")
    assert not res.ok


def test_regle_type_inconnu():
    data = {"id": "r_x", "type": "fictif"}
    res = validate_node_local(data, "regle")
    assert not res.ok
    assert any(e.field == "type" for e in res.errors)


def test_regle_periode_date_invalide():
    data = {
        "id": "r_x",
        "type": "interdiction",
        "periodes": [{"du": "32/13", "au": "01/01"}],
    }
    res = validate_node_local(data, "regle")
    assert not res.ok
    assert any("periodes" in e.field for e in res.errors)


def test_regle_periode_evenement_phenologique_accepte_localement():
    """Localement on accepte tout texte non JJ/MM (verifie en deep
    validate avec referentiels)."""
    data = {
        "id": "r_x",
        "type": "interdiction",
        "periodes": [{"du": "brunissement_soies", "au": "15/02"}],
    }
    res = validate_node_local(data, "regle")
    assert res.ok


# ─── validate_node_local : branche ──────────────────────────────────────────


def test_branche_avec_juste_valeur_ok():
    """Squelette draft : on accepte une branche sans contenu."""
    res = validate_node_local({"valeur": "x"}, "branche")
    assert res.ok


def test_branche_sans_valeur_ko():
    res = validate_node_local({}, "branche")
    assert not res.ok
    assert any(e.field == "valeur" for e in res.errors)


def test_branche_double_contenu_ko():
    """noeud + regle simultanement : interdit."""
    data = {
        "valeur": "x",
        "noeud": {"id": "q_x"},
        "regle": {"id": "r_x"},
    }
    res = validate_node_local(data, "branche")
    assert not res.ok


# ─── validate_node_local : renvoi_vers ──────────────────────────────────────


def test_renvoi_vers_cible_existe():
    data = {"renvoi_vers": "r_t0"}
    res = validate_node_local(data, "renvoi_vers", arbre=SAMPLE_ARBRE)
    assert res.ok


def test_renvoi_vers_cible_inexistante():
    data = {"renvoi_vers": "r_inexistant"}
    res = validate_node_local(data, "renvoi_vers", arbre=SAMPLE_ARBRE)
    assert not res.ok
    assert any(e.field == "renvoi_vers" for e in res.errors)


# ─── Unicite d'id ────────────────────────────────────────────────────────────


def test_id_collision_dans_arbre_ko():
    """Un nouveau noeud avec l'id d'un noeud deja present : refus."""
    data = {
        "id": "q_culture",
        "niveau": "culture",
        "texte": "x",
        "champ": "c",
    }
    res = validate_node_local(data, "noeud_formulaire", arbre=SAMPLE_ARBRE)
    assert not res.ok
    assert any(e.field == "id" and "deja" in e.message.lower() for e in res.errors)


def test_id_garde_son_propre_id_lors_dun_edit():
    """Quand on edite un noeud existant, son id ne doit pas declencher
    une fausse collision avec lui-meme."""
    data = {
        "id": "q_culture",
        "niveau": "culture",
        "texte": "x",
        "champ": "c",
    }
    res = validate_node_local(
        data,
        "noeud_formulaire",
        arbre=SAMPLE_ARBRE,
        own_path=("n_root", "q_culture"),
    )
    assert res.ok


# ─── get_allowed_child_kinds ───────────────────────────────────────────────


def test_allowed_kinds_sur_racine_catalogue():
    """Sur la racine catalogue, on autorise tous les niveaux formulaire
    + autres."""
    allowed = get_allowed_child_kinds(SAMPLE_ARBRE, ("n_root",))
    # On peut toujours mettre un catalogue, une regle, un renvoi
    assert "noeud_catalogue" in allowed
    assert "regle" in allowed
    assert "renvoi_vers" in allowed
    # Et tous les niveaux formulaire (rien n'est encore vu)
    assert "noeud_formulaire_culture" in allowed
    assert "noeud_formulaire_sous_culture" in allowed


def test_allowed_kinds_sous_culture():
    """Sous un noeud culture, on n'autorise plus culture (deja vu) mais
    sous_culture, type_fertilisant, complement OK."""
    allowed = get_allowed_child_kinds(SAMPLE_ARBRE, ("n_root", "q_culture"))
    assert "noeud_formulaire_culture" not in allowed
    assert "noeud_formulaire_sous_culture" in allowed
    assert "noeud_formulaire_type_fertilisant" in allowed
    assert "noeud_formulaire_complement" in allowed


def test_allowed_kinds_sous_type_fertilisant():
    """Apres culture + type_fertilisant : ni culture ni sous_culture autorises.
    type_fertilisant deja vu = interdit. complement OK."""
    allowed = get_allowed_child_kinds(SAMPLE_ARBRE, ("n_root", "q_culture", "q_fert"))
    assert "noeud_formulaire_culture" not in allowed
    assert "noeud_formulaire_sous_culture" not in allowed
    assert "noeud_formulaire_type_fertilisant" not in allowed
    assert "noeud_formulaire_complement" in allowed
    assert "regle" in allowed


def test_allowed_kinds_complement_repetable():
    """Le niveau complement peut se chainer 0..N fois."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "complement",
                "id": "q_c1",
                "champ": "c1",
                "texte": "x",
                "branches": [
                    {
                        "valeur": True,
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "complement",
                            "id": "q_c2",
                            "champ": "c2",
                            "texte": "y",
                            "branches": [],
                        },
                    }
                ],
            }
        }
    }
    allowed = get_allowed_child_kinds(arbre, ("q_c1", "q_c2"))
    assert "noeud_formulaire_complement" in allowed


def test_allowed_kinds_chemin_invalide():
    """Chemin qui ne correspond a aucun noeud : aucune insertion possible."""
    allowed = get_allowed_child_kinds(SAMPLE_ARBRE, ("inexistant",))
    assert allowed == []
