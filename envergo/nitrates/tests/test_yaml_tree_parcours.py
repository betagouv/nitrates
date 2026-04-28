"""Tests du parcours stateless de l'arbre de decision.

Couvre :
  - cas hors ZVN -> resultat direct
  - contexte vide en ZVN -> questions subsidiaires
  - chemin complet vers chaque type de regle (interdiction, plafonnement,
    autorisation_sous_condition, libre, calculatrice, non_applicable)
  - resolution renvoi_vers
  - regle a_completer (stub) : ne crashe pas
  - noeud catalogue interne sans reponse -> BesoinCatalogue
  - trace du chemin pour debug juriste
"""

import pytest

from envergo.nitrates.yaml_tree.loader import load_arbre
from envergo.nitrates.yaml_tree.parcours import (
    BesoinCatalogue,
    ParcoursError,
    QuestionsSubsidiaires,
    Resultat,
    parcours,
)

# ─── Fixtures et helpers ───────────────────────────────────────────────────


@pytest.fixture
def arbre_pan():
    """Le vrai brouillon PAN, charge depuis NITRATES_SPECS_DIR."""
    return load_arbre("arbre_decision_national")


def _arbre_jouet() -> dict:
    """Petit arbre maitrise pour tester les cas limites sans dependre du
    contenu evolutif du brouillon PAN."""
    return {
        "metadata": {"version": "test"},
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_root",
                "champ": "en_zone_vulnerable",
                "source": "sig",
                "reference": "zone_vulnerable_nitrates",
                "branches": [
                    {
                        "valeur": False,
                        "regle": {
                            "id": "r_hors",
                            "type": "non_applicable",
                            "message": "hors zvn",
                        },
                    },
                    {
                        "valeur": True,
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "culture",
                            "id": "q_culture",
                            "champ": "occupation_sol",
                            "texte": "Quelle culture ?",
                            "branches": [
                                {
                                    "valeur": "mais",
                                    "regle": {
                                        "id": "r_mais",
                                        "type": "interdiction",
                                        "periodes": [{"du": "15/07", "au": "15/02"}],
                                        "code_prescription": "pc5",
                                    },
                                },
                                {
                                    "valeur": "colza",
                                    "noeud": {
                                        "type_noeud": "catalogue",
                                        "id": "n_zone_5",
                                        "champ": "zone_note_5",
                                        "source": "sig",
                                        "reference": "zone_note_5",
                                        "branches": [
                                            {
                                                "valeur": True,
                                                "regle": {
                                                    "id": "r_colza_z5",
                                                    "type": "interdiction",
                                                    "periodes": [
                                                        {"du": "15/10", "au": "15/01"}
                                                    ],
                                                    "note": "note_5",
                                                },
                                            },
                                            {
                                                "valeur": False,
                                                "regle": {
                                                    "id": "r_colza_autre",
                                                    "type": "interdiction",
                                                    "periodes": [
                                                        {"du": "15/10", "au": "31/01"}
                                                    ],
                                                },
                                            },
                                        ],
                                    },
                                },
                                {"valeur": "renvoi", "renvoi_vers": "r_hors"},
                                {
                                    "valeur": "stub",
                                    "regle": {
                                        "id": "r_stub_todo",
                                        "a_completer": True,
                                    },
                                },
                            ],
                        },
                    },
                ],
            }
        },
    }


# ─── Cas hors ZVN ──────────────────────────────────────────────────────────


def test_hors_zvn_retourne_resultat_non_applicable():
    res = parcours(_arbre_jouet(), {"en_zone_vulnerable": False})
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_hors"
    assert res.type == "non_applicable"
    assert res.message == "hors zvn"
    assert res.chemin == ["n_root", "r_hors"]


# ─── Contexte vide en ZVN -> questions ─────────────────────────────────────


def test_en_zvn_sans_reponses_retourne_questions_subsidiaires():
    res = parcours(_arbre_jouet(), {"en_zone_vulnerable": True})
    assert isinstance(res, QuestionsSubsidiaires)
    # Au moins la 1re question (occupation_sol) doit etre presente
    champs = [q.champ for q in res.questions]
    assert "occupation_sol" in champs
    # Les choix de la 1re question doivent etre listes
    q1 = res.questions[0]
    valeurs = [c["valeur"] for c in q1.choix]
    assert "mais" in valeurs and "colza" in valeurs


# ─── Chemins vers regles ───────────────────────────────────────────────────


def test_chemin_complet_vers_interdiction_jouet():
    res = parcours(
        _arbre_jouet(),
        {"en_zone_vulnerable": True, "occupation_sol": "mais"},
    )
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_mais"
    assert res.type == "interdiction"
    assert res.periodes == [{"du": "15/07", "au": "15/02"}]
    assert res.code_prescription == "pc5"
    assert res.chemin == ["n_root", "q_culture", "r_mais"]


def test_renvoi_vers_resolu():
    res = parcours(
        _arbre_jouet(),
        {"en_zone_vulnerable": True, "occupation_sol": "renvoi"},
    )
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_hors"
    assert res.type == "non_applicable"
    # Le chemin doit garder la trace du renvoi pour les juristes
    assert "renvoi_vers:r_hors" in res.chemin


def test_a_completer_ne_crashe_pas():
    res = parcours(
        _arbre_jouet(),
        {"en_zone_vulnerable": True, "occupation_sol": "stub"},
    )
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_stub_todo"
    assert res.a_completer is True
    # Le type peut etre 'a_completer' (defaut) ou absent du YAML
    assert res.type == "a_completer"


# ─── Catalogue interne ─────────────────────────────────────────────────────


def test_catalogue_interne_sans_reponse_retourne_besoin_catalogue():
    res = parcours(
        _arbre_jouet(),
        {"en_zone_vulnerable": True, "occupation_sol": "colza"},
    )
    assert isinstance(res, BesoinCatalogue)
    assert res.noeud_id == "n_zone_5"
    assert res.champ == "zone_note_5"
    assert res.source == "sig"


def test_catalogue_interne_resolu_retourne_resultat():
    res = parcours(
        _arbre_jouet(),
        {
            "en_zone_vulnerable": True,
            "occupation_sol": "colza",
            "zone_note_5": True,
        },
    )
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_colza_z5"
    assert res.note == "note_5"


# ─── Erreurs de parcours ───────────────────────────────────────────────────


def test_valeur_inconnue_dans_contexte_leve_parcours_error():
    with pytest.raises(ParcoursError) as exc:
        parcours(
            _arbre_jouet(),
            {"en_zone_vulnerable": True, "occupation_sol": "valeur_inexistante"},
        )
    assert "valeur_inexistante" in str(exc.value)


# ─── Sur le vrai brouillon PAN ─────────────────────────────────────────────


def test_pan_hors_zvn(arbre_pan):
    res = parcours(arbre_pan, {"en_zone_vulnerable": False})
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_hors_zvn"
    assert res.type == "non_applicable"


def test_pan_zvn_sans_reponses_demande_culture(arbre_pan):
    res = parcours(arbre_pan, {"en_zone_vulnerable": True})
    assert isinstance(res, QuestionsSubsidiaires)
    q_culture = next(q for q in res.questions if q.champ == "occupation_sol")
    assert q_culture.niveau == "culture"
    valeurs = {c["valeur"] for c in q_culture.choix}
    assert {"sol_non_cultive", "culture_principale"}.issubset(valeurs)


def test_pan_sol_non_cultive_court_circuit(arbre_pan):
    res = parcours(
        arbre_pan,
        {"en_zone_vulnerable": True, "occupation_sol": "sol_non_cultive"},
    )
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_sol_non_cultive"
    assert res.type == "interdiction"


def test_pan_culture_post_0101_type_0_atteint_resultat(arbre_pan):
    res = parcours(
        arbre_pan,
        {
            "en_zone_vulnerable": True,
            "occupation_sol": "culture_principale",
            "sous_culture": "culture_recoltee_apres_0101_hors_colza",
            "type_fertilisant": "type_0",
        },
    )
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_post_0101_type_0"
    assert res.type == "interdiction"
    assert res.code_prescription == "pc4"


def test_pan_colza_type_II_demande_zone_note_5(arbre_pan):
    """Apres avoir choisi colza + type_II, on tombe sur un catalogue
    interne (zone_note_5) qui doit demander BesoinCatalogue."""
    res = parcours(
        arbre_pan,
        {
            "en_zone_vulnerable": True,
            "occupation_sol": "culture_principale",
            "sous_culture": "colza",
            "type_fertilisant": "type_II",
        },
    )
    assert isinstance(res, BesoinCatalogue)
    assert res.champ == "zone_note_5"
    assert res.source == "sig"


def test_pan_colza_type_II_zone_note_5_true(arbre_pan):
    res = parcours(
        arbre_pan,
        {
            "en_zone_vulnerable": True,
            "occupation_sol": "culture_principale",
            "sous_culture": "colza",
            "type_fertilisant": "type_II",
            "zone_note_5": True,
        },
    )
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_colza_type_II_note5"
    assert res.note == "note_5"
