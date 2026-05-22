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


# ─── Fallback type_I = union {type_Ia, type_Ib} ─────────────────────────────


def _arbre_avec_type_I_combine() -> dict:
    """Arbre minimal avec une branche `type_I` combinee (cas metier ou
    l'arbre ne distingue pas type_Ia et type_Ib)."""
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
                        "valeur": True,
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "type_fertilisant",
                            "id": "q_fert",
                            "champ": "type_fertilisant",
                            "texte": "Quel type ?",
                            "branches": [
                                {
                                    "valeur": "type_0",
                                    "regle": {"id": "r_t0", "type": "libre"},
                                },
                                {
                                    "valeur": "type_I",
                                    "regle": {
                                        "id": "r_tI_combine",
                                        "type": "interdiction",
                                    },
                                },
                            ],
                        },
                    },
                ],
            }
        },
    }


def test_type_Ia_retombe_sur_type_I_combine():
    """L'arbre n'a qu'une branche type_I ; un input type_Ia y retombe."""
    res = parcours(
        _arbre_avec_type_I_combine(),
        {"en_zone_vulnerable": True, "type_fertilisant": "type_Ia"},
    )
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_tI_combine"


def test_type_Ib_retombe_sur_type_I_combine():
    res = parcours(
        _arbre_avec_type_I_combine(),
        {"en_zone_vulnerable": True, "type_fertilisant": "type_Ib"},
    )
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_tI_combine"


def test_type_Ia_ne_retombe_pas_si_branche_specifique_existe():
    """Si l'arbre a une branche `type_Ia` explicite, on prend celle-ci
    (pas le fallback type_I)."""
    arbre = _arbre_avec_type_I_combine()
    # On ajoute une branche type_Ia specifique a cote du type_I combine
    arbre["arbre"]["noeud"]["branches"][0]["noeud"]["branches"].append(
        {"valeur": "type_Ia", "regle": {"id": "r_tIa_specifique", "type": "libre"}}
    )
    res = parcours(arbre, {"en_zone_vulnerable": True, "type_fertilisant": "type_Ia"})
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_tIa_specifique"


def test_fallback_type_I_ne_concerne_que_le_champ_type_fertilisant():
    """Le fallback type_Ia/Ib -> type_I ne s'applique pas sur d'autres
    champs. Une valeur 'type_Ia' sur un champ different leve normalement
    ParcoursError si pas de branche correspondante."""
    arbre = {
        "metadata": {"version": "test"},
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "culture",
                "id": "q_x",
                "champ": "autre_champ",
                "texte": "?",
                "branches": [
                    {"valeur": "type_I", "regle": {"id": "r_x", "type": "libre"}},
                ],
            }
        },
    }
    with pytest.raises(ParcoursError):
        parcours(arbre, {"autre_champ": "type_Ia"})


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


def test_pan_culture_hiver_hors_colza_type_0_atteint_resultat(arbre_pan):
    """Refonte 30/04 : culture_recoltee_apres_0101_hors_colza renommee
    en culture_hiver_hors_colza (avec doublon temporaire des deux dans
    l'arbre tant que Louise n'a pas valide la suppression)."""
    res = parcours(
        arbre_pan,
        {
            "en_zone_vulnerable": True,
            "occupation_sol": "culture_principale",
            "sous_culture": "culture_hiver_hors_colza",
            "type_fertilisant": "type_0",
        },
    )
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_hiver_hors_colza_type_0"
    assert res.type == "interdiction"


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


# ─── Cascade questions conditionnelles (#58.1) ─────────────────────────────


def test_questions_conditionnelles_remontees_avec_parent_champ(arbre_pan):
    """Cas mais irrigue : sans culture_irriguee dans le contexte, on doit
    recevoir AUSSI la sous-question culture_irriguee_type (sur la branche
    culture_irriguee=true), annotee parent_champ=culture_irriguee +
    parent_valeur=True. Resultat : 1 seul aller-retour serveur, le front
    cachera la sous-question jusqu'au clic sur "Oui" (cf. #58.1)."""
    res = parcours(
        arbre_pan,
        {
            "en_zone_vulnerable": True,
            "occupation_sol": "culture_principale",
            "sous_culture": "culture_printemps",
            "sous_culture_printemps": "mais",
            "type_fertilisant": "type_III",
        },
    )
    assert isinstance(res, QuestionsSubsidiaires)
    champs = {q.champ for q in res.questions}
    assert "culture_irriguee" in champs
    assert "culture_irriguee_type" in champs
    q_type = next(q for q in res.questions if q.champ == "culture_irriguee_type")
    assert q_type.parent_champ == "culture_irriguee"
    assert q_type.parent_valeur is True
    q_irr = next(q for q in res.questions if q.champ == "culture_irriguee")
    assert q_irr.parent_champ is None


def test_questions_conditionnelles_pas_remontees_si_parent_repondu(arbre_pan):
    """Cas mais irrigue, culture_irriguee=False deja dans l'URL : on n'a
    plus besoin de proposer culture_irriguee_type (la branche non-irriguee
    pointe direct vers une regle). La question conditionnelle ne doit
    pas etre remontee."""
    res = parcours(
        arbre_pan,
        {
            "en_zone_vulnerable": True,
            "occupation_sol": "culture_principale",
            "sous_culture": "culture_printemps",
            "sous_culture_printemps": "mais",
            "type_fertilisant": "type_III",
            "culture_irriguee": False,
        },
    )
    # culture_irriguee=False mene direct a une regle, pas de question.
    assert isinstance(res, Resultat)


def test_question_conditionnelle_pre_resolue_par_contexte(arbre_pan):
    """Cas mais sous-culture cliquee : cascade.js pre-remplit
    culture_irriguee_type=mais via mapping_sous_culture_vers_branche.flags.
    Du coup, meme si culture_irriguee n'est pas encore repondu, on ne
    doit PAS proposer la sous-question culture_irriguee_type (elle est
    deja resolue) -- juste demander culture_irriguee."""
    res = parcours(
        arbre_pan,
        {
            "en_zone_vulnerable": True,
            "occupation_sol": "culture_principale",
            "sous_culture": "culture_printemps",
            "sous_culture_printemps": "mais",
            "type_fertilisant": "type_III",
            # pre-fill via cascade.js depuis mapping referentiel
            "culture_irriguee_type": "mais",
        },
    )
    assert isinstance(res, QuestionsSubsidiaires)
    champs = {q.champ for q in res.questions}
    assert "culture_irriguee" in champs
    # La sous-question culture_irriguee_type ne doit PAS apparaitre
    # puisqu'elle est deja pre-remplie cote front.
    assert "culture_irriguee_type" not in champs


# ─── has_borne_flottante ───────────────────────────────────────────────────


def test_has_borne_flottante_false_si_que_dates_fixes():
    """Cas mixte standard (que des bornes JJ/MM) : pas de borne
    flottante. Le template ne doit pas afficher "Sinon, regle de base —"
    dans ce cas (fix #81)."""
    res = Resultat(
        regle_id="r_test",
        type="mixte",
        periodes=[
            {"du": "01/09", "au": "15/10", "regime": "autorisation_sous_condition"},
            {"du": "15/10", "au": "31/01", "regime": "interdiction"},
        ],
    )
    assert res.has_borne_flottante is False


def test_has_borne_flottante_true_si_borne_phenologique():
    """Cas mixte phenologique : une periode a un slug `brunissement_des_soies`
    comme borne. Le template doit afficher "Sinon, regle de base —" pour
    le fallback dates fixes."""
    res = Resultat(
        regle_id="r_test",
        type="mixte",
        periodes=[
            {
                "du": "15/07",
                "au": "brunissement_des_soies",
                "regime": "autorisation_sous_condition",
            },
            {"du": "15/07", "au": "15/02", "regime": "interdiction"},
        ],
    )
    assert res.has_borne_flottante is True


def test_has_borne_flottante_false_si_pas_de_periodes():
    """Cas degenere : pas de periodes, has_borne_flottante=False."""
    res = Resultat(regle_id="r_test", type="libre", periodes=None)
    assert res.has_borne_flottante is False
    res2 = Resultat(regle_id="r_test", type="libre", periodes=[])
    assert res2.has_borne_flottante is False


# ─── Branche `valeurs: [a, b]` (regroupement, cf. #61 phase 3) ──────────────


def _arbre_avec_valeurs_regroupees() -> dict:
    """Arbre qui regroupe icpe_e et icpe_d sur une seule branche via
    `valeurs: [icpe_e, icpe_d]`."""
    return {
        "metadata": {"version": "test"},
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "complement",
                "id": "q_plan",
                "champ": "plan_epandage",
                "texte": "Plan d'épandage ?",
                "branches": [
                    {
                        "valeur": "icpe_a",
                        "regle": {"id": "r_icpe_a", "type": "interdiction"},
                    },
                    {
                        "valeurs": ["icpe_e", "icpe_d"],
                        "libelle": "ICPE E ou D",
                        "regle": {"id": "r_icpe_ed_groupe", "type": "interdiction"},
                    },
                    {
                        "valeur": "non_concerne",
                        "regle": {"id": "r_non_concerne", "type": "libre"},
                    },
                ],
            }
        },
    }


def test_branche_valeurs_pluriel_matche_icpe_e():
    res = parcours(
        _arbre_avec_valeurs_regroupees(),
        {"plan_epandage": "icpe_e"},
    )
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_icpe_ed_groupe"


def test_branche_valeurs_pluriel_matche_icpe_d():
    res = parcours(
        _arbre_avec_valeurs_regroupees(),
        {"plan_epandage": "icpe_d"},
    )
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_icpe_ed_groupe"


def test_branche_valeur_singulier_prime_si_specifique():
    """icpe_a a une branche singulier dédiée : ne tombe pas sur le groupe."""
    res = parcours(
        _arbre_avec_valeurs_regroupees(),
        {"plan_epandage": "icpe_a"},
    )
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_icpe_a"
