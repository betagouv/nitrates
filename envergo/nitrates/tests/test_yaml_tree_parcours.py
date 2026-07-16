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
    RenvoiArbre,
    Resultat,
    _collecter_questions,
    collecter_qc_du_chemin,
    normaliser_codes_prescription,
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


def test_renvoi_vers_noeud_reutilisable():
    """renvoi_vers peut cibler un NOEUD (sous-arbre reutilisable, pattern
    'include'), pas seulement une regle : on re-descend dedans avec le meme
    contexte et on atteint la feuille sous-jacente. Cas luzerne/ICPE en prod
    (q_prairie_plus6_type_0_icpe reutilise depuis plusieurs branches)."""
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
                                # Branche A : renvoie vers le sous-arbre partage.
                                {"valeur": "a", "renvoi_vers": "q_sous_arbre"},
                                # Branche B : le sous-arbre partage lui-meme.
                                {
                                    "valeur": "b",
                                    "noeud": {
                                        "type_noeud": "formulaire",
                                        "id": "q_sous_arbre",
                                        "champ": "detail",
                                        "branches": [
                                            {
                                                "valeur": "x",
                                                "regle": {
                                                    "id": "r_partagee",
                                                    "type": "interdiction",
                                                },
                                            }
                                        ],
                                    },
                                },
                            ],
                        },
                    }
                ],
            }
        }
    }
    res = parcours(
        arbre,
        {"en_zone_vulnerable": True, "occupation_sol": "a", "detail": "x"},
    )
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_partagee"
    assert "renvoi_vers:q_sous_arbre" in res.chemin


def test_renvoi_vers_id_inexistant_leve_parcours_error():
    """renvoi_vers vers un id absent de l'arbre -> ParcoursError explicite
    (garde-fou : pas de None silencieux qui crasherait plus loin)."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
                "branches": [
                    {"valeur": True, "renvoi_vers": "r_nexiste_pas"},
                ],
            }
        }
    }
    with pytest.raises(ParcoursError, match="ne pointe vers aucun id"):
        parcours(arbre, {"en_zone_vulnerable": True})


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


# ─── Renvoi vers regles_partagees (couvert courte) ─────────────────────────


@pytest.mark.parametrize(
    "sous_culture,type_fert,regle_attendue",
    [
        ("cie_courte", "type_0", "r_cie_courte_types_0_I_II"),
        ("cie_courte", "type_I", "r_cie_courte_types_0_I_II"),
        ("cie_courte", "type_II", "r_cie_courte_types_0_I_II"),
        ("cine_courte", "type_0", "r_cine_courte_types_0_I_II"),
        ("cine_courte", "type_I", "r_cine_courte_types_0_I_II"),
        ("cine_courte", "type_II", "r_cine_courte_types_0_I_II"),
    ],
)
def test_couvert_courte_renvoi_vers_regle_partagee(
    arbre_pan, sous_culture, type_fert, regle_attendue
):
    """Les branches type 0/I/II du couvert courte renvoient vers une regle
    `regles_partagees` (r_cie_courte_types_0_I_II / r_cine_courte_...).

    Regression : ces regles vivent hors de l'arbre (section
    `regles_partagees`) ; si `_build_id_index` ne les indexe pas, le
    parcours leve ParcoursError sur ces 6 feuilles en prod. Cf. fix index
    parcours + regles_partagees."""
    res = parcours(
        arbre_pan,
        {
            "en_zone_vulnerable": True,
            "occupation_sol": "couvert_intercultures",
            "sous_culture": sous_culture,
            "type_fertilisant": type_fert,
        },
    )
    assert isinstance(res, Resultat)
    assert res.regle_id == regle_attendue
    # La regle partagee est une autorisation_sous_condition qui porte son
    # plafond via `plafonnement_associe` (pas inline). Le parcours doit avoir
    # resolu la reference et remonte le plafond + le code prescription sur le
    # Resultat, sinon le panneau ne les affiche pas (cf. fix 2026-06-18).
    assert res.type == "autorisation_sous_condition"
    assert res.plafond_azote_kg_n_ha == 70
    assert res.codes_prescription  # non vide (issu du plafonnement associe)


def test_plafonnement_associe_ne_surcharge_pas_un_plafond_inline():
    """Fusion plafonnement_associe : on ne complete que les champs ABSENTS.
    Une feuille qui porte deja son plafond inline garde sa valeur (le
    plafonnement associe ne l'ecrase pas)."""
    arbre = {
        "arbre": {
            "noeud": {
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
                "type_noeud": "catalogue",
                "branches": [
                    {
                        "valeur": True,
                        "regle": {
                            "id": "r_inline",
                            "type": "autorisation_sous_condition",
                            "plafond_azote_kg_n_ha": 120,
                            "plafonnement_associe": "r_plaf",
                        },
                    }
                ],
            }
        },
        "plafonnements": [
            {
                "regle": {
                    "id": "r_plaf",
                    "type": "plafonnement",
                    "plafond_azote_kg_n_ha": 70,
                }
            }
        ],
    }
    res = parcours(arbre, {"en_zone_vulnerable": True})
    assert isinstance(res, Resultat)
    # Le plafond inline (120) prime sur celui du plafonnement associe (70).
    assert res.plafond_azote_kg_n_ha == 120


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


def test_valeur_inconnue_liste_les_valeurs_pluriel_disponibles():
    """Le message d'erreur d'une valeur inconnue doit lister AUSSI les valeurs
    des branches `valeurs:` (pluriel), pas seulement les `valeur:` (singulier),
    pour aider le juriste a diagnostiquer (couvre la branche `extend`)."""
    with pytest.raises(ParcoursError) as exc:
        parcours(_arbre_avec_valeurs_regroupees(), {"plan_epandage": "inconnu"})
    msg = str(exc.value)
    # Valeurs singulier ET pluriel listees.
    assert "icpe_a" in msg
    assert "icpe_e" in msg
    assert "icpe_d" in msg


# ─── has_autorisation_sous_condition / has_interdiction ─────────────────────


def test_has_autorisation_sous_condition_true_si_une_periode_asc():
    res = Resultat(
        regle_id="r_test",
        type="mixte",
        periodes=[
            {"du": "01/09", "au": "15/10", "regime": "autorisation_sous_condition"},
            {"du": "15/10", "au": "31/01", "regime": "interdiction"},
        ],
    )
    assert res.has_autorisation_sous_condition is True


def test_has_autorisation_sous_condition_false_si_aucune():
    res = Resultat(
        regle_id="r_test",
        type="interdiction",
        periodes=[{"du": "15/10", "au": "31/01", "regime": "interdiction"}],
    )
    assert res.has_autorisation_sous_condition is False


def test_has_autorisation_sous_condition_false_si_pas_de_periodes():
    assert (
        Resultat(
            regle_id="r", type="libre", periodes=None
        ).has_autorisation_sous_condition
        is False
    )


def test_has_interdiction_true_si_une_periode_interdiction():
    res = Resultat(
        regle_id="r_test",
        type="mixte",
        periodes=[
            {"du": "01/09", "au": "15/10", "regime": "autorisation_sous_condition"},
            {"du": "15/10", "au": "31/01", "regime": "interdiction"},
        ],
    )
    assert res.has_interdiction is True


def test_has_interdiction_false_si_aucune():
    res = Resultat(
        regle_id="r_test",
        type="autorisation_sous_condition",
        periodes=[
            {"du": "01/09", "au": "15/10", "regime": "autorisation_sous_condition"}
        ],
    )
    assert res.has_interdiction is False


def test_has_interdiction_false_si_pas_de_periodes():
    assert Resultat(regle_id="r", type="libre", periodes=None).has_interdiction is False


def test_has_borne_flottante_true_si_borne_sur_du():
    """Symetrique du test sur `au` : une borne phenologique sur `du`
    (pas une date JJ/MM) doit aussi rendre has_borne_flottante=True."""
    res = Resultat(
        regle_id="r_test",
        type="mixte",
        periodes=[{"du": "derniere_coupe_luzerne", "au": "15/02"}],
    )
    assert res.has_borne_flottante is True


# ─── to_json_dict (serialisation front calculatrice) ────────────────────────


def test_to_json_dict_serialise_les_champs_attendus():
    res = Resultat(
        regle_id="r_calc",
        type="calculatrice",
        periodes=[{"du": "15/07", "au": "15/02"}],
        texte_condition="cond",
        message="verdict",
        codes_prescription=["pc12", "pc14"],
        composant="calendrier_dynamique_couvert",
        inputs_requis=[{"id": "date_semis", "label": "Date de semis", "type": "date"}],
    )
    d = res.to_json_dict()
    assert d["regle_id"] == "r_calc"
    assert d["type"] == "calculatrice"
    assert d["periodes"] == [{"du": "15/07", "au": "15/02"}]
    assert d["texte_condition"] == "cond"
    assert d["message"] == "verdict"
    # compat : 1er code en scalaire + liste complete
    assert d["code_prescription"] == "pc12"
    assert d["codes_prescription"] == ["pc12", "pc14"]
    assert d["composant"] == "calendrier_dynamique_couvert"
    assert d["inputs_requis"][0]["id"] == "date_semis"


def test_to_json_dict_defauts_si_champs_absents():
    """periodes/inputs_requis None -> listes vides cote JSON (le front itere
    dessus sans garde)."""
    d = Resultat(regle_id="r", type="libre").to_json_dict()
    assert d["periodes"] == []
    assert d["inputs_requis"] == []
    assert d["codes_prescription"] == []
    assert d["code_prescription"] is None


# ─── Gardes d'erreur du parcours ────────────────────────────────────────────


def test_arbre_sans_racine_leve_parcours_error():
    with pytest.raises(ParcoursError, match="sans noeud racine"):
        parcours({"arbre": {}}, {})


def test_branche_sans_cible_leve_parcours_error():
    """Une branche choisie qui n'a ni noeud, ni regle, ni renvoi_* est un
    arbre malforme -> ParcoursError explicite (et non un None silencieux)."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "id": "q_x",
                "champ": "c",
                "branches": [{"valeur": "a"}],  # branche vide (ni regle ni noeud)
            }
        }
    }
    with pytest.raises(ParcoursError, match="sans noeud/regle"):
        parcours(arbre, {"c": "a"})


def test_feuille_vide_leve_parcours_error():
    """Une `feuille_vide` (reponse cliquable sans regle, fallback cascade)
    n'est pas parcourable directement : elle leve ParcoursError (l'evaluateur
    le rattrape pour tomber sur l'arbre inferieur)."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "id": "q_x",
                "champ": "c",
                "branches": [{"valeur": "a", "feuille_vide": True}],
            }
        }
    }
    with pytest.raises(ParcoursError, match="feuille_vide"):
        parcours(arbre, {"c": "a"})


# ─── renvoi_arbre (cascade explicite ZAR -> PAR) ────────────────────────────


def test_renvoi_arbre_retourne_renvoi_arbre():
    """Une branche `renvoi_arbre` ne produit pas un Resultat mais un RenvoiArbre
    que l'evaluateur resout en basculant sur l'arbre du scope cible."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "id": "q_x",
                "champ": "c",
                "branches": [{"valeur": "a", "renvoi_arbre": "region"}],
            }
        }
    }
    res = parcours(arbre, {"c": "a"})
    assert isinstance(res, RenvoiArbre)
    assert res.scope_cible == "region"
    assert "renvoi_arbre:region" in res.chemin_partiel


# ─── _valeurs_egales : int YAML vs string numerique ─────────────────────────


def _arbre_int_branche() -> dict:
    """Noeud dont une branche porte une valeur INT (ex zonage numerote)."""
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zone",
                "champ": "zone_num",
                "branches": [
                    {"valeur": 5, "regle": {"id": "r_z5", "type": "interdiction"}},
                    {"valeur": 7, "regle": {"id": "r_z7", "type": "libre"}},
                ],
            }
        }
    }


def test_int_yaml_matche_string_numerique():
    """Une valeur de contexte string '5' (ex query string) matche une branche
    `valeur: 5` (int YAML)."""
    res = parcours(_arbre_int_branche(), {"zone_num": "5"})
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_z5"


def test_int_yaml_string_non_numerique_ne_matche_pas():
    """Une string non convertible en int ne matche aucune branche int -> erreur."""
    with pytest.raises(ParcoursError):
        parcours(_arbre_int_branche(), {"zone_num": "abc"})


# ─── Collecte de questions : 1re reponse deja dans l'URL ────────────────────


def _arbre_cascade_3_niveaux() -> dict:
    """Arbre formulaire a 3 niveaux : occupation_sol -> sous_culture ->
    type_fertilisant, pour tester la collecte de questions en aval d'un
    chemin deja amorce (`_collecter_aval_si_chemin_unique`)."""
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "culture",
                "id": "q_occ",
                "champ": "occupation_sol",
                "texte": "Culture ?",
                "branches": [
                    {
                        "valeur": "mais",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "sous_culture",
                            "id": "q_sous",
                            "champ": "sous_culture",
                            "texte": "Sous-culture ?",
                            "branches": [
                                {
                                    "valeur": "grain",
                                    "noeud": {
                                        "type_noeud": "formulaire",
                                        "niveau": "type_fertilisant",
                                        "id": "q_fert",
                                        "champ": "type_fertilisant",
                                        "texte": "Type ?",
                                        "branches": [
                                            {
                                                "valeur": "type_0",
                                                "regle": {
                                                    "id": "r_fin",
                                                    "type": "libre",
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


def _noeud_racine(arbre: dict) -> dict:
    return arbre["arbre"]["noeud"]


def test_collecte_descend_le_chemin_amorce_dans_l_url():
    """Cas "1re question deja repondue dans l'URL" : on appelle directement
    `_collecter_questions` sur le noeud bloquant avec sa valeur presente dans
    le contexte. On doit recevoir la 1re question PLUS les questions en aval
    du chemin choisi (`_collecter_aval_si_chemin_unique`)."""
    noeud = _noeud_racine(_arbre_cascade_3_niveaux())
    questions = _collecter_questions(noeud, {"occupation_sol": "mais"}, {})
    champs = [q.champ for q in questions]
    assert "occupation_sol" in champs
    # La sous-question en aval du chemin choisi est collectee.
    assert "sous_culture" in champs
    # Pas de parent_champ : on suit le chemin unique, pas du conditionnel.
    q_sous = next(q for q in questions if q.champ == "sous_culture")
    assert q_sous.parent_champ is None


def test_collecte_descend_deux_niveaux_quand_amorce():
    """occupation_sol=mais ET sous_culture=grain repondus : on descend
    jusqu'a la 3e question (type_fertilisant), encore bloquante."""
    noeud = _noeud_racine(_arbre_cascade_3_niveaux())
    questions = _collecter_questions(
        noeud, {"occupation_sol": "mais", "sous_culture": "grain"}, {}
    )
    champs = [q.champ for q in questions]
    assert "sous_culture" in champs
    assert "type_fertilisant" in champs


def test_collecte_s_arrete_si_valeur_url_inconnue_en_aval():
    """occupation_sol=mais repondu mais sous_culture pointe une valeur
    inexistante : la descente s'arrete sans planter (aucune branche ne
    matche, pas de question en aval ajoutee)."""
    noeud = _noeud_racine(_arbre_cascade_3_niveaux())
    questions = _collecter_questions(
        noeud, {"occupation_sol": "mais", "sous_culture": "inexistant"}, {}
    )
    champs = [q.champ for q in questions]
    assert "sous_culture" in champs
    # On n'a pas pu descendre plus loin (valeur inconnue) -> pas de type_fert.
    assert "type_fertilisant" not in champs


def _arbre_collecte_catalogue() -> dict:
    """Arbre occupation_sol -> catalogue zone_note_5 -> QC detail, pour tester
    la traversee d'un catalogue dans `_collecter_aval_si_chemin_unique`."""
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "culture",
                "id": "q_occ",
                "champ": "occupation_sol",
                "texte": "?",
                "branches": [
                    {
                        "valeur": "colza",
                        "noeud": {
                            "type_noeud": "catalogue",
                            "id": "n_zone",
                            "champ": "zone_note_5",
                            "branches": [
                                {
                                    "valeur": True,
                                    "noeud": {
                                        "type_noeud": "formulaire",
                                        "niveau": "complement",
                                        "id": "q_apres_cat",
                                        "champ": "detail",
                                        "texte": "Detail ?",
                                        "branches": [
                                            {
                                                "valeur": "x",
                                                "regle": {
                                                    "id": "r_fin",
                                                    "type": "libre",
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


def test_collecte_aval_traverse_catalogue_resolu():
    """Un catalogue resolu dans le contexte est TRAVERSE (pas liste) pour
    atteindre la question en aval (branche type_noeud == catalogue)."""
    noeud = _noeud_racine(_arbre_collecte_catalogue())
    questions = _collecter_questions(
        noeud, {"occupation_sol": "colza", "zone_note_5": True}, {}
    )
    champs = [q.champ for q in questions]
    # Le catalogue n'est PAS une question, mais la question en aval l'est.
    assert "zone_note_5" not in champs
    assert "detail" in champs


def test_collecte_aval_s_arrete_si_catalogue_non_resolu():
    """Si le catalogue en aval n'est pas resolu dans le contexte, on ne
    descend pas plus loin (pas de question apres le catalogue)."""
    noeud = _noeud_racine(_arbre_collecte_catalogue())
    questions = _collecter_questions(noeud, {"occupation_sol": "colza"}, {})
    champs = [q.champ for q in questions]
    assert "detail" not in champs


def test_collecte_aval_traverse_catalogue_parametre():
    """Un catalogue_parametre en aval d'un chemin amorce est TRAVERSE par
    evaluation d'expression (premiere vraie) pour atteindre la question en
    aval (`_collecter_aval_si_chemin_unique`, branche catalogue_parametre)."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "culture",
                "id": "q_occ",
                "champ": "occupation_sol",
                "texte": "?",
                "branches": [
                    {
                        "valeur": "mais",
                        "noeud": {
                            "type_noeud": "catalogue_parametre",
                            "id": "n_cp",
                            "champ": "categorie",
                            "branches": [
                                {
                                    "expression": "type_fertilisant == 'digestats'",
                                    "valeur": "dig",
                                    "regle": {"id": "r_dig", "type": "libre"},
                                },
                                {
                                    "expression": "True",
                                    "valeur": "autre",
                                    "noeud": {
                                        "type_noeud": "formulaire",
                                        "niveau": "complement",
                                        "id": "q_apres_cp",
                                        "champ": "detail",
                                        "texte": "Detail ?",
                                        "branches": [
                                            {
                                                "valeur": "x",
                                                "regle": {
                                                    "id": "r_fin",
                                                    "type": "libre",
                                                },
                                            }
                                        ],
                                    },
                                },
                            ],
                        },
                    }
                ],
            }
        }
    }
    noeud = _noeud_racine(arbre)
    # type_fertilisant absent -> 1re expression fausse -> 2e (True) prise ->
    # on traverse jusqu'a la question `detail`.
    questions = _collecter_questions(noeud, {"occupation_sol": "mais"}, {})
    champs = [q.champ for q in questions]
    assert "detail" in champs


def _arbre_qc_apres_catalogue() -> dict:
    """Arbre : QC parent (plan_epandage) NON repondue, dont une branche mene a
    un catalogue SIG (resolu dans le contexte) puis a une QC descendante.

    Reproduit le bug #187 : quand la 1re QC n'est pas encore repondue, la
    collecte conditionnelle doit traverser le catalogue intermediaire pour
    prefetcher la QC en aval (sinon l'utilisateur doit relancer)."""
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "complement",
                "id": "q_plan",
                "champ": "plan_epandage",
                "texte": "Plan d'epandage ?",
                "branches": [
                    {
                        "valeur": "icpe_a",
                        "noeud": {
                            "type_noeud": "catalogue",
                            "id": "n_zone_sig",
                            "champ": "zone_note_5",
                            "branches": [
                                {
                                    "valeur": True,
                                    "noeud": {
                                        "type_noeud": "formulaire",
                                        "niveau": "complement",
                                        "id": "q_apres_sig",
                                        "champ": "detail_apres_sig",
                                        "texte": "Detail apres SIG ?",
                                        "branches": [
                                            {
                                                "valeur": "x",
                                                "regle": {
                                                    "id": "r_fin",
                                                    "type": "libre",
                                                },
                                            }
                                        ],
                                    },
                                }
                            ],
                        },
                    },
                    {
                        "valeur": "autre",
                        "regle": {"id": "r_autre", "type": "libre"},
                    },
                ],
            }
        }
    }


def test_collecte_conditionnelle_traverse_catalogue_sig(recwarn):
    """Bug #187 : la 1re QC n'est pas repondue mais le catalogue SIG en aval
    EST resolu dans le contexte (par la moulinette). La collecte conditionnelle
    doit traverser le catalogue pour prefetcher la QC descendante.

    Avant le fix, `_collecter_aval_conditionnel` s'arretait sur tout noeud
    non-`formulaire` -> `detail_apres_sig` manquait du batch."""
    noeud = _noeud_racine(_arbre_qc_apres_catalogue())
    # plan_epandage PAS dans le contexte (QC a poser), mais zone_note_5 resolu.
    questions = _collecter_questions(noeud, {"zone_note_5": True}, {})
    champs = [q.champ for q in questions]
    assert "plan_epandage" in champs  # la QC bloquante elle-meme
    assert "detail_apres_sig" in champs  # la QC descendante, via le catalogue
    # Annotee comme conditionnelle a la reponse parente icpe_a.
    q_aval = next(q for q in questions if q.champ == "detail_apres_sig")
    assert q_aval.parent_champ == "plan_epandage"
    assert q_aval.parent_valeur == "icpe_a"


def test_collecte_conditionnelle_catalogue_sig_non_resolu_sans_callback_s_arrete():
    """Sans callback de resolution et catalogue SIG absent du contexte, on ne
    peut pas savoir quelle branche prendre -> on s'arrete proprement (pas de QC
    descendante hallucinee). C'est le fallback submit."""
    noeud = _noeud_racine(_arbre_qc_apres_catalogue())
    questions = _collecter_questions(noeud, {}, {})
    champs = [q.champ for q in questions]
    assert "plan_epandage" in champs
    assert "detail_apres_sig" not in champs


def test_collecte_conditionnelle_catalogue_sig_resolu_par_callback():
    """Coeur du fix #187 : le catalogue SIG n'est PAS dans le contexte, mais un
    `resoudre_catalogue` (geo-deterministe) le resout A LA VOLEE -> le sous-arbre
    s'aplatit et la QC descendante est prefetchee, sans relance. Generique :
    marche pour tout arbre des lors que le SIG est resolvable au chargement."""

    appels = []

    def resolveur(noeud):
        # Simule la moulinette : resout zone_note_5 via geo (ici True).
        appels.append(noeud.get("champ"))
        if noeud.get("champ") == "zone_note_5":
            return True
        return None

    noeud = _noeud_racine(_arbre_qc_apres_catalogue())
    # Contexte SANS zone_note_5 : c'est le callback qui doit le fournir.
    questions = _collecter_questions(noeud, {}, {}, resoudre_catalogue=resolveur)
    champs = [q.champ for q in questions]
    assert "plan_epandage" in champs
    assert "detail_apres_sig" in champs  # prefetchee grace au callback SIG
    assert "zone_note_5" in appels  # le callback a bien ete sollicite
    q_aval = next(q for q in questions if q.champ == "detail_apres_sig")
    assert q_aval.parent_champ == "plan_epandage"
    assert q_aval.parent_valeur == "icpe_a"


def test_collecte_conditionnelle_callback_irresolvable_s_arrete():
    """Garde-fou : si le callback ne sait pas resoudre le SIG (retourne None,
    ex dataset absent), la collecte s'arrete proprement sur ce noeud -> fallback
    submit, pas de crash ni de QC hallucinee."""

    def resolveur(noeud):
        return None  # irresolvable

    noeud = _noeud_racine(_arbre_qc_apres_catalogue())
    questions = _collecter_questions(noeud, {}, {}, resoudre_catalogue=resolveur)
    champs = [q.champ for q in questions]
    assert "plan_epandage" in champs
    assert "detail_apres_sig" not in champs


def test_bug_187_qc_prefetchee_a_travers_catalogue_sur_pan(arbre_pan):
    """Non-regression #187 sur le VRAI arbre PAN : le motif de la carte est
    plan_epandage (QC) -> catalogue_parametre effluent_peu_charge -> fertilisant_iaa
    (QC). Au moment ou plan_epandage n'est pas encore repondu, fertilisant_iaa
    doit etre prefetchee dans le batch (annotee comme conditionnelle a la reponse
    parente), pour eviter que l'utilisateur relance la simulation.

    On cible le noeud plan_epandage du chemin cine_apres_0101 / type_II (celui
    de l'URL de la carte)."""
    from envergo.nitrates.yaml_tree.parcours import _build_id_index

    index = _build_id_index(arbre_pan)

    def _trouver_par_id(noeud, cible_id):
        if noeud.get("id") == cible_id:
            return noeud
        for b in noeud.get("branches", []):
            sous = b.get("noeud")
            if sous:
                r = _trouver_par_id(sous, cible_id)
                if r:
                    return r
        return None

    racine = arbre_pan["arbre"]["noeud"]
    noeud_plan = _trouver_par_id(racine, "q_cine_apres_0101_type_II_icpe")
    assert noeud_plan is not None, "noeud plan_epandage du chemin carte introuvable"
    assert noeud_plan["champ"] == "plan_epandage"

    # plan_epandage NON repondu et zone_note_5 ABSENT du contexte (etat reel au
    # chargement) : c'est le callback SIG qui doit le resoudre a la volee pour
    # aplatir le sous-arbre et prefetcher fertilisant_iaa. On simule la moulinette
    # (zone_note_5 = False pour ce point).
    def resolveur(noeud):
        if noeud.get("reference") == "zone_note_5":
            return False
        return None

    questions = _collecter_questions(
        noeud_plan,
        {"en_zone_vulnerable": True},
        index,
        resoudre_catalogue=resolveur,
    )
    champs = {q.champ for q in questions}
    assert "plan_epandage" in champs
    assert "fertilisant_iaa" in champs, (
        "fertilisant_iaa (Q6) non prefetchee : le batch s'est arrete sur le "
        "catalogue intermediaire (bug #187)"
    )
    q_aval = next(q for q in questions if q.champ == "fertilisant_iaa")
    assert q_aval.parent_champ == "plan_epandage"


def test_collecte_traverse_renvoi_vers_sous_arbre():
    """La collecte QC suit une branche `renvoi_vers` pointant vers un sous-arbre
    reutilisable (formulaire) pour prefetcher la QC descendante. Vaut pour le
    chemin amorce (`_collecter_aval_si_chemin_unique`) : la 1re question est
    repondue dans l'URL, la branche prise est un renvoi_vers."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "sous_culture",
                "id": "q_occ",
                "champ": "occupation_sol",
                "texte": "?",
                "branches": [
                    {
                        "valeur": "colza",
                        "renvoi_vers": "q_reutilisable",
                    }
                ],
            }
        },
        # Sous-arbre reutilisable, hors branche directe, atteint via renvoi_vers.
        "regles_partagees": [
            {
                "regle": {"id": "r_bidon", "type": "libre"},
            }
        ],
    }
    # Injecte le noeud reutilisable dans l'arbre (indexe par _build_id_index via
    # _walk_for_index -> il faut qu'il soit accessible depuis la racine ; on
    # l'accroche donc comme un noeud a part que l'index trouvera).
    arbre["arbre"]["noeud"]["branches"].append(
        {
            "valeur": "_indexation",
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "complement",
                "id": "q_reutilisable",
                "champ": "qc_reutilisable",
                "texte": "QC reutilisable ?",
                "branches": [
                    {"valeur": "x", "regle": {"id": "r_fin", "type": "libre"}}
                ],
            },
        }
    )
    from envergo.nitrates.yaml_tree.parcours import _build_id_index

    index = _build_id_index(arbre)
    noeud = _noeud_racine(arbre)
    # occupation_sol=colza -> branche renvoi_vers q_reutilisable.
    questions = _collecter_questions(noeud, {"occupation_sol": "colza"}, index)
    champs = [q.champ for q in questions]
    assert "qc_reutilisable" in champs


def test_collecte_renvoi_vers_cyclique_ne_boucle_pas():
    """Garde-fou anti-cycle : deux QC qui se renvoient mutuellement via
    `renvoi_vers` (q_a -> q_b -> q_a) ne doivent PAS provoquer de recursion
    infinie lors de la collecte. Les arbres reels n'ont aucun cycle, mais un
    futur editeur d'arbre pourrait en introduire un : la collecte doit terminer
    proprement (le set `_visites_renvoi` coupe la boucle)."""
    from envergo.nitrates.yaml_tree.parcours import _build_id_index

    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "complement",
                "id": "q_a",
                "champ": "champ_a",
                "texte": "A ?",
                "branches": [
                    # champ_a=go -> renvoi vers q_b (qui renverra vers q_a).
                    {"valeur": "go", "renvoi_vers": "q_b"},
                    # Branche d'indexation pour rendre q_b atteignable par l'index.
                    {
                        "valeur": "_idx",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "complement",
                            "id": "q_b",
                            "champ": "champ_b",
                            "texte": "B ?",
                            "branches": [
                                # champ_b=go -> renvoi vers q_a : cycle.
                                {"valeur": "go", "renvoi_vers": "q_a"},
                            ],
                        },
                    },
                ],
            }
        }
    }
    index = _build_id_index(arbre)
    noeud = _noeud_racine(arbre)
    # Les 2 reponses presentes forcent la descente a travers les 2 renvois : sans
    # garde-fou, q_a -> q_b -> q_a -> ... boucle. Avec, ca termine.
    questions = _collecter_questions(noeud, {"champ_a": "go", "champ_b": "go"}, index)
    # Le test PASSE des lors qu'aucune RecursionError n'est levee. On verifie au
    # passage que les 2 QC ont bien ete collectees une fois (dedup par champ).
    champs = [q.champ for q in questions]
    assert champs.count("champ_a") == 1
    assert champs.count("champ_b") == 1


# ─── collecter_qc_du_chemin ─────────────────────────────────────────────────


def test_collecter_qc_arbre_sans_racine_retourne_vide():
    assert collecter_qc_du_chemin({"arbre": {}}, {}) == []


def test_collecter_qc_du_chemin_remonte_les_complements():
    """collecter_qc_du_chemin remonte les questions de niveau `complement`
    sur le chemin courant, qu'elles soient repondues ou pas, avec leurs choix
    REELS issus de l'arbre (rendu panneau gauche)."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "culture",
                "id": "q_occ",
                "champ": "occupation_sol",
                "texte": "Culture ?",
                "branches": [
                    {
                        "valeur": "mais",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "complement",
                            "id": "q_irr",
                            "champ": "culture_irriguee",
                            "texte": "Irriguee ?",
                            "branches": [
                                {
                                    "valeur": True,
                                    "regle": {"id": "r_irr", "type": "libre"},
                                },
                                {
                                    "valeur": False,
                                    "regle": {"id": "r_non", "type": "libre"},
                                },
                            ],
                        },
                    }
                ],
            }
        }
    }
    # occupation_sol repondu, culture_irriguee PAS encore : la QC complement
    # est collectee avec ses choix, puis on s'arrete (valeur manquante).
    qc = collecter_qc_du_chemin(arbre, {"occupation_sol": "mais"})
    champs = [q.champ for q in qc]
    assert "occupation_sol" not in champs  # pas une QC (niveau culture)
    assert "culture_irriguee" in champs
    q = next(q for q in qc if q.champ == "culture_irriguee")
    valeurs = {c["valeur"] for c in q.choix}
    assert valeurs == {True, False}


def test_collecter_qc_type_fertilisant_intermediaire_apres_complement():
    """#223 : une QC de niveau `type_fertilisant` rencontree APRES un complement
    (QC de raffinement intermediaire, ex legumes PAR HdF) doit etre collectee
    pour le rendu du panneau. Sans ca, le moteur la posait mais le formulaire
    ne l'affichait jamais. Un type_fertilisant NORMAL (avant tout complement)
    ne doit PAS etre collecte (c'est la cascade principale)."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "culture",
                "id": "q_occ",
                "champ": "occupation_sol",
                "texte": "Culture ?",
                "branches": [
                    {
                        "valeur": "legumes",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "complement",
                            "id": "q_interm",
                            "champ": "implante_avant_juin",
                            "texte": "Avant le 1er juin ?",
                            "branches": [
                                {
                                    "valeur": "avant",
                                    "noeud": {
                                        "type_noeud": "formulaire",
                                        "niveau": "type_fertilisant",
                                        "id": "q_fert",
                                        "champ": "type_fertilisant",
                                        "texte": "Type fertilisant ?",
                                        "branches": [
                                            {
                                                "valeur": "type_0",
                                                "regle": {"id": "r_f", "type": "libre"},
                                            }
                                        ],
                                    },
                                },
                                {
                                    "valeur": "apres",
                                    "regle": {"id": "r_ap", "type": "libre"},
                                },
                            ],
                        },
                    }
                ],
            }
        }
    }
    # QC complement repondue -> la QC type_fertilisant INTERMEDIAIRE doit etre
    # collectee (elle vient apres le complement).
    qc = collecter_qc_du_chemin(
        arbre, {"occupation_sol": "legumes", "implante_avant_juin": "avant"}
    )
    champs = [q.champ for q in qc]
    assert "implante_avant_juin" in champs  # la QC complement
    assert "type_fertilisant" in champs, (
        "la QC type_fertilisant intermediaire (apres complement) doit etre "
        "collectee pour le rendu"
    )


def test_collecter_qc_type_fertilisant_normal_pas_collecte():
    """#223 non-regression : un type_fertilisant de cascade PRINCIPALE (sans
    complement en amont) n'est PAS collecte comme QC."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "culture",
                "id": "q_occ",
                "champ": "occupation_sol",
                "texte": "Culture ?",
                "branches": [
                    {
                        "valeur": "colza",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "type_fertilisant",
                            "id": "q_fert",
                            "champ": "type_fertilisant",
                            "texte": "Type ?",
                            "branches": [
                                {
                                    "valeur": "type_0",
                                    "regle": {"id": "r_c", "type": "libre"},
                                }
                            ],
                        },
                    }
                ],
            }
        }
    }
    qc = collecter_qc_du_chemin(arbre, {"occupation_sol": "colza"})
    assert [
        q.champ for q in qc
    ] == [], "un type_fertilisant de cascade principale ne doit pas etre collecte"


def test_collecter_qc_traverse_catalogue_parametre():
    """collecter_qc_du_chemin traverse un catalogue_parametre (pas une QC)
    via l'expression vraie pour atteindre les QC en aval (lignes 760-775)."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue_parametre",
                "id": "n_cp",
                "champ": "categorie",
                "branches": [
                    {
                        "expression": "type_fertilisant == 'digestats'",
                        "valeur": "dig",
                        "regle": {"id": "r_dig", "type": "libre"},
                    },
                    {
                        "expression": "True",
                        "valeur": "autre",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "complement",
                            "id": "q_qc",
                            "champ": "detail",
                            "texte": "Detail ?",
                            "branches": [
                                {"valeur": "x", "regle": {"id": "r", "type": "libre"}}
                            ],
                        },
                    },
                ],
            }
        }
    }
    qc = collecter_qc_du_chemin(arbre, {})
    champs = [q.champ for q in qc]
    assert "detail" in champs


def test_collecter_qc_traverse_catalogue_parametre_via_renvoi_vers():
    """Branche catalogue_parametre qui pointe en renvoi_vers vers un noeud
    reutilisable : la collecte QC suit le renvoi (lignes 766-773)."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue_parametre",
                "id": "n_cp",
                "champ": "categorie",
                "branches": [
                    {"expression": "True", "renvoi_vers": "q_partagee"},
                ],
            },
        },
        "regles_partagees": [],
    }
    # On insere le noeud cible reutilisable comme branche d'un autre noeud
    # pour qu'il soit indexe par _build_id_index.
    arbre["arbre"]["noeud"]["branches"].append(
        {
            "expression": "False",
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "complement",
                "id": "q_partagee",
                "champ": "detail",
                "texte": "Detail ?",
                "branches": [{"valeur": "x", "regle": {"id": "r", "type": "libre"}}],
            },
        }
    )
    qc = collecter_qc_du_chemin(arbre, {})
    champs = [q.champ for q in qc]
    assert "detail" in champs


def test_collecter_qc_suit_renvoi_vers_noeud():
    """Hors catalogue_parametre : une branche renvoi_vers vers un noeud
    formulaire/catalogue est suivie pour collecter les QC en aval
    (lignes 794-797)."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "culture",
                "id": "q_occ",
                "champ": "occupation_sol",
                "texte": "?",
                "branches": [
                    {"valeur": "a", "renvoi_vers": "q_partagee"},
                    {
                        "valeur": "b",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "complement",
                            "id": "q_partagee",
                            "champ": "detail",
                            "texte": "Detail ?",
                            "branches": [
                                {"valeur": "x", "regle": {"id": "r", "type": "libre"}}
                            ],
                        },
                    },
                ],
            }
        }
    }
    qc = collecter_qc_du_chemin(arbre, {"occupation_sol": "a"})
    champs = [q.champ for q in qc]
    assert "detail" in champs


def test_collecter_qc_protege_contre_les_cycles():
    """Garde-fou anti-boucle : un noeud deja visite n'est pas reparcouru
    (set `visites`, ligne 749). On simule un cycle via renvoi_vers vers un
    ancetre deja visite -> la collecte se termine sans recursion infinie."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "complement",
                "id": "q_a",
                "champ": "champ_a",
                "texte": "A ?",
                "branches": [
                    {"valeur": "boucle", "renvoi_vers": "q_a"},
                ],
            }
        }
    }
    qc = collecter_qc_du_chemin(arbre, {"champ_a": "boucle"})
    # On a collecte q_a une fois, et le renvoi vers q_a (deja visite) coupe.
    champs = [q.champ for q in qc]
    assert champs.count("champ_a") == 1


def test_collecter_qc_s_arrete_si_valeur_incoherente():
    """Si le contexte porte une valeur qui ne matche aucune branche,
    `_choisir_branche_safe` retourne None et la collecte s'arrete sans
    lever (tolerance contexte incoherent, ligne 791)."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "complement",
                "id": "q_a",
                "champ": "champ_a",
                "texte": "A ?",
                "branches": [
                    {"valeur": "ok", "regle": {"id": "r", "type": "libre"}},
                ],
            }
        }
    }
    # champ_a = valeur inconnue -> _choisir_branche_safe None -> stop, pas
    # d'exception. La QC elle-meme est quand meme collectee.
    qc = collecter_qc_du_chemin(arbre, {"champ_a": "valeur_absente"})
    champs = [q.champ for q in qc]
    assert "champ_a" in champs


def test_collecter_qc_choisir_branche_safe_fallback_type_I():
    """_choisir_branche_safe applique le meme fallback type_Ia/Ib -> type_I
    que le parcours, pour continuer la collecte QC sur ce chemin
    (lignes 809-813)."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "type_fertilisant",
                "id": "q_fert",
                "champ": "type_fertilisant",
                "texte": "Type ?",
                "branches": [
                    {
                        "valeur": "type_I",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "complement",
                            "id": "q_qc",
                            "champ": "detail",
                            "texte": "Detail ?",
                            "branches": [
                                {"valeur": "x", "regle": {"id": "r", "type": "libre"}}
                            ],
                        },
                    },
                ],
            }
        }
    }
    # type_fertilisant=type_Ia doit retomber sur la branche type_I et
    # continuer la descente jusqu'a la QC en aval.
    qc = collecter_qc_du_chemin(arbre, {"type_fertilisant": "type_Ia"})
    champs = [q.champ for q in qc]
    assert "detail" in champs


def test_collecter_qc_catalogue_parametre_sans_expression_vraie_n_ajoute_rien():
    """Si aucune expression du catalogue_parametre n'est vraie, la collecte QC
    ne plante pas et ne remonte rien (ligne 775, fallback `return`)."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue_parametre",
                "id": "n_cp",
                "champ": "categorie",
                "branches": [
                    {
                        "expression": "type_fertilisant == 'digestats'",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "complement",
                            "id": "q_qc",
                            "champ": "detail",
                            "texte": "?",
                            "branches": [
                                {"valeur": "x", "regle": {"id": "r", "type": "libre"}}
                            ],
                        },
                    },
                ],
            }
        }
    }
    # type_fertilisant absent -> expression fausse -> aucune branche prise.
    qc = collecter_qc_du_chemin(arbre, {})
    assert qc == []


# ─── QuestionsSubsidiaires.champs_set ───────────────────────────────────────


def test_questions_subsidiaires_champs_set():
    """champs_set expose l'ensemble des champs des questions (utilise cote
    template pour eviter de re-render ces champs en hidden input)."""
    res = parcours(_arbre_jouet(), {"en_zone_vulnerable": True})
    assert isinstance(res, QuestionsSubsidiaires)
    assert res.champs_set == {q.champ for q in res.questions}
    assert "occupation_sol" in res.champs_set


# ─── catalogue_parametre via parcours() (issue #128) ────────────────────────


def _arbre_catalogue_parametre() -> dict:
    """Arbre dont la racine est un catalogue_parametre : le branchement se
    fait par evaluation d'expression (premiere vraie l'emporte)."""
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue_parametre",
                "id": "n_cp",
                "champ": "categorie_resolue",
                "branches": [
                    {
                        "expression": "sous_fertilisant == 'digestats'",
                        "valeur": "dig",
                        "regle": {"id": "r_dig", "type": "interdiction"},
                    },
                    {
                        "expression": "True",
                        "valeur": "autre",
                        "regle": {"id": "r_autre", "type": "libre"},
                    },
                ],
            }
        }
    }


def test_catalogue_parametre_premiere_expression_vraie():
    """La premiere expression vraie l'emporte ; la valeur de la branche est
    ecrite dans le contexte (trace) avant de descendre."""
    contexte = {"sous_fertilisant": "digestats"}
    res = parcours(_arbre_catalogue_parametre(), contexte)
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_dig"
    # Trace : la valeur resolue est ecrite dans le contexte.
    assert contexte["categorie_resolue"] == "dig"


def test_catalogue_parametre_fallback_expression_true():
    """Si la 1re expression est fausse, on tombe sur la branche `True`."""
    res = parcours(_arbre_catalogue_parametre(), {"sous_fertilisant": "autre"})
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_autre"


def test_catalogue_parametre_aucune_expression_vraie_leve_erreur():
    """Sans branche fallback `True`, si aucune expression n'est vraie, le
    parcours leve ParcoursError (l'arbre doit couvrir tous les cas)."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue_parametre",
                "id": "n_cp",
                "champ": "categorie",
                "branches": [
                    {
                        "expression": "sous_fertilisant == 'digestats'",
                        "regle": {"id": "r_dig", "type": "libre"},
                    },
                ],
            }
        }
    }
    with pytest.raises(ParcoursError, match="aucune expression vraie"):
        parcours(arbre, {"sous_fertilisant": "autre"})


# ─── renvoi_vers avec patch (remap codes prescription) ──────────────────────


def test_renvoi_vers_avec_patch_remappe_codes_prescription():
    """Une branche renvoi_vers peut porter un `patch` qui remappe les codes de
    prescription de la feuille atteinte (ex pc12 -> pc14), pour reutiliser un
    sous-arbre en ne changeant que les PC (`_appliquer_patch`)."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "id": "q_x",
                "champ": "c",
                "branches": [
                    {
                        "valeur": "a",
                        "renvoi_vers": "r_cible",
                        "patch": {"code_prescription": {"pc12": "pc14"}},
                    },
                    {
                        "valeur": "b",
                        "regle": {
                            "id": "r_cible",
                            "type": "interdiction",
                            "code_prescription": "pc12",
                        },
                    },
                ],
            }
        }
    }
    res = parcours(arbre, {"c": "a"})
    assert isinstance(res, Resultat)
    # Le patch a remappe pc12 -> pc14 sur la feuille atteinte par renvoi.
    assert res.codes_prescription == ["pc14"]


def test_renvoi_vers_patch_laisse_intacts_codes_non_mappes():
    """Le patch ne touche que les codes presents dans le mapping ; les autres
    restent inchanges."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "id": "q_x",
                "champ": "c",
                "branches": [
                    {
                        "valeur": "a",
                        "renvoi_vers": "r_cible",
                        "patch": {"code_prescription": {"pc12": "pc14"}},
                    },
                    {
                        "valeur": "b",
                        "regle": {
                            "id": "r_cible",
                            "type": "interdiction",
                            "code_prescription": ["pc12", "pc99"],
                        },
                    },
                ],
            }
        }
    }
    res = parcours(arbre, {"c": "a"})
    assert res.codes_prescription == ["pc14", "pc99"]


# ─── _valeurs_egales : bool YAML vs string contexte ─────────────────────────


def _arbre_bool_branche() -> dict:
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_b",
                "champ": "flag",
                "branches": [
                    {"valeur": True, "regle": {"id": "r_vrai", "type": "libre"}},
                    {
                        "valeur": False,
                        "regle": {"id": "r_faux", "type": "interdiction"},
                    },
                ],
            }
        }
    }


@pytest.mark.parametrize("brut", ["true", "True", "oui", "1"])
def test_bool_true_yaml_matche_strings_vraies(brut):
    """Une branche `valeur: True` (bool YAML) matche les strings de contexte
    'true'/'oui'/'1' (ex query string), insensible a la casse."""
    res = parcours(_arbre_bool_branche(), {"flag": brut})
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_vrai"


@pytest.mark.parametrize("brut", ["false", "False", "non", "0"])
def test_bool_false_yaml_matche_strings_fausses(brut):
    res = parcours(_arbre_bool_branche(), {"flag": brut})
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_faux"


# ─── _valeurs_egales : string YAML vs bool contexte (sens inverse) ──────────
# Bug PAR Grand Est : un gate catalogue SIG renvoie un BOOLEEN (True/False),
# mais la branche YAML a ete saisie en string ('True'/'False'/'en_zge2'...).
# La comparaison doit tolerer string-booleenne vs bool, sinon no-match ->
# fallback PAN.


def _arbre_string_bool_branche() -> dict:
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_b",
                "champ": "flag",
                "branches": [
                    {"valeur": "True", "regle": {"id": "r_vrai", "type": "libre"}},
                    {
                        "valeur": "False",
                        "regle": {"id": "r_faux", "type": "interdiction"},
                    },
                ],
            }
        }
    }


def test_string_true_yaml_matche_bool_true_contexte():
    """Branche `valeur: 'True'` (string) matche le bool True du resolveur."""
    res = parcours(_arbre_string_bool_branche(), {"flag": True})
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_vrai"


def test_string_false_yaml_matche_bool_false_contexte():
    res = parcours(_arbre_string_bool_branche(), {"flag": False})
    assert isinstance(res, Resultat)
    assert res.regle_id == "r_faux"


def test_string_non_booleenne_ne_matche_pas_bool():
    """Une branche string non booleenne ('en_zge2') ne matche PAS un bool :
    c'est exactement ce qui cause le no-match d'origine -> fallback attendu."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_b",
                "champ": "flag",
                "branches": [
                    {"valeur": "en_zge2", "regle": {"id": "r_x", "type": "libre"}},
                ],
            }
        }
    }
    with pytest.raises(ParcoursError):
        parcours(arbre, {"flag": True})


# ─── normaliser_codes_prescription ──────────────────────────────────────────


def test_normaliser_codes_prescription_scalaire():
    assert normaliser_codes_prescription("pc4") == ["pc4"]


def test_normaliser_codes_prescription_none():
    assert normaliser_codes_prescription(None) == []


def test_normaliser_codes_prescription_liste_filtre_les_vides():
    """Une liste est conservee, castee en str, et les entrees vides ignorees."""
    assert normaliser_codes_prescription(["pc4", "", "pc5"]) == ["pc4", "pc5"]
    assert normaliser_codes_prescription((4, 5)) == ["4", "5"]


# ─── _collecter_aval_si_chemin_unique : branche sans noeud ──────────────────


def test_collecte_aval_branche_terminale_sans_noeud_s_arrete():
    """Quand la branche choisie en aval mene a une REGLE (pas un noeud), la
    collecte s'arrete proprement (ligne 569, `if "noeud" not in branche`)."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "culture",
                "id": "q_occ",
                "champ": "occupation_sol",
                "texte": "?",
                "branches": [
                    {"valeur": "mais", "regle": {"id": "r_fin", "type": "libre"}},
                ],
            }
        }
    }
    noeud = _noeud_racine(arbre)
    # occupation_sol repondu, sa branche mene a une regle : pas de question
    # en aval, seulement la 1re.
    questions = _collecter_questions(noeud, {"occupation_sol": "mais"}, {})
    champs = [q.champ for q in questions]
    assert champs == ["occupation_sol"]
