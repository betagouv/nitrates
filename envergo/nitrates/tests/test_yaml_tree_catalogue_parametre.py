"""Tests de la resolution runtime des noeuds catalogue_parametre (#128).

Couvre :
  - chaque branche prise selon l'expression vraie (premiere l'emporte)
  - aucune expression vraie => ParcoursError
  - expression cassee (exception) => branche consideree fausse, on continue
  - la valeur de tracabilite est ecrite dans le contexte
  - renvoi_vers depuis une branche catalogue_parametre
  - enumeration des feuilles : toutes les branches explorees

Pas de DB : on construit des arbres jouets et on appelle parcours() direct.
"""

import pytest

from envergo.nitrates.yaml_tree.feuilles import enumerer_feuilles_culture_principale_v2
from envergo.nitrates.yaml_tree.parcours import ParcoursError, Resultat, parcours


def _arbre_origine_effluent() -> dict:
    """Arbre jouet minimal : racine = catalogue_parametre sur l'origine
    elevage de l'effluent, resolu par le sous_fertilisant choisi (cas #98
    de la spec §7, sans branche defaut)."""
    return {
        "metadata": {"version": "test"},
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue_parametre",
                "id": "q_origine",
                "champ": "effluent_peu_charge_elevage",
                "texte": "Origine elevage (resolue par le fertilisant)",
                "branches": [
                    {
                        "expression": (
                            "sous_fertilisant == 'effluents_peu_charges_elevage'"
                        ),
                        "valeur": True,
                        "regle": {
                            "id": "r_origine_elevage",
                            "type": "interdiction",
                            "periodes": [{"du": "15/10", "au": "31/01"}],
                        },
                    },
                    {
                        "expression": (
                            "sous_fertilisant == 'effluents_peu_charges_non_elevage'"
                        ),
                        "valeur": False,
                        "regle": {
                            "id": "r_origine_non_elevage",
                            "type": "libre",
                        },
                    },
                ],
            }
        },
    }


# ─── Resolution par expression ──────────────────────────────────────────────


def test_premiere_branche_prise_si_elevage():
    arbre = _arbre_origine_effluent()
    ctx = {"sous_fertilisant": "effluents_peu_charges_elevage"}
    res = parcours(arbre, ctx)
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_origine_elevage"


def test_seconde_branche_prise_si_non_elevage():
    arbre = _arbre_origine_effluent()
    ctx = {"sous_fertilisant": "effluents_peu_charges_non_elevage"}
    res = parcours(arbre, ctx)
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_origine_non_elevage"


def test_aucune_expression_vraie_leve_parcours_error():
    arbre = _arbre_origine_effluent()
    ctx = {"sous_fertilisant": "fumier_volaille"}  # ni l'un ni l'autre
    with pytest.raises(ParcoursError) as exc:
        parcours(arbre, ctx)
    assert "catalogue_parametre" in str(exc.value)


def test_contexte_absent_leve_parcours_error():
    # sous_fertilisant absent -> None -> aucune expression vraie -> erreur.
    arbre = _arbre_origine_effluent()
    with pytest.raises(ParcoursError):
        parcours(arbre, {})


def test_valeur_tracabilite_ecrite_dans_contexte():
    arbre = _arbre_origine_effluent()
    ctx = {"sous_fertilisant": "effluents_peu_charges_elevage"}
    parcours(arbre, ctx)
    # La valeur de la branche prise est ecrite sous la cle `champ`.
    assert ctx["effluent_peu_charge_elevage"] is True


def test_ordre_premiere_vraie_l_emporte():
    """Si deux expressions sont vraies, la premiere dans l'ordre gagne."""
    arbre = {
        "metadata": {"version": "test"},
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue_parametre",
                "id": "q_x",
                "champ": "resultat",
                "branches": [
                    {
                        "expression": "type_fertilisant == 'type_II'",
                        "valeur": "a",
                        "regle": {"id": "r_a", "type": "libre"},
                    },
                    {
                        "expression": "True",  # aussi vraie, mais 2e
                        "valeur": "b",
                        "regle": {"id": "r_b", "type": "libre"},
                    },
                ],
            }
        },
    }
    res = parcours(arbre, {"type_fertilisant": "type_II"})
    assert res.regle_id == "r_a"


def test_expression_cassee_consideree_fausse_on_continue():
    """Une expression qui leve a l'eval ne bloque pas : on passe a la
    suivante. Ici la 1re fait une addition int+str (TypeError), la 2e
    attrape."""
    arbre = {
        "metadata": {"version": "test"},
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue_parametre",
                "id": "q_x",
                "champ": "resultat",
                "branches": [
                    {
                        "expression": "type_fertilisant + 1",  # TypeError -> faux
                        "valeur": "ko",
                        "regle": {"id": "r_ko", "type": "libre"},
                    },
                    {
                        "expression": "True",
                        "valeur": "ok",
                        "regle": {"id": "r_ok", "type": "libre"},
                    },
                ],
            }
        },
    }
    res = parcours(arbre, {"type_fertilisant": "type_II"})
    assert res.regle_id == "r_ok"


def test_fallback_expression_true_attrape_le_reste():
    """Idiome juriste : derniere branche `expression: "True"` = fallback."""
    arbre = {
        "metadata": {"version": "test"},
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue_parametre",
                "id": "q_x",
                "champ": "origine",
                "branches": [
                    {
                        "expression": "sous_fertilisant == 'a'",
                        "valeur": "a",
                        "regle": {"id": "r_a", "type": "libre"},
                    },
                    {
                        "expression": "True",
                        "valeur": "inconnu",
                        "regle": {"id": "r_inconnu", "a_completer": True},
                    },
                ],
            }
        },
    }
    res = parcours(arbre, {"sous_fertilisant": "zzz"})
    assert res.regle_id == "r_inconnu"


# ─── renvoi_vers depuis une branche catalogue_parametre ────────────────────


def test_renvoi_vers_depuis_catalogue_parametre():
    arbre = {
        "metadata": {"version": "test"},
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue_parametre",
                "id": "q_x",
                "champ": "origine",
                "branches": [
                    {
                        "expression": "sous_fertilisant == 'a'",
                        "valeur": "a",
                        "renvoi_vers": "r_partage",
                    },
                ],
            }
        },
        "regles_partagees": [
            {"regle": {"id": "r_partage", "type": "interdiction"}},
        ],
    }
    res = parcours(arbre, {"sous_fertilisant": "a"})
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_partage"


# ─── Enumeration des feuilles ───────────────────────────────────────────────


def test_enumeration_explore_toutes_les_branches():
    """La mini-app de validation doit voir les 2 feuilles du noeud
    catalogue_parametre, sous culture_principale."""
    arbre = {
        "metadata": {"version": "test"},
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
                "source": "sig",
                "branches": [
                    {
                        "valeur": True,
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "culture",
                            "id": "q_occ",
                            "champ": "occupation_sol",
                            "texte": "?",
                            "branches": [
                                {
                                    "valeur": "culture_principale",
                                    "noeud": {
                                        "type_noeud": "catalogue_parametre",
                                        "id": "q_origine",
                                        "champ": "effluent_peu_charge_elevage",
                                        "branches": [
                                            {
                                                "expression": (
                                                    "sous_fertilisant == 'a'"
                                                ),
                                                "valeur": True,
                                                "regle": {
                                                    "id": "r_oui",
                                                    "type": "interdiction",
                                                },
                                            },
                                            {
                                                "expression": "True",
                                                "valeur": False,
                                                "regle": {
                                                    "id": "r_non",
                                                    "type": "libre",
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
        },
    }
    feuilles = enumerer_feuilles_culture_principale_v2(arbre)
    regle_ids = {f["regle_id"] for f in feuilles}
    assert regle_ids == {"r_oui", "r_non"}
