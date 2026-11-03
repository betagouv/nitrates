"""Identite, recherche et normalisation des champs de QC (#620)."""

import copy

import pytest

from envergo.nitrates.yaml_tree.parcours import _ajouter_question
from envergo.nitrates.yaml_tree.qc_champs import (
    PlanImpossible,
    RenommageImpossible,
    catalogue_qc,
    cle_valeur,
    collecter_qc,
    normaliser_texte,
    planifier_normalisation,
    rechercher_qc,
    renommer_champs,
    renommer_dans_expression,
    score_recherche,
)

IAA_LONG = (
    "Le fertilisant utilisé est-il issu de traitement et transformations de "
    "matières premières ?"
)
IAA_COURT = "Le fertilisant utilisé est-il issu du traitement de matières premières ?"
OUI_NON = [{"valeur": True, "libelle": "Oui"}, {"valeur": False, "libelle": "Non"}]


def qc(nid, champ, texte, branches=None):
    return {
        "type_noeud": "formulaire",
        "niveau": "complement",
        "id": nid,
        "champ": champ,
        "texte": texte,
        "branches": copy.deepcopy(branches if branches is not None else OUI_NON),
    }


def arbre(*noeuds):
    """Racine catalogue, une branche par noeud fourni."""
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_racine",
                "champ": "zone",
                "source": "sig",
                "branches": [
                    {"valeur": f"v{i}", "noeud": n} for i, n in enumerate(noeuds)
                ],
            }
        }
    }


def occurrences(*arbres_):
    out = []
    for i, a in enumerate(arbres_):
        out.extend(collecter_qc(a, arbre=f"arbre{i}"))
    return out


# ─── Normalisation ──────────────────────────────────────────────────────────


def test_normaliser_texte_ignore_casse_ponctuation_accents_espaces():
    assert normaliser_texte("Culture  irriguée ?") == normaliser_texte(
        "culture irriguee?"
    )


def test_cle_valeur_booleen_et_chaine_equivalents():
    assert cle_valeur(True) == cle_valeur("True") == "true"
    assert cle_valeur("icpe_a") == "icpe_a"


def test_collecter_qc_ignore_les_autres_niveaux():
    principal = {
        "type_noeud": "formulaire",
        "niveau": "type_fertilisant",
        "id": "q_type",
        "champ": "type_fertilisant",
        "texte": "Type ?",
        "branches": [{"valeur": "type_I", "noeud": qc("q_a", "a", IAA_LONG)}],
    }
    occs = collecter_qc(arbre(principal))
    assert [o.champ for o in occs] == ["a"]


# ─── Plan ───────────────────────────────────────────────────────────────────


def test_meme_texte_memes_reponses_fusionnent_vers_le_plus_utilise():
    a = arbre(
        qc("q_1", "fertilisant_iaa", IAA_LONG), qc("q_2", "fertilisant_iaa", IAA_LONG)
    )
    b = arbre(qc("q_3", "q_typeIa_ICPE_ED_q6", IAA_LONG + " "))
    plan = planifier_normalisation(occurrences(a, b))
    assert plan.mapping == {"q_typeIa_ICPE_ED_q6": "fertilisant_iaa"}


def test_regroupement_transitif_par_les_variantes_de_texte():
    # fertilisant_iaa porte les deux redactions : chacune ramene son champ.
    a = arbre(
        qc("q_1", "fertilisant_iaa", IAA_LONG),
        qc("q_2", "fertilisant_iaa", IAA_COURT),
        qc("q_3", "icpe_ed", IAA_LONG),
        qc("q_4", "pas_un_digestats", IAA_COURT),
    )
    plan = planifier_normalisation(occurrences(a))
    assert plan.mapping == {
        "icpe_ed": "fertilisant_iaa",
        "pas_un_digestats": "fertilisant_iaa",
    }


def test_a_egalite_le_champ_le_plus_parlant_l_emporte():
    a = arbre(
        qc("q_1", "type_ii", "Fertirrigation ?"),
        qc("q_2", "fertirrigation", "Fertirrigation ?"),
    )
    plan = planifier_normalisation(occurrences(a))
    assert plan.mapping == {"type_ii": "fertirrigation"}


def test_reponses_differentes_ne_fusionnent_pas():
    a = arbre(
        qc("q_1", "a", "Plan ?", [{"valeur": "icpe_a"}, {"valeur": "autre"}]),
        qc("q_2", "b", "Plan ?", [{"valeur": "icpe_a"}, {"valeur": "non_concerne"}]),
    )
    assert planifier_normalisation(occurrences(a)).mapping == {}


def test_polarite_inversee_ecarte_le_champ():
    inverse = [{"valeur": True, "libelle": "Non"}, {"valeur": False, "libelle": "Oui"}]
    a = arbre(qc("q_1", "a", IAA_LONG), qc("q_2", "pas_a", IAA_LONG, inverse))
    plan = planifier_normalisation(occurrences(a))
    assert plan.mapping == {}
    assert "pas_a" in plan.ecartes_polarite


def test_ordre_des_branches_sans_effet_sur_la_polarite():
    ordre_inverse = [
        {"valeur": False, "libelle": "Non"},
        {"valeur": True, "libelle": "Oui"},
    ]
    a = arbre(qc("q_1", "a", IAA_LONG), qc("q_2", "b", IAA_LONG, ordre_inverse))
    assert planifier_normalisation(occurrences(a)).mapping == {"b": "a"}


def test_canonique_force_et_exclusion():
    a = arbre(
        qc("q_1", "a", IAA_LONG),
        qc("q_2", "a", IAA_LONG),
        qc("q_3", "b", IAA_LONG),
        qc("q_4", "c", IAA_LONG),
    )
    occs = occurrences(a)
    assert planifier_normalisation(occs, canoniques_forces=["b"]).mapping == {
        "a": "b",
        "c": "b",
    }
    assert planifier_normalisation(occs, exclus=["c"]).mapping == {"b": "a"}


def test_fusion_forcee_exige_les_memes_reponses():
    a = arbre(
        qc("q_1", "culture_irriguee", "Culture irriguée ?"),
        qc("q_2", "type_iii", "Est-ce que votre culture est irriguée ?"),
        qc("q_3", "plan", "Plan ?", [{"valeur": "x"}, {"valeur": "y"}]),
    )
    occs = occurrences(a)
    plan = planifier_normalisation(occs)
    assert plan.mapping == {}
    assert ("culture_irriguee", "type_iii") in [(p[0], p[1]) for p in plan.proches]
    fusion = planifier_normalisation(occs, fusions=[["culture_irriguee", "type_iii"]])
    assert fusion.mapping == {"type_iii": "culture_irriguee"}
    with pytest.raises(PlanImpossible):
        planifier_normalisation(occs, fusions=[["culture_irriguee", "plan"]])


def test_meme_champ_reponses_differentes_signale():
    a = arbre(qc("q_1", "plan", "Plan ?", [{"valeur": "icpe_a"}, {"valeur": "autre"}]))
    b = arbre(qc("q_2", "plan", "Plan ?", [{"valeur": "icpe_a"}, {"valeur": "Non"}]))
    plan = planifier_normalisation(occurrences(a, b))
    assert list(plan.valeurs_divergentes) == ["plan"]
    assert plan.mapping == {}


# ─── Reecriture ─────────────────────────────────────────────────────────────


def test_renommer_expression_ne_touche_pas_les_chaines():
    expr = "icpe_ed is True and plan_epandage == 'icpe_ed'"
    assert (
        renommer_dans_expression(expr, {"icpe_ed": "fertilisant_iaa"})
        == "fertilisant_iaa is True and plan_epandage == 'icpe_ed'"
    )


def test_renommer_expression_avec_litteral_accentue():
    expr = "zone == 'Épinal' and type_ii"
    assert (
        renommer_dans_expression(expr, {"type_ii": "fertirrigation"})
        == "zone == 'Épinal' and fertirrigation"
    )


def test_renommer_expression_illisible_refuse():
    with pytest.raises(RenommageImpossible):
        renommer_dans_expression("type_ii ==", {"type_ii": "fertirrigation"})


def test_renommer_champs_reecrit_champ_expression_remap_et_inputs():
    contenu = arbre(
        qc("q_1", "type_ii", "Fertirrigation ?"),
        {
            "type_noeud": "catalogue_parametre",
            "id": "n_param",
            "champ": "calc",
            "branches": [
                {
                    "expression": "type_ii is True",
                    "valeur": "x",
                    "renvoi_arbre": "national",
                    "remap_contexte": {"type_ii": True, "plan_epandage": "icpe_ed"},
                },
                {
                    "expression": "True",
                    "regle": {
                        "id": "r_1",
                        "type": "libre",
                        "inputs_requis": ["type_ii"],
                    },
                },
            ],
        },
    )
    modifs = renommer_champs(contenu, {"type_ii": "fertirrigation"})
    assert {m.nature for m in modifs} == {
        "champ",
        "expression",
        "remap_contexte",
        "inputs_requis",
    }
    branches = contenu["arbre"]["noeud"]["branches"]
    assert branches[0]["noeud"]["champ"] == "fertirrigation"
    param = branches[1]["noeud"]["branches"]
    assert param[0]["expression"] == "fertirrigation is True"
    # La valeur 'icpe_ed' d'un autre champ n'est jamais touchee.
    assert param[0]["remap_contexte"] == {
        "fertirrigation": True,
        "plan_epandage": "icpe_ed",
    }
    assert param[1]["regle"]["inputs_requis"] == ["fertirrigation"]


def test_renommer_champs_conflit_de_remap_ne_modifie_rien():
    contenu = arbre(
        {
            "type_noeud": "catalogue_parametre",
            "id": "n_param",
            "champ": "calc",
            "branches": [
                {
                    "expression": "True",
                    "renvoi_arbre": "national",
                    "remap_contexte": {"type_ii": True, "fertirrigation": False},
                }
            ],
        }
    )
    avant = copy.deepcopy(contenu)
    with pytest.raises(RenommageImpossible):
        renommer_champs(contenu, {"type_ii": "fertirrigation"})
    assert contenu == avant


# ─── Recherche ──────────────────────────────────────────────────────────────


def test_recherche_texte_partiel_et_dernier_mot_en_cours_de_frappe():
    assert score_recherche("fertilisant issu de trait", IAA_LONG) >= 0.75


def test_score_identique_reserve_au_meme_texte():
    assert score_recherche("Culture irriguée ?", "culture irriguee") == 1.0
    assert (
        score_recherche("Culture irriguée ?", "Votre culture est-elle irriguée ?") < 1.0
    )


def test_catalogue_regroupe_les_variantes_d_un_champ():
    a = arbre(
        qc("q_1", "fertilisant_iaa", IAA_LONG),
        qc("q_2", "fertilisant_iaa", IAA_LONG),
        qc("q_3", "fertilisant_iaa", IAA_COURT),
    )
    cat = catalogue_qc(occurrences(a))
    assert len(cat) == 1
    assert cat[0].texte == IAA_LONG
    assert cat[0].nb_occurrences == 3
    assert cat[0].branches == OUI_NON


def test_rechercher_trie_et_filtre():
    a = arbre(
        qc("q_1", "fertilisant_iaa", IAA_LONG),
        qc("q_2", "culture_irriguee", "Culture irriguée ?"),
    )
    cat = catalogue_qc(occurrences(a))
    res = rechercher_qc("matières premières", cat)
    assert [q.champ for _, q in res] == ["fertilisant_iaa"]
    assert rechercher_qc("zz", cat) == []
    assert rechercher_qc("rien à voir avec la question", cat) == []


# ─── Parcours : une QC sous plusieurs reponses du meme parent ──────────────


def test_qc_sous_plusieurs_reponses_du_parent_les_garde_toutes():
    questions = []
    noeud = qc("q_iaa", "fertilisant_iaa", IAA_LONG)
    _ajouter_question(
        questions, noeud, parent_champ="plan_epandage", parent_valeur="icpe_a"
    )
    _ajouter_question(
        questions, noeud, parent_champ="plan_epandage", parent_valeur="icpe_ed"
    )
    _ajouter_question(
        questions, noeud, parent_champ="plan_epandage", parent_valeur="icpe_a"
    )
    assert len(questions) == 1
    assert questions[0].parent_valeur == "icpe_a"
    assert questions[0].parent_valeurs == ["icpe_a", "icpe_ed"]


def test_qc_deja_posee_sans_condition_reste_inconditionnelle():
    questions = []
    noeud = qc("q_iaa", "fertilisant_iaa", IAA_LONG)
    _ajouter_question(questions, noeud)
    _ajouter_question(
        questions, noeud, parent_champ="plan_epandage", parent_valeur="icpe_a"
    )
    assert questions[0].parent_champ is None
    assert questions[0].parent_valeurs == []


@pytest.mark.django_db
def test_template_qc_porte_toutes_les_reponses_du_parent():
    # Le filtre glossaire du template lit la base.
    from django.template.loader import render_to_string

    questions = []
    noeud = qc("q_iaa", "fertilisant_iaa", IAA_LONG)
    _ajouter_question(
        questions, noeud, parent_champ="plan_epandage", parent_valeur="icpe_a"
    )
    _ajouter_question(
        questions, noeud, parent_champ="plan_epandage", parent_valeur="icpe_ed"
    )
    html = render_to_string(
        "nitrates/fragments/_qc_question_item.html",
        {"q": questions[0], "id_prefix": "id_", "form_attr": "", "forloop_first": True},
    )
    assert 'data-qc-parent-valeurs="icpe_a||icpe_ed"' in html
    assert 'data-qc-parent-valeur="icpe_a"' in html
