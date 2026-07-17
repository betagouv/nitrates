"""Tests du validateur YAML de l'arbre de decision.

Couvre :
  - structure (JSON Schema) : noeud / branche / regle, types, champs requis
  - ids uniques
  - renvoi_vers vers id existant
  - dates JJ/MM valides ou evenement phenologique connu
  - ordre des niveaux formulaire (retour interdit, doublon des 3 premiers)
  - references code_prescription / note dans referentiels
"""

import pytest

from envergo.nitrates.yaml_tree.validator import ValidationError, validate_arbre


def _arbre_minimal_valide() -> dict:
    """Arbre minimal qui passe : 1 noeud catalogue ZVN avec branches true + false.

    Les 2 valeurs booleennes doivent etre couvertes pour ne pas declencher
    l'erreur d'exhaustivite (cf. _check_branches_booleennes_exhaustives).
    """
    return {
        "metadata": {"version": "0.1.0"},
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
                "source": "sig",
                "reference": "zone_vulnerable_nitrates",
                "branches": [
                    {
                        "valeur": False,
                        "regle": {
                            "id": "r_hors_zvn",
                            "type": "non_applicable",
                            "message": "Hors ZVN",
                        },
                    },
                    {
                        "valeur": True,
                        "regle": {
                            "id": "r_en_zvn",
                            "type": "non_applicable",
                            "message": "En ZVN",
                        },
                    },
                ],
            }
        },
    }


# ─── Cas nominaux ──────────────────────────────────────────────────────────


def test_arbre_minimal_valide_passe():
    validate_arbre(_arbre_minimal_valide())


def test_arbre_avec_plafonnements_valide():
    a = _arbre_minimal_valide()
    a["plafonnements"] = [
        {
            "regle": {
                "id": "r_plafond_test",
                "type": "plafonnement",
                "plafond_azote_kg_n_ha": 70,
            }
        }
    ]
    validate_arbre(a)


def test_arbre_avec_renvoi_vers_id_existant_passe():
    """Une branche peut renvoyer vers un id de regle defini ailleurs."""
    a = _arbre_minimal_valide()
    # Ajoute une 2e branche avec un sous-noeud et un renvoi_vers la regle existante
    a["arbre"]["noeud"]["branches"].append(
        {
            "valeur": True,
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "culture",
                "id": "q_oc_sol",
                "champ": "occupation_sol",
                "texte": "Quelle occupation ?",
                "branches": [
                    {"valeur": "test", "renvoi_vers": "r_hors_zvn"},
                ],
            },
        }
    )
    validate_arbre(a)


# ─── Erreurs de structure ──────────────────────────────────────────────────


def test_arbre_sans_arbre_root_echoue():
    with pytest.raises(ValidationError) as exc:
        validate_arbre({"metadata": {}})
    assert any("arbre" in e.lower() for e in exc.value.errors)


def test_branche_avec_deux_de_noeud_regle_renvoi_echoue():
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"][0]["renvoi_vers"] = "r_qqch"
    # Maintenant la branche a regle ET renvoi_vers, ce qui viole oneOf.
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a)
    assert any("structure" in e for e in exc.value.errors)


def test_regle_avec_id_invalide_echoue():
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"][0]["regle"]["id"] = "INVALIDE_PAS_DE_PREFIXE"
    with pytest.raises(ValidationError):
        validate_arbre(a)


def test_noeud_formulaire_sans_niveau_echoue():
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append(
        {
            "valeur": True,
            "noeud": {
                "type_noeud": "formulaire",
                "id": "q_test",
                "champ": "test",
                "texte": "Texte ?",
                "branches": [
                    {
                        "valeur": "x",
                        "regle": {"id": "r_x", "type": "libre"},
                    }
                ],
            },
        }
    )
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a)
    assert any("niveau" in e for e in exc.value.errors)


# ─── Ids uniques ───────────────────────────────────────────────────────────


def test_ids_dupliques_echoue():
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append(
        {
            "valeur": True,
            "regle": {"id": "r_hors_zvn", "type": "libre"},  # meme id que la 1ere
        }
    )
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a)
    assert any("duplique" in e for e in exc.value.errors)


# ─── Renvoi_vers ───────────────────────────────────────────────────────────


def test_renvoi_vers_id_inexistant_echoue():
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append(
        {"valeur": True, "renvoi_vers": "r_inexistant"}
    )
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a)
    assert any("inexistant" in e or "r_inexistant" in e for e in exc.value.errors)


# ─── Dates ─────────────────────────────────────────────────────────────────


def test_date_invalide_echoue():
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"][0]["regle"] = {
        "id": "r_test_date",
        "type": "interdiction",
        "periodes": [{"du": "32/13", "au": "15/01"}],
    }
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a)
    assert any("date" in e for e in exc.value.errors)


def test_date_jj_mm_valide_passe():
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"][0]["regle"] = {
        "id": "r_test_date",
        "type": "interdiction",
        "periodes": [{"du": "15/12", "au": "15/01"}],
    }
    validate_arbre(a)


def test_evenement_phenologique_inconnu_echoue_si_referentiels_fournis():
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"][0]["regle"] = {
        "id": "r_test",
        "type": "interdiction",
        "periodes": [{"du": "evenement_inconnu", "au": "15/02"}],
    }
    referentiels = {
        "evenements_phenologiques": {"brunissement_soies": {}},
        "codes_prescription": {},
        "notes": {},
    }
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a, referentiels)
    assert any("evenement" in e or "phenologique" in e for e in exc.value.errors)


def test_evenement_phenologique_connu_passe():
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"][0]["regle"] = {
        "id": "r_test",
        "type": "interdiction",
        "periodes": [{"du": "brunissement_soies", "au": "15/02"}],
    }
    referentiels = {
        "evenements_phenologiques": {"brunissement_soies": {}},
        "codes_prescription": {},
        "notes": {},
    }
    validate_arbre(a, referentiels)


# ─── Ordre des niveaux formulaire ──────────────────────────────────────────


def test_niveau_formulaire_retour_arriere_echoue():
    """sous_culture qui apparait apres complement = retour interdit."""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append(
        {
            "valeur": True,
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "complement",
                "id": "q_complement",
                "champ": "x",
                "texte": "?",
                "branches": [
                    {
                        "valeur": "x",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "sous_culture",  # apres complement, interdit
                            "id": "q_back",
                            "champ": "y",
                            "texte": "?",
                            "branches": [
                                {"valeur": "z", "regle": {"id": "r_z", "type": "libre"}}
                            ],
                        },
                    }
                ],
            },
        }
    )
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a)
    assert any("retour" in e or "niveau" in e for e in exc.value.errors)


def test_champ_type_fertilisant_branches_type_mais_mauvais_champ_rejete():
    """#222 : un noeud formulaire dont les branches sont des type_* mais dont
    le champ n'est pas 'type_fertilisant' (bug PAR HdF legumes) est rejete."""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append(
        {
            "valeur": True,
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "type_fertilisant",
                "id": "q_mauvais_champ",
                "champ": "avant_le_1er_juin",  # devrait etre type_fertilisant
                "texte": "?",
                "branches": [
                    {"valeur": "type_Ia", "regle": {"id": "r_a", "type": "libre"}},
                    {"valeur": "type_II", "regle": {"id": "r_b", "type": "libre"}},
                ],
            },
        }
    )
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a)
    assert any("champ" in e for e in exc.value.errors)


def test_champ_type_fertilisant_occupation_sol_epargne():
    """#222 non-regression : un noeud niveau=culture / champ=occupation_sol
    (legitime, universel) ne doit PAS etre signale -- ses branches ne sont pas
    des type_*."""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append(
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
                        "regle": {"id": "r_cp", "type": "libre"},
                    },
                ],
            },
        }
    )
    validate_arbre(a)  # ne doit pas lever


def test_niveau_complement_puis_type_fertilisant_autorise():
    """#223 : une QC complement intermediaire suivie de type_fertilisant est
    AUTORISEE (ex : "legumes implantes avant/apres le 1er juin ?" entre la
    culture et le fertilisant, PAR HdF). Le moteur de parcours gere ce pattern ;
    la grammaire ne doit plus le bloquer."""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append(
        {
            "valeur": True,
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "complement",
                "id": "q_interm",
                "champ": "implante_avant_juin",
                "texte": "Implanté avant le 1er juin ?",
                "branches": [
                    {
                        "valeur": "avant",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "type_fertilisant",  # apres complement : OK #223
                            "id": "q_fert",
                            "champ": "type_fertilisant",
                            "texte": "?",
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
                        "regle": {"id": "r_apres", "type": "libre"},
                    },
                ],
            },
        }
    )
    # Ne doit PAS lever : c'est le cas assoupli.
    validate_arbre(a)


def test_niveau_complement_puis_culture_toujours_interdit():
    """#223 non-regression : l'assouplissement n'autorise QUE type_fertilisant
    apres complement. Un retour vers culture reste un non-sens interdit."""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append(
        {
            "valeur": True,
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "complement",
                "id": "q_interm2",
                "champ": "x",
                "texte": "?",
                "branches": [
                    {
                        "valeur": "x",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "culture",  # retour a culture : toujours interdit
                            "id": "q_back_culture",
                            "champ": "occupation_sol",
                            "texte": "?",
                            "branches": [
                                {
                                    "valeur": "z",
                                    "regle": {"id": "r_z2", "type": "libre"},
                                }
                            ],
                        },
                    }
                ],
            },
        }
    )
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a)
    assert any("retour" in e or "niveau" in e for e in exc.value.errors)


def test_niveau_formulaire_doublon_strict_meme_champ_echoue():
    """Doublon strict (meme niveau ET meme champ) interdit -- on ne pose
    pas deux fois la meme question."""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append(
        {
            "valeur": True,
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "culture",
                "id": "q_culture_1",
                "champ": "occupation_sol",
                "texte": "?",
                "branches": [
                    {
                        "valeur": "x",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "culture",
                            "id": "q_culture_2",
                            "champ": "occupation_sol",  # meme niveau + meme champ : doublon
                            "texte": "?",
                            "branches": [
                                {"valeur": "z", "regle": {"id": "r_z", "type": "libre"}}
                            ],
                        },
                    }
                ],
            },
        }
    )
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a)
    assert any("doublon" in e for e in exc.value.errors)


def test_niveau_doublon_meme_niveau_rejete_meme_champ_different():
    """Depuis l'aplatissement des couverts (spec_refactor_couverts), un
    doublon de niveau `sous_culture` est TOUJOURS rejete, meme si les
    `champ` different. L'ancienne tolerance (qui servait au niveau parasite
    sous_culture/sous_culture_couvert) a ete retiree."""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append(
        {
            "valeur": True,
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "sous_culture",
                "id": "q_sc_1",
                "champ": "sous_culture",
                "texte": "?",
                "branches": [
                    {
                        "valeur": "x",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "sous_culture",
                            "id": "q_sc_2",
                            "champ": "sous_culture_couvert",  # champ different
                            "texte": "?",
                            "branches": [
                                {"valeur": "z", "regle": {"id": "r_z", "type": "libre"}}
                            ],
                        },
                    }
                ],
            },
        }
    )
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a)
    assert any("doublon" in e for e in exc.value.errors)


def test_niveau_complement_chainable():
    """complement -> complement OK (chainage 0..N)."""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append(
        {
            "valeur": True,
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "complement",
                "id": "q_c1",
                "champ": "x",
                "texte": "?",
                "branches": [
                    {
                        "valeur": "x",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "complement",  # OK chainable
                            "id": "q_c2",
                            "champ": "y",
                            "texte": "?",
                            "branches": [
                                {"valeur": "z", "regle": {"id": "r_z", "type": "libre"}}
                            ],
                        },
                    }
                ],
            },
        }
    )
    validate_arbre(a)


def test_saut_de_niveau_autorise():
    """culture -> complement directement (saut de sous_culture et type_fertilisant)
    est autorise."""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append(
        {
            "valeur": True,
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "culture",
                "id": "q_culture",
                "champ": "x",
                "texte": "?",
                "branches": [
                    {
                        "valeur": "sol_non_cultive",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "complement",
                            "id": "q_complement",
                            "champ": "y",
                            "texte": "?",
                            "branches": [
                                {"valeur": "z", "regle": {"id": "r_z", "type": "libre"}}
                            ],
                        },
                    }
                ],
            },
        }
    )
    validate_arbre(a)


# ─── References referentiels ───────────────────────────────────────────────


def test_code_prescription_inconnu_echoue():
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"][0]["regle"] = {
        "id": "r_test",
        "type": "interdiction",
        "periodes": [{"du": "15/12", "au": "15/01"}],
        "code_prescription": "pc_inexistant",
    }
    referentiels = {
        "codes_prescription": {"pc1": {}, "pc4": {}},
        "notes": {},
        "evenements_phenologiques": {},
    }
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a, referentiels)
    assert any("pc_inexistant" in e for e in exc.value.errors)


def test_note_inconnue_echoue():
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"][0]["regle"] = {
        "id": "r_test",
        "type": "interdiction",
        "periodes": [{"du": "15/12", "au": "15/01"}],
        "note": "note_inexistante",
    }
    referentiels = {
        "codes_prescription": {},
        "notes": {"note_1": {}, "note_2": {}},
        "evenements_phenologiques": {},
    }
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a, referentiels)
    assert any("note_inexistante" in e for e in exc.value.errors)


# ─── Sur le vrai arbre PAN brouillon (charge depuis NITRATES_SPECS_DIR) ────


@pytest.mark.django_db
def test_vrai_arbre_pan_brouillon_structurellement_valide():
    """Le brouillon vit dans NITRATES_SPECS_DIR. Il doit etre structurellement
    valide (JSON Schema). Les erreurs semantiques residuelles (renvois vers
    des ids non encore crees, etc.) sont acceptees tant que c'est un brouillon ;
    on les remonte juste pour info au lieu de faire echouer le test.

    Marquage django_db ajoute en phase 4 #61 : load_referentiels() lit la DB
    desormais."""
    from envergo.nitrates.yaml_tree.loader import load_arbre, load_referentiels
    from envergo.nitrates.yaml_tree.validator import _validate_structure

    arbre = load_arbre("arbre_decision_national")
    referentiels = load_referentiels()

    # 1) la structure DOIT passer
    structure_errors = _validate_structure(arbre)
    assert (
        not structure_errors
    ), f"Brouillon structurellement invalide : {structure_errors}"

    # 2) la semantique a le droit d'avoir des warnings residuels
    try:
        validate_arbre(arbre, referentiels)
    except ValidationError as e:
        # On les imprime pour info, on ne fait pas echouer le test ;
        # le brouillon est en cours de finalisation.
        print("\nWarnings semantiques sur le brouillon PAN :")
        for err in e.errors:
            print(f"  - {err}")


# ─── Champ `regime` sur les periodes (introduit le 30/04) ───────────────────


def _arbre_avec_type_et_regime(type_regle: str, regime_periode: str) -> dict:
    """Helper pour tester combinaisons type / regime.

    Convention 2026-05-08 : type = regime principal, periode peut raffiner
    vers PLUS RESTRICTIF uniquement.
    Severite : interdiction > plafonnement > autorisation_sous_condition > libre
    """
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append(
        {
            "valeur": True,
            "regle": {
                "id": "r_regime_test",
                "type": type_regle,
                "periodes": [
                    {"du": "01/09", "au": "15/01", "regime": regime_periode},
                ],
            },
        }
    )
    return a


def test_regime_periode_idempotent_passe():
    """Une periode peut repeter le type parent (idempotent)."""
    validate_arbre(_arbre_avec_type_et_regime("interdiction", "interdiction"))
    validate_arbre(
        _arbre_avec_type_et_regime(
            "autorisation_sous_condition", "autorisation_sous_condition"
        )
    )


def test_regime_periode_raffine_vers_plus_restrictif_passe():
    """Le regime de periode peut etre PLUS restrictif que le type parent."""
    # autorisation_sous_condition raffine vers interdiction : OK (plus restrictif)
    validate_arbre(
        _arbre_avec_type_et_regime("autorisation_sous_condition", "interdiction")
    )
    # plafonnement raffine vers interdiction : OK (plus restrictif)
    validate_arbre(_arbre_avec_type_et_regime("plafonnement", "interdiction"))


def test_regime_periode_raffine_vers_plus_permissif_rejete():
    """Une periode plus PERMISSIVE que le type parent est refusee
    (convention grammaire 2026-05-08)."""
    # interdiction → autorisation_sous_condition : refus (plus permissif)
    with pytest.raises(ValidationError) as exc:
        validate_arbre(
            _arbre_avec_type_et_regime("interdiction", "autorisation_sous_condition")
        )
    assert any("plus permissif" in e for e in exc.value.errors)

    # interdiction → libre : refus (encore plus permissif)
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_type_et_regime("interdiction", "libre"))
    assert any("plus permissif" in e for e in exc.value.errors)

    # plafonnement → autorisation_sous_condition : refus (plus permissif)
    with pytest.raises(ValidationError) as exc:
        validate_arbre(
            _arbre_avec_type_et_regime("plafonnement", "autorisation_sous_condition")
        )
    assert any("plus permissif" in e for e in exc.value.errors)


def test_regime_periode_inconnu_rejete():
    """Un regime inconnu (typo, valeur libre) est refuse.

    Soit le JSON Schema attrape (enum restreint), soit le check semantique
    de regimes_coherents. Les deux messages sont acceptables tant que la
    validation echoue."""
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_type_et_regime("interdiction", "yolo"))
    assert any(
        "regime" in e and ("inconnu" in e or "is not one of" in e)
        for e in exc.value.errors
    )

    # `calculatrice` est un type de regle, pas un regime de periode.
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_type_et_regime("interdiction", "calculatrice"))
    assert any(
        "regime" in e and ("inconnu" in e or "is not one of" in e)
        for e in exc.value.errors
    )


def test_periode_sans_regime_passe_retro_compat():
    """Une periode sans champ `regime` est toujours valide (retro-compat)."""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append(
        {
            "valeur": True,
            "regle": {
                "id": "r_sans_regime",
                "type": "interdiction",
                "periodes": [{"du": "01/09", "au": "15/01"}],
            },
        }
    )
    validate_arbre(a)


def test_periodes_regime_mixte_accepte():
    """Cas colza Type III note_5 (post-bascule 2026-05-08) :
    type=autorisation_sous_condition + une periode raffinee vers interdiction."""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append(
        {
            "valeur": True,
            "regle": {
                "id": "r_regime_mixte",
                "type": "autorisation_sous_condition",
                "periodes": [
                    {
                        "du": "01/09",
                        "au": "15/10",
                        "regime": "autorisation_sous_condition",
                    },
                    {"du": "15/10", "au": "15/01", "regime": "interdiction"},
                ],
            },
        }
    )
    validate_arbre(a)


# ─── Exhaustivite booleenne ─────────────────────────────────────────────────


def test_branche_booleenne_manquante_leve_erreur_true():
    """Si on supprime la branche True d'un noeud booleen, le validator doit
    lever une erreur (un utilisateur dont le champ = True n'a pas de chemin)."""
    a = _arbre_minimal_valide()
    # Garde uniquement la branche False
    a["arbre"]["noeud"]["branches"] = [
        b for b in a["arbre"]["noeud"]["branches"] if b["valeur"] is False
    ]
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a)
    msgs = " ".join(exc.value.errors)
    assert "[exhaustivite]" in msgs
    assert "n_zvn" in msgs
    assert "True" in msgs


def test_branche_booleenne_manquante_leve_erreur_false():
    """Idem pour la branche False manquante."""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"] = [
        b for b in a["arbre"]["noeud"]["branches"] if b["valeur"] is True
    ]
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a)
    msgs = " ".join(exc.value.errors)
    assert "[exhaustivite]" in msgs
    assert "False" in msgs


def test_exhaustivite_booleenne_seulement_pour_national():
    """Un arbre booleen incomplet (branche False manquante) :
    - scope national (PAN) -> bloque (le PAN doit etre couvrant) ;
    - scope region/zar (PAR override partiel) -> PASSE (les trous sont
      legitimes, le cas non couvert retombe en cascade sur l'arbre inferieur).
    """
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"] = [
        b for b in a["arbre"]["noeud"]["branches"] if b["valeur"] is True
    ]
    # national : bloque
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a, scope="national")
    assert "[exhaustivite]" in " ".join(exc.value.errors)
    # region / zar : pas d'erreur d'exhaustivite
    for scope in ("region", "zar"):
        try:
            validate_arbre(a, scope=scope)
        except ValidationError as e:
            assert not any(
                "exhaustivite" in m for m in e.errors
            ), f"exhaustivite ne devrait pas bloquer en scope={scope}"


def test_branches_non_booleennes_ne_declenchent_pas_exhaustivite():
    """Pour les noeuds dont les branches sont des slugs (type_0, colza, ...),
    on ne contraint pas l'exhaustivite : le domaine peut etre ouvert."""
    a = _arbre_minimal_valide()
    # Remplace la branche True par un sous-noeud formulaire culture, qui a
    # une seule branche slug "colza" (pas une enum exhaustive).
    a["arbre"]["noeud"]["branches"][1] = {
        "valeur": True,
        "noeud": {
            "type_noeud": "formulaire",
            "id": "q_culture",
            "texte": "Quelle culture ?",
            "champ": "occupation_sol",
            "niveau": "culture",
            "branches": [
                {
                    "valeur": "colza",
                    "regle": {
                        "id": "r_colza",
                        "type": "interdiction",
                    },
                },
            ],
        },
    }
    # Aucune erreur d'exhaustivite : "colza" tout seul est valide.
    validate_arbre(a)


def test_arbre_national_passe_le_check_exhaustivite():
    """Garde-fou : l'arbre national packagé doit rester valide. Si ce test
    casse, c'est qu'on a introduit un check trop strict ou qu'un noeud
    booleen de l'arbre national a perdu une branche."""
    import yaml

    with open("envergo/nitrates/specs/arbre_decision_national.yaml") as f:
        arbre = yaml.safe_load(f)
    validate_arbre(arbre)


# ─── ORM-strict : checks de reference depuis la DB sans dict explicite ──────


@pytest.mark.django_db
def test_validate_arbre_lit_orm_quand_referentiels_omis():
    """Sans `referentiels` explicite, le validator lit directement les
    sets d'identifiants depuis l'ORM (CodePrescription, NoteReglementaire,
    EvenementPhenologique). Un code_prescription inconnu doit donc faire
    echouer la validation meme si l'appelant ne fournit pas de dict.

    Couvre la regression carte #61 : avant le fix, les 3 vues admin
    appelaient `validate_arbre(arbre)` sans referentiels et sautaient
    silencieusement les checks de reference."""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"][0]["regle"] = {
        "id": "r_test_orm",
        "type": "interdiction",
        "periodes": [{"du": "15/12", "au": "15/01"}],
        "code_prescription": "pc_inexistant_orm",
    }
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a)
    assert any("pc_inexistant_orm" in e for e in exc.value.errors)


@pytest.mark.django_db
def test_validate_arbre_orm_reconnait_codes_seedes():
    """Reciproque : un code_prescription qui existe en DB (seede via
    migration 0012) ne doit PAS faire echouer la validation."""
    from envergo.nitrates.models import CodePrescription

    pc_existant = CodePrescription.objects.values_list("identifiant", flat=True).first()
    assert pc_existant, "Pre-condition : au moins un CodePrescription seede"

    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"][0]["regle"] = {
        "id": "r_test_orm_ok",
        "type": "interdiction",
        "periodes": [{"du": "15/12", "au": "15/01"}],
        "code_prescription": pc_existant,
    }
    validate_arbre(a)


# ─── Type "calculatrice" : grammaire (spec 2026-05-26) ─────────────────────


def _calculatrice_regle_valide(rid="r_calc_test"):
    """Regle calculatrice minimale valide : 2 inputs, 3 periodes (dont 2
    event-based), composant ok."""
    return {
        "id": rid,
        "type": "calculatrice",
        "composant": "calendrier_dynamique_couvert",
        "inputs_requis": [
            {
                "id": "date_semis_couvert",
                "label": "Date de semis",
                "type": "date",
                "placeholder": "25/07",
            },
            {
                "id": "date_destruction_prevue",
                "label": "Date de destruction",
                "type": "date",
                "placeholder": "23/03",
            },
        ],
        "periodes": [
            {"du": "15/12", "au": "15/01", "regime": "autorisation_sous_condition"},
            {
                "du": "date_semis_couvert",
                "au": "date_semis_couvert+4semaines",
                "regime": "interdiction",
            },
            {
                "du": "date_destruction_prevue-20jours",
                "au": "date_destruction_prevue",
                "regime": "interdiction",
            },
        ],
    }


def _arbre_avec_calculatrice(regle):
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"][0]["regle"] = regle
    return a


def test_calculatrice_minimale_valide_passe():
    validate_arbre(_arbre_avec_calculatrice(_calculatrice_regle_valide()))


def test_calculatrice_sans_inputs_requis_echoue():
    r = _calculatrice_regle_valide()
    r.pop("inputs_requis")
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("inputs_requis" in e for e in exc.value.errors)


def test_calculatrice_inputs_requis_vide_echoue():
    r = _calculatrice_regle_valide()
    r["inputs_requis"] = []
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("inputs_requis" in e for e in exc.value.errors)


def test_calculatrice_input_id_non_slug_echoue():
    r = _calculatrice_regle_valide()
    r["inputs_requis"][0]["id"] = "Date Semis"  # espace + majuscule
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("slug" in e.lower() or "snake_case" in e for e in exc.value.errors)


def test_calculatrice_input_label_vide_echoue():
    r = _calculatrice_regle_valide()
    r["inputs_requis"][0]["label"] = "   "
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("label" in e for e in exc.value.errors)


def test_calculatrice_input_type_inconnu_echoue():
    r = _calculatrice_regle_valide()
    r["inputs_requis"][0]["type"] = "datetime"
    # Schema JSON refuse avant validator semantique : ValidationError attendue.
    with pytest.raises(ValidationError):
        validate_arbre(_arbre_avec_calculatrice(r))


def test_calculatrice_input_placeholder_invalide_echoue():
    r = _calculatrice_regle_valide()
    r["inputs_requis"][0]["placeholder"] = "99/99"
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("placeholder" in e for e in exc.value.errors)


def test_calculatrice_ids_dupliques_echoue():
    r = _calculatrice_regle_valide()
    r["inputs_requis"][1]["id"] = "date_semis_couvert"  # duplique le 1er
    # En sortant l'event "date_destruction_prevue" des inputs, les bornes
    # qui le referencent vont aussi echouer -- on garde la duplication
    # comme erreur principale.
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("duplique" in e for e in exc.value.errors)


def test_calculatrice_sans_periodes_echoue():
    r = _calculatrice_regle_valide()
    r["periodes"] = []
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("periodes" in e for e in exc.value.errors)


def test_calculatrice_borne_event_inconnu_echoue():
    r = _calculatrice_regle_valide()
    r["periodes"][1]["du"] = "date_inexistante"
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("date_inexistante" in e for e in exc.value.errors)


def test_calculatrice_borne_offset_unite_inconnue_echoue():
    r = _calculatrice_regle_valide()
    r["periodes"][1]["au"] = "date_semis_couvert+4annees"
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("annees" in e or "4annees" in e for e in exc.value.errors)


def test_calculatrice_borne_offset_negatif_echoue():
    r = _calculatrice_regle_valide()
    r["periodes"][1]["au"] = "date_semis_couvert+0jours"
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any(">= 1" in e for e in exc.value.errors)


def test_calculatrice_aucune_borne_event_echoue():
    """Si toutes les bornes sont des dates fixes JJ/MM, calculatrice n'a
    pas de sens -> on demande d'utiliser `type: mixte` a la place."""
    r = _calculatrice_regle_valide()
    r["periodes"] = [
        {"du": "15/12", "au": "15/01", "regime": "autorisation_sous_condition"},
        {"du": "01/03", "au": "31/05", "regime": "interdiction"},
    ]
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("event" in e for e in exc.value.errors)


def test_calculatrice_regime_inconnu_echoue():
    r = _calculatrice_regle_valide()
    r["periodes"][0]["regime"] = "yolo"
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("yolo" in e for e in exc.value.errors)


def test_calculatrice_composant_inconnu_echoue():
    r = _calculatrice_regle_valide()
    r["composant"] = "composant_imaginaire"
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    # JSON schema enum ferme : erreur de structure attendue.
    assert any(
        "composant" in e or "composant_imaginaire" in e for e in exc.value.errors
    )


def test_calculatrice_sans_composant_echoue():
    r = _calculatrice_regle_valide()
    r.pop("composant")
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("composant" in e for e in exc.value.errors)


def test_calculatrice_input_mort_echoue():
    """Un input declare mais non reference par aucune borne -> erreur."""
    r = _calculatrice_regle_valide()
    # Ajoute un input qui n'est utilise nulle part.
    r["inputs_requis"].append(
        {
            "id": "date_orpheline",
            "label": "Orpheline",
            "type": "date",
            "placeholder": "01/01",
        }
    )
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("date_orpheline" in e for e in exc.value.errors)


def test_calculatrice_back_compat_inputs_requis_legacy_strings():
    """Une regle non-calculatrice peut toujours utiliser inputs_requis sous
    forme de liste de strings (cf. pc6 fertirrigation existant)."""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"][0]["regle"] = {
        "id": "r_legacy",
        "type": "autorisation_sous_condition",
        "periodes": [{"du": "15/12", "au": "15/01"}],
        "inputs_requis": ["fertirrigation"],
    }
    validate_arbre(a)


# ─── Champ `condition` sur periodes calculatrice (spec extension) ──────────


def test_calculatrice_condition_valide_passe():
    """Une condition bien formee + input_id existant + type date passe."""
    r = _calculatrice_regle_valide()
    r["periodes"][0]["condition"] = "date_destruction_prevue >= 05/12"
    validate_arbre(_arbre_avec_calculatrice(r))


def test_calculatrice_condition_format_invalide_echoue():
    r = _calculatrice_regle_valide()
    r["periodes"][0]["condition"] = "date_destruction_prevue est tot"
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("condition" in e for e in exc.value.errors)


def test_calculatrice_condition_input_inconnu_echoue():
    r = _calculatrice_regle_valide()
    r["periodes"][0]["condition"] = "date_imaginaire < 05/12"
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any(
        "date_imaginaire" in e and "inputs_requis" in e for e in exc.value.errors
    )


def test_calculatrice_condition_date_invalide_echoue():
    """Comme pour les placeholders / bornes fixes, on accepte tout JJ/MM
    avec j in [1..31] et m in [1..12]. Un jour > 31 ou mois > 12 est rejete.
    """
    r = _calculatrice_regle_valide()
    r["periodes"][0]["condition"] = "date_destruction_prevue < 45/12"
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("45/12" in e for e in exc.value.errors)


def test_calculatrice_condition_operateur_invalide_echoue():
    r = _calculatrice_regle_valide()
    r["periodes"][0]["condition"] = "date_destruction_prevue ~ 05/12"
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("condition" in e for e in exc.value.errors)


def test_calculatrice_condition_vide_echoue():
    """Condition presente mais chaine vide -> erreur."""
    r = _calculatrice_regle_valide()
    r["periodes"][0]["condition"] = "   "
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("condition" in e for e in exc.value.errors)


def test_calculatrice_condition_tous_operateurs_passent():
    """Verifie que les 6 operateurs sont acceptes."""
    for op in ("<", "<=", ">", ">=", "==", "!="):
        r = _calculatrice_regle_valide()
        r["periodes"][0]["condition"] = f"date_destruction_prevue {op} 05/12"
        validate_arbre(_arbre_avec_calculatrice(r))


def test_calculatrice_deux_periodes_conditions_complementaires_passent():
    """Cas typique spec : 2 periodes alternatives selon condition opposees."""
    r = _calculatrice_regle_valide()
    r["periodes"] = [
        {
            "du": "15/11",
            "au": "15/01",
            "regime": "autorisation_sous_condition",
            "condition": "date_destruction_prevue >= 05/12",
        },
        {
            "du": "date_destruction_prevue-20jours",
            "au": "15/01",
            "regime": "autorisation_sous_condition",
            "condition": "date_destruction_prevue < 05/12",
        },
        {
            "du": "date_semis_couvert",
            "au": "date_semis_couvert+4semaines",
            "masque": True,
            "regime": "interdiction",
        },
    ]
    validate_arbre(_arbre_avec_calculatrice(r))


# ─── Bornage min/max des inputs date (#126) ─────────────────────────────────


def test_calculatrice_input_max_valide_passe():
    """Un input date avec max=31/12 (couvert recolte avant 31/12) passe."""
    r = _calculatrice_regle_valide()
    r["inputs_requis"][1]["max"] = "31/12"
    validate_arbre(_arbre_avec_calculatrice(r))


def test_calculatrice_input_min_valide_passe():
    """Un input date avec min=01/01 (couvert recolte apres 01/01) passe."""
    r = _calculatrice_regle_valide()
    r["inputs_requis"][1]["min"] = "01/01"
    validate_arbre(_arbre_avec_calculatrice(r))


def test_calculatrice_input_max_date_invalide_echoue():
    r = _calculatrice_regle_valide()
    r["inputs_requis"][1]["max"] = "99/12"
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("max" in e for e in exc.value.errors)


def test_calculatrice_input_min_apres_max_echoue():
    """min doit preceder max dans l'annee agricole (juil->juin)."""
    r = _calculatrice_regle_valide()
    r["inputs_requis"][1]["min"] = "01/02"
    r["inputs_requis"][1]["max"] = "31/12"
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("min" in e and "max" in e for e in exc.value.errors)


def test_calculatrice_input_min_max_meme_annee_agricole_ok():
    """15/12 (min) -> 15/01 (max) : valide car dec precede jan en annee
    agricole (la fenetre n'est pas vide)."""
    r = _calculatrice_regle_valide()
    r["inputs_requis"][1]["min"] = "15/12"
    r["inputs_requis"][1]["max"] = "15/01"
    validate_arbre(_arbre_avec_calculatrice(r))


# ─── Noeuds catalogue_parametre (#128) ──────────────────────────────────────


def _arbre_avec_catalogue_parametre(noeud_cp: dict) -> dict:
    """Enveloppe un noeud catalogue_parametre comme racine d'arbre valide."""
    return {"metadata": {"version": "test"}, "arbre": {"noeud": noeud_cp}}


def _catalogue_parametre_valide() -> dict:
    return {
        "type_noeud": "catalogue_parametre",
        "id": "q_origine",
        "champ": "effluent_peu_charge_elevage",
        "branches": [
            {
                "expression": "sous_fertilisant == 'effluents_peu_charges_elevage'",
                "valeur": True,
                "regle": {"id": "r_oui", "type": "interdiction"},
            },
            {
                "expression": "True",
                "valeur": False,
                "regle": {"id": "r_non", "type": "libre"},
            },
        ],
    }


def test_catalogue_parametre_valide_passe():
    validate_arbre(_arbre_avec_catalogue_parametre(_catalogue_parametre_valide()))


def test_catalogue_parametre_sans_expression_echoue():
    noeud = _catalogue_parametre_valide()
    # 1re branche : on retire l'expression, on met une valeur seule.
    del noeud["branches"][0]["expression"]
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_catalogue_parametre(noeud))
    assert any("expression" in e for e in exc.value.errors)


def test_catalogue_parametre_expression_vide_echoue():
    noeud = _catalogue_parametre_valide()
    noeud["branches"][0]["expression"] = "   "
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_catalogue_parametre(noeud))
    assert any("catalogue_parametre" in e for e in exc.value.errors)


def test_catalogue_parametre_syntaxe_invalide_echoue():
    noeud = _catalogue_parametre_valide()
    noeud["branches"][0]["expression"] = "sous_fertilisant =="
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_catalogue_parametre(noeud))
    assert any("syntaxe" in e.lower() for e in exc.value.errors)


def test_catalogue_parametre_dunder_rejete_a_la_validation():
    """Securite : une expression avec attribut dunder est refusee a la
    validation de l'arbre (pas seulement au runtime)."""
    noeud = _catalogue_parametre_valide()
    noeud["branches"][0]["expression"] = "().__class__.__bases__"
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_catalogue_parametre(noeud))
    assert any("interdit" in e.lower() or "__" in e for e in exc.value.errors)


def test_catalogue_parametre_valeur_bool_n_exige_pas_exhaustivite():
    """Un noeud catalogue_parametre avec valeurs true/false ne doit PAS
    declencher le check d'exhaustivite booleenne (il route par expression,
    le couple true/false n'est que tracabilite). Ici une seule branche true
    suffit a passer."""
    noeud = {
        "type_noeud": "catalogue_parametre",
        "id": "q_x",
        "champ": "origine",
        "branches": [
            {
                "expression": "True",
                "valeur": True,
                "regle": {"id": "r_seul", "type": "libre"},
            },
        ],
    }
    # Ne leve pas (pas d'erreur d'exhaustivite reclamant la branche false).
    validate_arbre(_arbre_avec_catalogue_parametre(noeud))


# ─── feuille_vide interdite dans le PAN national ────────────────────────────


def test_feuille_vide_interdite_en_scope_national():
    """Le PAN doit etre couvrant : une branche feuille_vide y est refusee.
    (Autorisee en PAR/ZAR, cf. cascade.)"""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append({"valeur": True, "feuille_vide": True})
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a, scope="national")
    assert any("feuille_vide" in e for e in exc.value.errors)


def test_feuille_vide_autorisee_en_scope_region():
    """La meme feuille_vide passe en PAR (override partiel)."""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append({"valeur": True, "feuille_vide": True})
    # Aucune erreur feuille_vide en region (les autres checks doivent passer).
    try:
        validate_arbre(a, scope="region")
    except ValidationError as e:
        assert not any("feuille_vide" in m for m in e.errors)


# ─── collect_references_sig (utilitaire de localisation des refs SIG) ───────


def test_collect_references_sig_liste_les_noeuds_sig():
    """collect_references_sig remonte (id, reference) de chaque noeud
    catalogue source=sig. Sert a savoir quels datasets importer."""
    from envergo.nitrates.yaml_tree.validator import collect_references_sig

    a = _arbre_minimal_valide()
    refs = collect_references_sig(a)
    assert ("n_zvn", "zone_vulnerable_nitrates") in refs


def test_collect_references_sig_ignore_non_sig_et_non_catalogue():
    """Un noeud non-catalogue ou un catalogue d'une autre source n'est pas
    remonte. Couvre les `continue` de filtre + un noeud catalogue sans
    reference."""
    from envergo.nitrates.yaml_tree.validator import collect_references_sig

    arbre = {
        "metadata": {"version": "t"},
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",  # pas catalogue -> ignore
                "id": "q_x",
                "champ": "occupation_sol",
                "niveau": "culture",
                "texte": "?",
                "branches": [
                    {
                        "valeur": "a",
                        "noeud": {
                            "type_noeud": "catalogue",
                            "id": "n_autre",
                            "champ": "z",
                            "source": "mapping_referentiel",  # source != sig
                            "reference": "ref_non_sig",
                            "branches": [
                                {
                                    "valeur": True,
                                    "regle": {"id": "r_t", "type": "libre"},
                                },
                                {
                                    "valeur": False,
                                    "regle": {"id": "r_f", "type": "libre"},
                                },
                            ],
                        },
                    }
                ],
            }
        },
    }
    assert collect_references_sig(arbre) == []


# ─── References SIG supportees par le backend (#) ──────────────────────────


def test_reference_sig_non_supportee_signale():
    """Si on passe un set de references supportees qui ne couvre pas la
    reference du noeud catalogue sig, le validator la signale."""
    a = _arbre_minimal_valide()
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a, references_sig_supportees={"une_autre_ref"})
    assert any(
        "[sig]" in e and "zone_vulnerable_nitrates" in e for e in exc.value.errors
    )


def test_reference_sig_supportee_passe():
    """Reference couverte par le backend -> pas d'erreur [sig]."""
    a = _arbre_minimal_valide()
    validate_arbre(a, references_sig_supportees={"zone_vulnerable_nitrates"})


# ─── _is_valid_date : robustesse aux entrees non conformes ──────────────────


def test_is_valid_date_robuste_aux_entrees_non_str():
    """_is_valid_date renvoie False sur None / chaine non parseable au lieu
    de lever (branche except ValueError/AttributeError)."""
    from envergo.nitrates.yaml_tree.validator import _is_valid_date

    assert _is_valid_date(None) is False
    assert _is_valid_date("pasunedate") is False


# ─── _check_dates : borne absente ignoree ───────────────────────────────────


def test_check_dates_ignore_borne_absente():
    """Une periode sans `au` (borne a None) ne declenche pas d'erreur de date.
    On appelle _check_dates directement car le schema impose du+au."""
    from envergo.nitrates.yaml_tree.validator import _check_dates

    arbre = {
        "arbre": {
            "noeud": {
                "branches": [
                    {
                        "regle": {
                            "id": "r_x",
                            "type": "interdiction",
                            "periodes": [{"du": "15/12", "au": None}],
                        }
                    }
                ]
            }
        }
    }
    assert _check_dates(arbre, None) == []


# ─── _check_regimes_coherents : regime inconnu (schema-bypass) ──────────────


def test_check_regimes_coherents_regime_inconnu():
    """Un regime de periode hors enum est signale. Le JSON Schema l'attraperait
    en amont via validate_arbre ; ici on teste la branche semantique en
    appelant le check directement."""
    from envergo.nitrates.yaml_tree.validator import _check_regimes_coherents

    arbre = {
        "arbre": {
            "noeud": {
                "branches": [
                    {
                        "regle": {
                            "id": "r_x",
                            "type": "interdiction",
                            "periodes": [
                                {"du": "15/12", "au": "15/01", "regime": "zzz"}
                            ],
                        }
                    }
                ]
            }
        }
    }
    errs = _check_regimes_coherents(arbre)
    assert any("inconnu" in e and "zzz" in e for e in errs)


# ─── type=mixte : exigences (>=2 periodes, regime par periode, >=2 distincts) ─


def _arbre_mixte(periodes):
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append(
        {
            "valeur": True,
            "regle": {"id": "r_mixte", "type": "mixte", "periodes": periodes},
        }
    )
    return a


def test_mixte_moins_de_deux_periodes_echoue():
    """type=mixte avec une seule periode -> erreur (mixte exige >=2)."""
    a = _arbre_mixte([{"du": "01/09", "au": "15/10", "regime": "interdiction"}])
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a)
    assert any("mixte" in e and "2 periodes" in e for e in exc.value.errors)


def test_mixte_periode_sans_regime_echoue():
    """En mixte, chaque periode doit declarer son regime (pas d'heritage)."""
    a = _arbre_mixte(
        [
            {"du": "01/09", "au": "15/10", "regime": "interdiction"},
            {"du": "15/10", "au": "15/01"},  # pas de regime
        ]
    )
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a)
    assert any("regime` obligatoire" in e for e in exc.value.errors)


def test_mixte_regime_invalide_echoue():
    """Regime de periode hors enum en mixte. Appel direct du check car le
    schema bloquerait en amont."""
    from envergo.nitrates.yaml_tree.validator import _check_regime_mixte

    arbre = {
        "arbre": {
            "noeud": {
                "branches": [
                    {
                        "regle": {
                            "id": "r_mixte",
                            "type": "mixte",
                            "periodes": [
                                {
                                    "du": "01/09",
                                    "au": "15/10",
                                    "regime": "interdiction",
                                },
                                {"du": "15/10", "au": "15/01", "regime": "zzz"},
                            ],
                        }
                    }
                ]
            }
        }
    }
    errs = _check_regime_mixte(arbre)
    assert any("invalide" in e and "zzz" in e for e in errs)


def test_mixte_un_seul_regime_distinct_echoue():
    """type=mixte avec 2 periodes mais le meme regime -> mixte n'a pas de
    sens, erreur (>=2 regimes distincts attendus)."""
    a = _arbre_mixte(
        [
            {"du": "01/09", "au": "15/10", "regime": "interdiction"},
            {"du": "15/10", "au": "15/01", "regime": "interdiction"},
        ]
    )
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a)
    assert any(">=2 regimes" in e for e in exc.value.errors)


def test_mixte_valide_passe():
    """2 periodes, 2 regimes distincts -> mixte valide."""
    a = _arbre_mixte(
        [
            {"du": "01/09", "au": "15/10", "regime": "autorisation_sous_condition"},
            {"du": "15/10", "au": "15/01", "regime": "interdiction"},
        ]
    )
    validate_arbre(a)


# ─── calculatrice : branches semantiques bypassant le schema ────────────────


def test_calculatrice_composant_legacy_skip_grammaire():
    """Un composant legacy (luzerne_post_coupe) saute la nouvelle grammaire
    calculatrice : meme sans inputs_requis/periodes, pas d'erreur."""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"][0]["regle"] = {
        "id": "r_legacy_calc",
        "type": "calculatrice",
        "composant": "luzerne_post_coupe",
        "inputs_requis": ["date_coupe"],
    }
    validate_arbre(a)


def test_calculatrice_input_non_dict_echoue():
    """Un input qui n'est pas un objet (ex string melange a des objets) sur une
    regle calculatrice -> erreur. Appel direct car le schema oneOf interdit le
    melange mais le check protege quand meme la shape."""
    from envergo.nitrates.yaml_tree.validator import _check_calculatrice

    arbre = {
        "arbre": {
            "noeud": {
                "branches": [
                    {
                        "regle": {
                            "id": "r_calc",
                            "type": "calculatrice",
                            "composant": "calendrier_dynamique_couvert",
                            "inputs_requis": ["pas_un_objet"],
                            "periodes": [
                                {"du": "date_x", "au": "date_x+2jours"},
                            ],
                        }
                    }
                ]
            }
        }
    }
    errs = _check_calculatrice(arbre)
    assert any("doit etre un" in e and "objet" in e for e in errs)


def test_calculatrice_input_type_invalide_echoue():
    """Un input dont le `type` n'est pas 'date' -> erreur semantique.
    Appel direct (schema enum bloquerait via validate_arbre)."""
    from envergo.nitrates.yaml_tree.validator import _check_calculatrice

    arbre = {
        "arbre": {
            "noeud": {
                "branches": [
                    {
                        "regle": {
                            "id": "r_calc",
                            "type": "calculatrice",
                            "composant": "calendrier_dynamique_couvert",
                            "inputs_requis": [
                                {
                                    "id": "date_x",
                                    "label": "X",
                                    "type": "datetime",
                                    "placeholder": "01/01",
                                }
                            ],
                            "periodes": [{"du": "date_x", "au": "date_x+2jours"}],
                        }
                    }
                ]
            }
        }
    }
    errs = _check_calculatrice(arbre)
    assert any("`type` doit" in e for e in errs)


def test_calculatrice_label_court_invalide_echoue():
    """`label_court` present mais vide -> erreur."""
    r = _calculatrice_regle_valide()
    r["inputs_requis"][0]["label_court"] = "   "
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre_avec_calculatrice(r))
    assert any("label_court" in e for e in exc.value.errors)


def test_calculatrice_borne_absente_ignoree():
    """Une borne (du/au) absente est ignoree par _check_calculatrice (continue).
    Appel direct car le schema impose du+au."""
    from envergo.nitrates.yaml_tree.validator import _check_calculatrice

    arbre = {
        "arbre": {
            "noeud": {
                "branches": [
                    {
                        "regle": {
                            "id": "r_calc",
                            "type": "calculatrice",
                            "composant": "calendrier_dynamique_couvert",
                            "inputs_requis": [
                                {"id": "date_x", "label": "X", "type": "date"}
                            ],
                            # 'au' absent : la borne None est sautee, mais 'du'
                            # reference bien un event -> calculatrice valide.
                            "periodes": [{"du": "date_x"}],
                        }
                    }
                ]
            }
        }
    }
    errs = _check_calculatrice(arbre)
    # Aucune erreur liee a la borne 'au' absente.
    assert not any("au :" in e for e in errs)


def test_calculatrice_regime_inconnu_appel_direct():
    """Regime de periode calculatrice hors enum -> erreur. Appel direct
    (schema enum bloquerait via validate_arbre)."""
    from envergo.nitrates.yaml_tree.validator import _check_calculatrice

    arbre = {
        "arbre": {
            "noeud": {
                "branches": [
                    {
                        "regle": {
                            "id": "r_calc",
                            "type": "calculatrice",
                            "composant": "calendrier_dynamique_couvert",
                            "inputs_requis": [
                                {"id": "date_x", "label": "X", "type": "date"}
                            ],
                            "periodes": [
                                {"du": "date_x", "au": "date_x+2jours", "regime": "zzz"}
                            ],
                        }
                    }
                ]
            }
        }
    }
    errs = _check_calculatrice(arbre)
    assert any("regime" in e and "zzz" in e for e in errs)


def test_calculatrice_composant_inconnu_appel_direct():
    """Composant hors liste fermee -> erreur. Appel direct (schema enum
    bloquerait via validate_arbre)."""
    from envergo.nitrates.yaml_tree.validator import _check_calculatrice

    arbre = {
        "arbre": {
            "noeud": {
                "branches": [
                    {
                        "regle": {
                            "id": "r_calc",
                            "type": "calculatrice",
                            "composant": "composant_bidon",
                            "inputs_requis": [
                                {"id": "date_x", "label": "X", "type": "date"}
                            ],
                            "periodes": [{"du": "date_x", "au": "date_x+2jours"}],
                        }
                    }
                ]
            }
        }
    }
    errs = _check_calculatrice(arbre)
    assert any("composant" in e and "composant_bidon" in e for e in errs)


# ─── _check_catalogue_parametre : branches absentes / non dict ──────────────


def test_catalogue_parametre_sans_branches_echoue():
    """Un noeud catalogue_parametre sans branche -> erreur (au moins une
    branche avec expression). Appel direct car le schema impose minItems=1."""
    from envergo.nitrates.yaml_tree.validator import _check_catalogue_parametre

    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue_parametre",
                "id": "q_cp",
                "champ": "origine",
                "branches": [],
            }
        }
    }
    errs = _check_catalogue_parametre(arbre)
    assert any("au moins une branche" in e for e in errs)


def test_catalogue_parametre_racine_non_dict_pas_d_erreur():
    """Si la racine n'est pas un dict, _check_catalogue_parametre ne plante
    pas et ne remonte rien."""
    from envergo.nitrates.yaml_tree.validator import _check_catalogue_parametre

    assert _check_catalogue_parametre({"arbre": {"noeud": None}}) == []


# ─── _check_niveaux_formulaire : niveau hors ordre connu ────────────────────


def test_niveau_hors_ordre_connu_ignore():
    """Un niveau formulaire non present dans NIVEAUX_FORMULAIRE_ORDRE est
    ignore par le check d'ordre (deja attrape par le schema). Appel direct de
    _check_niveau_ajout."""
    from envergo.nitrates.yaml_tree.validator import _check_niveau_ajout

    assert _check_niveau_ajout([], "niveau_exotique", "champ", "q_x") is None


def test_niveau_retour_arriere_pur_echoue():
    """sous_culture apres type_fertilisant (sans complement intermediaire) =
    retour en arriere pur (idx_nouveau < idx_prec). Couvre la branche
    distincte de la regle 'apres complement'."""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"].append(
        {
            "valeur": True,
            "noeud": {
                "type_noeud": "formulaire",
                "niveau": "type_fertilisant",
                "id": "q_tf",
                "champ": "type_fertilisant",
                "texte": "?",
                "branches": [
                    {
                        "valeur": "type_0",
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "sous_culture",  # retour arriere
                            "id": "q_sc",
                            "champ": "sous_culture",
                            "texte": "?",
                            "branches": [
                                {"valeur": "z", "regle": {"id": "r_z", "type": "libre"}}
                            ],
                        },
                    }
                ],
            },
        }
    )
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a)
    assert any("retour en arriere" in e for e in exc.value.errors)


# ─── _check_references_referentiels : doublon + patch renvoi_vers ───────────


def test_code_prescription_doublon_echoue():
    """Lister deux fois le meme code_prescription sur une regle -> erreur de
    doublon."""
    a = _arbre_minimal_valide()
    a["arbre"]["noeud"]["branches"][0]["regle"] = {
        "id": "r_dup_pc",
        "type": "interdiction",
        "periodes": [{"du": "15/12", "au": "15/01"}],
        "code_prescription": ["pc1", "pc1"],
    }
    referentiels = {
        "codes_prescription": {"pc1": {}},
        "notes": {},
        "evenements_phenologiques": {},
    }
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a, referentiels)
    assert any("doublon" in e for e in exc.value.errors)


def test_patch_renvoi_vers_code_prescription_inconnu_echoue():
    """Le remap code_prescription d'un patch sur branche renvoi_vers doit
    pointer vers des PC connus (source ET cible)."""
    a = _arbre_minimal_valide()
    # Une regle cible existante pour le renvoi.
    a["plafonnements"] = [{"regle": {"id": "r_cible", "type": "libre"}}]
    a["arbre"]["noeud"]["branches"].append(
        {
            "valeur": True,
            "renvoi_vers": "r_cible",
            "patch": {"code_prescription": {"pc1": "pc_inconnu_dst"}},
        }
    )
    referentiels = {
        "codes_prescription": {"pc1": {}},
        "notes": {},
        "evenements_phenologiques": {},
    }
    with pytest.raises(ValidationError) as exc:
        validate_arbre(a, referentiels)
    assert any("pc_inconnu_dst" in e for e in exc.value.errors)


# ─── Robustesse : gardes defensives (entrees non conformes) ─────────────────


def test_parse_borne_calculatrice_valeur_vide():
    """Une borne vide est rejetee par _parse_borne_calculatrice."""
    from envergo.nitrates.yaml_tree.validator import _parse_borne_calculatrice

    is_event, err = _parse_borne_calculatrice("", set())
    assert is_event is False
    assert err == "valeur vide"


def test_sig_supportees_ignore_formulaire_et_catalogue_non_sig():
    """Un noeud formulaire (non catalogue) et un catalogue source!=sig ne sont
    pas verifies par _check_references_sig_supportees (branches continue)."""
    arbre = {
        "metadata": {"version": "t"},
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_autre_source",
                "champ": "z",
                "source": "mapping_referentiel",  # source != sig -> ignore
                "reference": "ref_non_sig",
                "branches": [
                    {
                        "valeur": True,
                        "noeud": {
                            "type_noeud": "formulaire",  # non catalogue -> ignore
                            "id": "q_x",
                            "champ": "occupation_sol",
                            "niveau": "culture",
                            "texte": "?",
                            "branches": [
                                {"valeur": "a", "regle": {"id": "r_a", "type": "libre"}}
                            ],
                        },
                    },
                    {
                        "valeur": False,
                        "regle": {"id": "r_f", "type": "libre"},
                    },
                ],
            }
        },
    }
    from envergo.nitrates.yaml_tree.validator import _check_references_sig_supportees

    # Aucune reference sig a verifier -> liste vide, pas d'erreur.
    assert _check_references_sig_supportees(arbre, set()) == []


def test_checks_robustes_aux_noeuds_non_dict():
    """Les checks qui parcourent l'arbre tolerent un noeud/objet non-dict
    (garde defensive) sans planter. On passe une racine None / des branches
    non-dict."""
    from envergo.nitrates.yaml_tree.validator import (
        _check_branches_booleennes_exhaustives,
        _check_references_referentiels,
    )

    # Racine None -> pas d'exhaustivite.
    assert _check_branches_booleennes_exhaustives({"arbre": {"noeud": None}}) == []
    # Un walk avec un objet non-dict (plafonnement vide) ne plante pas.
    arbre = {"arbre": {"noeud": None}, "plafonnements": []}
    assert _check_references_referentiels(arbre, {}) == []
