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


def test_niveau_doublon_avec_champ_different_tolere():
    """Doublon de niveau tolere si les champs different (cas legitime
    interculture : sous_culture sur la duree puis sur le type de
    couvert)."""
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
    # Pas d'exception : ce n'est pas un doublon strict.
    validate_arbre(a)


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
