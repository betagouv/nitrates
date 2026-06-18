"""Tests de l'enumeration des feuilles (yaml_tree/feuilles.py).

Couvre les deux APIs :
  - `enumerer_feuilles_culture_principale` (tuple historique)
  - `enumerer_feuilles_culture_principale_v2` (dict enrichi)
  - `enumerer_feuilles_couvert_v2` (resolution des renvoi_vers via index)

On construit des arbres-jouets exercant chaque type de noeud (catalogue SIG,
formulaire, catalogue_parametre), chaque type de branche (noeud, regle,
renvoi_vers resolu/non resolu) et chaque enrichissement de contexte
(type_fertilisant, condition complementaire, zonage SIG).

Pas de DB : tout passe par des dicts construits a la main.
"""

from envergo.nitrates.yaml_tree.feuilles import (
    enumerer_feuilles_couvert_v2,
    enumerer_feuilles_culture_principale,
    enumerer_feuilles_culture_principale_v2,
)

# ─── Helpers de construction d'arbres ──────────────────────────────────────


def _enrober_cp(noeud_sous_cp: dict) -> dict:
    """Enrobe un noeud dans la structure standard : racine catalogue ZVN
    `n_zvn` -> formulaire occupation_sol -> branche culture_principale."""
    return {
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
                            "id": "q_occ",
                            "champ": "occupation_sol",
                            "texte": "Occupation du sol ?",
                            "branches": [
                                {
                                    "valeur": "culture_principale",
                                    "noeud": noeud_sous_cp,
                                },
                            ],
                        },
                    },
                ],
            }
        },
    }


def _enrober_couvert(noeud_sous_couvert: dict, regles_partagees=None) -> dict:
    """Idem mais branche couvert_intercultures, avec un bloc de regles
    partagees pour la resolution des renvoi_vers."""
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
                            "id": "q_occ",
                            "champ": "occupation_sol",
                            "texte": "Occupation du sol ?",
                            "branches": [
                                {
                                    "valeur": "couvert_intercultures",
                                    "noeud": noeud_sous_couvert,
                                },
                            ],
                        },
                    },
                ],
            }
        },
    }
    if regles_partagees is not None:
        arbre["regles_partagees"] = regles_partagees
    return arbre


# ─── Garde-fous de l'entree v2 (culture principale) ────────────────────────


def test_arbre_vide_renvoie_liste_vide():
    # Pas de arbre.noeud -> ligne 43.
    assert enumerer_feuilles_culture_principale_v2({}) == []
    assert enumerer_feuilles_culture_principale_v2({"arbre": {}}) == []


def test_zvn_sans_branche_oui_renvoie_liste_vide():
    # Racine n_zvn mais aucune branche valeur=True -> ligne 54.
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
                "branches": [{"valeur": False, "regle": {"id": "r_hors_zv"}}],
            }
        }
    }
    assert enumerer_feuilles_culture_principale_v2(arbre) == []


def test_racine_directe_sans_zvn_sur_occupation_sol():
    # Racine != n_zvn : on prend la racine telle quelle comme `sous` (ligne
    # 57). Ici elle est bien sur occupation_sol -> on enumere la feuille.
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "id": "q_occ",
                "champ": "occupation_sol",
                "branches": [
                    {
                        "valeur": "culture_principale",
                        "noeud": {
                            "type_noeud": "catalogue",
                            "id": "q_cult",
                            "champ": "sous_culture",
                            "branches": [
                                {"valeur": "colza", "regle": {"id": "r_colza"}},
                            ],
                        },
                    }
                ],
            }
        }
    }
    feuilles = enumerer_feuilles_culture_principale_v2(arbre)
    assert {f["regle_id"] for f in feuilles} == {"r_colza"}


def test_sous_noeud_pas_occupation_sol_renvoie_liste_vide():
    # `sous` n'est pas sur occupation_sol -> ligne 60.
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "id": "q_autre",
                "champ": "autre_chose",
                "branches": [{"valeur": "x", "regle": {"id": "r_x"}}],
            }
        }
    }
    assert enumerer_feuilles_culture_principale_v2(arbre) == []


def test_pas_de_branche_culture_principale_renvoie_liste_vide():
    # occupation_sol mais pas de branche culture_principale -> ligne 72.
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "id": "q_occ",
                "champ": "occupation_sol",
                "branches": [
                    {"valeur": "jachere", "regle": {"id": "r_jachere"}},
                ],
            }
        }
    }
    assert enumerer_feuilles_culture_principale_v2(arbre) == []


# ─── Catalogue SIG + regles directes ───────────────────────────────────────


def test_catalogue_sous_culture_principale_explore_toutes_branches():
    # Noeud catalogue (lignes 177-194) avec 3 branches -> 3 feuilles.
    noeud = {
        "type_noeud": "catalogue",
        "id": "q_cult",
        "champ": "sous_culture",
        "branches": [
            {"valeur": "colza", "regle": {"id": "r_colza"}},
            {"valeur": "luzerne", "regle": {"id": "r_luzerne"}},
            {"valeur": "ble", "regle": {"id": "r_ble"}},
        ],
    }
    feuilles = enumerer_feuilles_culture_principale_v2(_enrober_cp(noeud))
    assert {f["regle_id"] for f in feuilles} == {"r_colza", "r_luzerne", "r_ble"}
    # branche_valeur = sous_culture (lignes 294/_extract).
    par_regle = {f["regle_id"]: f for f in feuilles}
    assert par_regle["r_colza"]["branche_valeur"] == "colza"
    # Le chemin_ids contient la racine, l'occupation, le catalogue et la regle.
    assert par_regle["r_colza"]["chemin_ids"] == [
        "n_zvn",
        "q_occ",
        "q_cult",
        "r_colza",
    ]
    # Contexte cascade minimal.
    assert par_regle["r_colza"]["contexte"]["en_zone_vulnerable"] is True
    assert par_regle["r_colza"]["contexte"]["occupation_sol"] == "culture_principale"
    assert par_regle["r_colza"]["contexte"]["sous_culture"] == "colza"


# ─── API tuple historique ──────────────────────────────────────────────────


def test_api_tuple_historique():
    # Ligne 17 : la signature historique retourne des tuples.
    noeud = {
        "type_noeud": "catalogue",
        "id": "q_cult",
        "champ": "sous_culture",
        "branches": [
            {"valeur": "colza", "regle": {"id": "r_colza"}},
        ],
    }
    tuples = enumerer_feuilles_culture_principale(_enrober_cp(noeud))
    assert len(tuples) == 1
    label, contexte, regle_id = tuples[0]
    assert regle_id == "r_colza"
    assert isinstance(contexte, dict)
    assert "colza" in label


# ─── type_fertilisant + zonage + condition (enrichissement contexte) ───────


def test_type_fertilisant_zonage_et_condition_extraits():
    # Cascade : sous_culture -> type_fertilisant -> zone_note_5 (zonage)
    # -> plan_epandage (condition) -> regle. Couvre _extract (346),
    # _extract_zonage (364) et _extract_condition (355).
    noeud = {
        "type_noeud": "catalogue",
        "id": "q_cult",
        "champ": "sous_culture",
        "branches": [
            {
                "valeur": "prairie",
                "noeud": {
                    "type_noeud": "catalogue",
                    "id": "q_fert",
                    "champ": "type_fertilisant",
                    "branches": [
                        {
                            "valeur": "type_III",
                            "noeud": {
                                "type_noeud": "catalogue",
                                "id": "q_zone",
                                "champ": "zone_note_5",
                                "source": "sig",
                                "branches": [
                                    {
                                        "valeur": True,
                                        "noeud": {
                                            "type_noeud": "formulaire",
                                            "id": "q_pe",
                                            "champ": "plan_epandage",
                                            "branches": [
                                                {
                                                    "valeur": True,
                                                    "regle": {"id": "r_avec_pe"},
                                                },
                                                {
                                                    "valeur": False,
                                                    "regle": {"id": "r_sans_pe"},
                                                },
                                            ],
                                        },
                                    },
                                    {"valeur": False, "regle": {"id": "r_zone_non"}},
                                ],
                            },
                        },
                    ],
                },
            },
        ],
    }
    feuilles = enumerer_feuilles_culture_principale_v2(_enrober_cp(noeud))
    par_regle = {f["regle_id"]: f for f in feuilles}
    assert set(par_regle) == {"r_avec_pe", "r_sans_pe", "r_zone_non"}

    f_pe = par_regle["r_avec_pe"]
    assert f_pe["type_fertilisant"] == "type_III"
    assert f_pe["branche_valeur"] == "prairie"
    assert f_pe["zonage"] == "zone_note_5=True"
    assert f_pe["condition"] == "plan_epandage=True"

    # Branche zone fausse : pas de condition (None), zonage False.
    f_zn = par_regle["r_zone_non"]
    assert f_zn["zonage"] == "zone_note_5=False"
    assert f_zn["condition"] is None


def test_zonage_multiple_concatene():
    # Deux champs zonage SIG dans la cascade -> _extract_zonage les joint.
    noeud = {
        "type_noeud": "catalogue",
        "id": "q_z1",
        "champ": "zone_montagne_d113_14",
        "source": "sig",
        "branches": [
            {
                "valeur": True,
                "noeud": {
                    "type_noeud": "catalogue",
                    "id": "q_z2",
                    "champ": "zonage_prairie_III_montagne",
                    "source": "sig",
                    "branches": [
                        {"valeur": True, "regle": {"id": "r_montagne"}},
                    ],
                },
            },
        ],
    }
    feuilles = enumerer_feuilles_culture_principale_v2(_enrober_cp(noeud))
    assert len(feuilles) == 1
    assert (
        feuilles[0]["zonage"]
        == "zonage_prairie_III_montagne=True / zone_montagne_d113_14=True"
    )


def test_condition_multiple_concatene():
    noeud = {
        "type_noeud": "formulaire",
        "id": "q_c1",
        "champ": "culture_irriguee",
        "branches": [
            {
                "valeur": True,
                "noeud": {
                    "type_noeud": "formulaire",
                    "id": "q_c2",
                    "champ": "fertirrigation",
                    "branches": [
                        {"valeur": True, "regle": {"id": "r_irrig_fert"}},
                    ],
                },
            },
        ],
    }
    feuilles = enumerer_feuilles_culture_principale_v2(_enrober_cp(noeud))
    assert feuilles[0]["condition"] == "culture_irriguee=True / fertirrigation=True"


# ─── catalogue_parametre : branche sans valeur (etiquette expr) ────────────


def test_catalogue_parametre_branche_sans_valeur_etiquette_expr():
    # Une branche catalogue_parametre sans cle "valeur" -> ligne 208
    # (etiquette retombe sur l'expression, champ pas pose dans le contexte).
    noeud = {
        "type_noeud": "catalogue_parametre",
        "id": "q_origine",
        "champ": "origine",
        "branches": [
            {
                "expression": "sous_fertilisant == 'a'",
                "valeur": "elevage",
                "regle": {"id": "r_avec_valeur"},
            },
            {
                # pas de cle "valeur"
                "expression": "True",
                "regle": {"id": "r_sans_valeur"},
            },
        ],
    }
    feuilles = enumerer_feuilles_culture_principale_v2(_enrober_cp(noeud))
    par_regle = {f["regle_id"]: f for f in feuilles}
    assert set(par_regle) == {"r_avec_valeur", "r_sans_valeur"}
    # La branche avec valeur ecrit origine=elevage dans le contexte.
    assert par_regle["r_avec_valeur"]["contexte"]["origine"] == "elevage"
    # La branche sans valeur n'ecrit pas origine ; label = expr#2.
    assert "origine" not in par_regle["r_sans_valeur"]["contexte"]
    assert "origine~expr#2" in par_regle["r_sans_valeur"]["label"]


# ─── renvoi_vers non resolu (culture principale, sans index) ───────────────


def test_renvoi_vers_non_resolu_culture_principale():
    # Sans index, un renvoi_vers reste non resolu : regle_id None, segment
    # renvoi_vers: dans le chemin. Couvre lignes 300-301 / 311-312.
    noeud = {
        "type_noeud": "catalogue",
        "id": "q_cult",
        "champ": "sous_culture",
        "branches": [
            {"valeur": "colza", "renvoi_vers": "r_ailleurs"},
        ],
    }
    feuilles = enumerer_feuilles_culture_principale_v2(_enrober_cp(noeud))
    assert len(feuilles) == 1
    f = feuilles[0]
    assert f["regle_id"] is None
    assert f["chemin_ids"][-1] == "renvoi_vers:r_ailleurs"
    assert f["label"].endswith("-> r_ailleurs")
    assert f["branche_valeur"] == "colza"


# ─── enumeration couvert : index + renvoi_vers resolu ──────────────────────


def test_couvert_vide_et_garde_fous():
    assert enumerer_feuilles_couvert_v2({}) == []
    # n_zvn sans branche True.
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
                "branches": [{"valeur": False, "regle": {"id": "r_x"}}],
            }
        }
    }
    assert enumerer_feuilles_couvert_v2(arbre) == []


def test_couvert_pas_branche_couvert_renvoie_liste_vide():
    # occupation_sol present mais pas de branche couvert_intercultures.
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
                            "id": "q_occ",
                            "champ": "occupation_sol",
                            "branches": [
                                {"valeur": "culture_principale", "regle": {"id": "r"}},
                            ],
                        },
                    }
                ],
            }
        }
    }
    assert enumerer_feuilles_couvert_v2(arbre) == []


def test_couvert_racine_directe_sans_zvn():
    # Racine != n_zvn : on prend la racine telle quelle comme `sous`
    # (ligne 111). Elle est sur occupation_sol -> on enumere la feuille.
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "formulaire",
                "id": "q_occ",
                "champ": "occupation_sol",
                "branches": [
                    {
                        "valeur": "couvert_intercultures",
                        "noeud": {
                            "type_noeud": "catalogue",
                            "id": "q_type",
                            "champ": "type_couvert",
                            "branches": [
                                {"valeur": "court", "regle": {"id": "r_court"}},
                            ],
                        },
                    }
                ],
            }
        }
    }
    feuilles = enumerer_feuilles_couvert_v2(arbre)
    assert {f["regle_id"] for f in feuilles} == {"r_court"}


def test_couvert_pas_occupation_sol_renvoie_liste_vide():
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
                            "id": "q_autre",
                            "champ": "autre_chose",
                            "branches": [{"valeur": "x", "regle": {"id": "r_x"}}],
                        },
                    }
                ],
            }
        }
    }
    assert enumerer_feuilles_couvert_v2(arbre) == []


def test_couvert_renvoi_vers_resolu_vers_regle():
    # renvoi_vers pointant une regle partagee -> feuille materialisee avec
    # le regle_id de la cible. Couvre lignes 254-274 (else final) + index.
    noeud = {
        "type_noeud": "catalogue",
        "id": "q_type",
        "champ": "type_couvert",
        "branches": [
            {"valeur": "type_0", "renvoi_vers": "r_partage"},
            {"valeur": "type_I", "renvoi_vers": "r_partage"},
        ],
    }
    regles = [{"regle": {"id": "r_partage", "type": "interdiction"}}]
    feuilles = enumerer_feuilles_couvert_v2(_enrober_couvert(noeud, regles))
    # Deux branches distinctes pointant vers la meme regle restent deux
    # feuilles separees (segment de renvoi inclut la valeur de branche).
    assert len(feuilles) == 2
    for f in feuilles:
        assert f["regle_id"] == "r_partage"
        assert f["chemin_ids"][-1] == "r_partage"
    chemins = {tuple(f["chemin_ids"]) for f in feuilles}
    assert len(chemins) == 2
    # Le segment de renvoi conserve la valeur de branche.
    assert any("type_0->renvoi_vers:r_partage" in f["chemin_ids"] for f in feuilles)


def test_couvert_renvoi_vers_resolu_vers_noeud():
    # renvoi_vers pointant un sous-noeud (avec branches) -> on continue le
    # parcours dans la cible. Couvre la branche "branches" in cible (269-272).
    noeud = {
        "type_noeud": "catalogue",
        "id": "q_type",
        "champ": "type_couvert",
        "branches": [
            {"valeur": "court", "renvoi_vers": "n_sous_arbre"},
        ],
    }
    regles = [
        {
            "type_noeud": "catalogue",
            "id": "n_sous_arbre",
            "champ": "avant_31_12",
            "branches": [
                {"valeur": True, "regle": {"id": "r_avant"}},
                {"valeur": False, "regle": {"id": "r_apres"}},
            ],
        }
    ]
    feuilles = enumerer_feuilles_couvert_v2(_enrober_couvert(noeud, regles))
    assert {f["regle_id"] for f in feuilles} == {"r_avant", "r_apres"}
    # Le chemin passe par le segment de renvoi puis le sous-arbre.
    for f in feuilles:
        assert any("renvoi_vers:n_sous_arbre" in seg for seg in f["chemin_ids"])
        assert "n_sous_arbre" in f["chemin_ids"]


def test_couvert_renvoi_vers_non_resolu_si_cible_absente():
    # index actif mais cible introuvable -> renvoi non resolu (cible is None,
    # ligne 267-268), regle_id None.
    noeud = {
        "type_noeud": "catalogue",
        "id": "q_type",
        "champ": "type_couvert",
        "branches": [
            {"valeur": "court", "renvoi_vers": "id_inexistant"},
        ],
    }
    feuilles = enumerer_feuilles_couvert_v2(_enrober_couvert(noeud, []))
    assert len(feuilles) == 1
    assert feuilles[0]["regle_id"] is None
    assert feuilles[0]["chemin_ids"][-1] == "renvoi_vers:id_inexistant"


def test_couvert_renvoi_vers_branche_sans_valeur():
    # renvoi_vers resolu vers une regle, branche sans cle "valeur" :
    # le segment de renvoi est sans prefixe de valeur (ligne 262, pas 264).
    noeud = {
        "type_noeud": "catalogue_parametre",
        "id": "q_type",
        "champ": "type_couvert",
        "branches": [
            {"expression": "True", "renvoi_vers": "r_partage"},
        ],
    }
    regles = [{"regle": {"id": "r_partage", "type": "libre"}}]
    feuilles = enumerer_feuilles_couvert_v2(_enrober_couvert(noeud, regles))
    assert len(feuilles) == 1
    assert feuilles[0]["regle_id"] == "r_partage"
    assert "renvoi_vers:r_partage" in feuilles[0]["chemin_ids"]


# ─── garde-fou profondeur (boucle de renvoi_vers) ──────────────────────────


def test_garde_fou_profondeur_boucle_renvoi():
    # Deux renvois qui se pointent mutuellement -> _walk borne a profondeur
    # 60 (ligne 173-174). On verifie surtout que ca termine sans recursion
    # infinie ; l'enumeration retourne une liste finie.
    noeud = {
        "type_noeud": "catalogue",
        "id": "n_a",
        "champ": "x",
        "branches": [
            {"valeur": True, "renvoi_vers": "n_b"},
        ],
    }
    regles = [
        {
            "type_noeud": "catalogue",
            "id": "n_b",
            "champ": "y",
            "branches": [
                {"valeur": True, "renvoi_vers": "n_a"},
            ],
        }
    ]
    feuilles = enumerer_feuilles_couvert_v2(_enrober_couvert(noeud, regles))
    # La boucle est bornee : pas de regle terminale, donc aucune feuille
    # materialisee, mais surtout l'appel termine.
    assert isinstance(feuilles, list)
