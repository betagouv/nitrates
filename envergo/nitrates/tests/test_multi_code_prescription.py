"""Plusieurs prescriptions conditionnees par regle (#multi-PC).

Grammaire : `code_prescription` accepte un scalaire (1 PC) OU une liste (2+).
En interne on normalise toujours en liste (`Resultat.codes_prescription`).
"""

import pytest
from django.http import QueryDict

from envergo.nitrates.yaml_admin.forms import RegleForm
from envergo.nitrates.yaml_tree.parcours import (
    _faire_resultat,
    normaliser_codes_prescription,
    parcours,
)

pytestmark = pytest.mark.django_db


# ─── Normalisation ───────────────────────────────────────────────────────────


def test_normalisation():
    assert normaliser_codes_prescription(None) == []
    assert normaliser_codes_prescription("pc4") == ["pc4"]
    assert normaliser_codes_prescription(["pc4", "pc11"]) == ["pc4", "pc11"]
    assert normaliser_codes_prescription([]) == []


def test_resultat_scalaire_et_liste():
    r1 = _faire_resultat(
        {"id": "r", "type": "interdiction", "code_prescription": "pc4"}, []
    )
    assert r1.codes_prescription == ["pc4"]
    assert r1.code_prescription == "pc4"  # compat 1er PC
    r2 = _faire_resultat(
        {"id": "r", "type": "interdiction", "code_prescription": ["pc4", "pc11"]}, []
    )
    assert r2.codes_prescription == ["pc4", "pc11"]
    assert r2.code_prescription == "pc4"


# ─── Parcours bout-en-bout ───────────────────────────────────────────────────


def _arbre(code_prescription):
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
                "branches": [
                    {
                        "valeur": True,
                        "regle": {
                            "id": "r_x",
                            "type": "interdiction",
                            "code_prescription": code_prescription,
                        },
                    }
                ],
            }
        }
    }


def test_parcours_multi_pc():
    res = parcours(_arbre(["pc4", "pc11"]), {"en_zone_vulnerable": True})
    assert res.codes_prescription == ["pc4", "pc11"]


def test_parcours_patch_remap_sur_liste():
    """Un patch renvoi_vers remappe chaque PC de la liste."""
    cible = {
        "type_noeud": "formulaire",
        "id": "n_cible",
        "champ": "tf",
        "niveau": "type_fertilisant",
        "texte": "?",
        "branches": [
            {
                "valeur": "a",
                "regle": {
                    "id": "r",
                    "type": "plafonnement",
                    "code_prescription": ["pc12", "pc13"],
                },
            }
        ],
    }
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
                            "id": "q",
                            "champ": "occ",
                            "niveau": "culture",
                            "texte": "?",
                            "branches": [
                                {"valeur": "src", "noeud": cible},
                                {
                                    "valeur": "via",
                                    "renvoi_vers": "n_cible",
                                    "patch": {"code_prescription": {"pc12": "pc14"}},
                                },
                            ],
                        },
                    }
                ],
            }
        }
    }
    res = parcours(arbre, {"en_zone_vulnerable": True, "occ": "via", "tf": "a"})
    # pc12 remappe en pc14, pc13 inchange.
    assert res.codes_prescription == ["pc14", "pc13"]


# ─── Validateur ──────────────────────────────────────────────────────────────


def _check(arbre):
    from envergo.nitrates.yaml_tree.validator import _check_references_referentiels

    ref = {"codes_prescription": {f"pc{i}": {} for i in range(1, 17)}, "notes": {}}
    return _check_references_referentiels(arbre, ref)


def test_validateur_liste_pc_connus_ok():
    assert _check(_arbre(["pc4", "pc11"])) == []


def test_validateur_pc_inconnu_dans_liste():
    errs = _check(_arbre(["pc4", "pc99"]))
    assert any("pc99" in e and "inconnu" in e for e in errs)


def test_validateur_doublon_pc():
    errs = _check(_arbre(["pc4", "pc4"]))
    assert any("doublon" in e for e in errs)


# ─── RegleForm (widget repetable) ────────────────────────────────────────────


def _form(pcs):
    q = QueryDict(mutable=True)
    q.update({"id": "r", "type": "interdiction"})
    for pc in pcs:
        q.appendlist("code_prescription", pc)
    f = RegleForm(q)
    f.is_valid()
    return f


def test_form_scalaire_si_un():
    assert _form(["pc4"]).to_new_data()["code_prescription"] == "pc4"


def test_form_liste_si_plusieurs():
    assert _form(["pc4", "pc11"]).to_new_data()["code_prescription"] == ["pc4", "pc11"]


def test_form_none_si_zero():
    assert _form([]).to_new_data()["code_prescription"] is None


def test_form_normalise_et_dedoublonne():
    # '13' et 'pc13' fusionnent ; '14' -> 'pc14'.
    assert _form(["13", "pc13", "14"]).to_new_data()["code_prescription"] == [
        "pc13",
        "pc14",
    ]


# ─── Patch remap sur liste (exhaustif) ───────────────────────────────────────


def _arbre_patch(code_prescription, patch):
    cible = {
        "type_noeud": "formulaire",
        "id": "n_cible",
        "champ": "tf",
        "niveau": "type_fertilisant",
        "texte": "?",
        "branches": [
            {
                "valeur": "a",
                "regle": {
                    "id": "r",
                    "type": "plafonnement",
                    "code_prescription": code_prescription,
                },
            }
        ],
    }
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
                            "id": "q",
                            "champ": "occ",
                            "niveau": "culture",
                            "texte": "?",
                            "branches": [
                                {"valeur": "src", "noeud": cible},
                                {
                                    "valeur": "via",
                                    "renvoi_vers": "n_cible",
                                    "patch": patch,
                                },
                            ],
                        },
                    }
                ],
            }
        }
    }


def _run_patch(cp, patch):
    a = _arbre_patch(cp, patch)
    return parcours(
        a, {"en_zone_vulnerable": True, "occ": "via", "tf": "a"}
    ).codes_prescription


def test_patch_remap_multiple_sur_liste():
    assert _run_patch(
        ["pc12", "pc13"], {"code_prescription": {"pc12": "pc14", "pc13": "pc16"}}
    ) == ["pc14", "pc16"]


def test_patch_remap_partiel_preserve_ordre():
    assert _run_patch(
        ["pc12", "pc13", "pc5"], {"code_prescription": {"pc12": "pc14"}}
    ) == ["pc14", "pc13", "pc5"]


def test_patch_remap_origine_scalaire():
    assert _run_patch("pc12", {"code_prescription": {"pc12": "pc14"}}) == ["pc14"]


def test_patch_sans_match_inchange():
    assert _run_patch(["pc4", "pc11"], {"code_prescription": {"pc99": "pc1"}}) == [
        "pc4",
        "pc11",
    ]
