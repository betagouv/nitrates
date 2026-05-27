"""JSON Schema derive de specs/decision_tree_yaml/grammaire.yaml.

Valide la structure recursive `noeud` / `branche` / `regle`. Les checks
semantiques (id unique, renvoi_vers existant, references referentiels) sont
faits dans validator.py — pas dans le schema.
"""

# Primitive `regle` : feuille terminale, 5 types factuels + 1 type calculatrice.
REGLE_SCHEMA = {
    "type": "object",
    "required": ["id"],
    "additionalProperties": False,
    # `type` est requis sauf si la regle est marquee `a_completer: true`
    # (stub brouillon, pas encore typee).
    "anyOf": [
        {"required": ["type"]},
        {"properties": {"a_completer": {"const": True}}, "required": ["a_completer"]},
    ],
    "properties": {
        "id": {"type": "string", "pattern": "^r_[a-zA-Z0-9_]+$"},
        "type": {
            "enum": [
                "interdiction",
                "autorisation_sous_condition",
                "plafonnement",
                "libre",
                "non_applicable",
                "calculatrice",
                "mixte",
            ]
        },
        "periodes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["du", "au"],
                "additionalProperties": False,
                "properties": {
                    "du": {"type": "string"},
                    "au": {"type": "string"},
                    # Regime : permet d'avoir une regle "interdiction" globale
                    # avec des periodes ou cette interdiction est reduite a
                    # une autorisation_sous_condition (ex: colza Type III
                    # autorise sous condition entre 01/09 et 15/10, interdit
                    # ensuite). Le `regime` de la periode prevaut sur le
                    # `type` de la regle parente pour la fenetre concernee.
                    "regime": {
                        "enum": [
                            "interdiction",
                            "autorisation_sous_condition",
                            "plafonnement",
                            "libre",
                            "non_applicable",
                        ]
                    },
                },
            },
        },
        "code_prescription": {"type": "string"},
        "note": {"type": "string"},
        "source_juridique": {"type": "string"},
        "message": {"type": "string"},
        "texte": {"type": "string"},
        "texte_condition": {"type": "string"},
        # Plafonnement
        "plafond_azote_kg_n_ha": {"type": "number"},
        # Libre
        "plafonnement_associe": {"type": "string"},
        # Calculatrice : composant front fermé (cf. spec grammaire calculatrice
        # 2026-05-26). On garde les 2 composants legacy de l'arbre PAN actuel
        # (`luzerne_post_coupe`, `fenetre_epandage`) en attendant leur
        # migration vers la nouvelle grammaire / le nouveau composant.
        "composant": {
            "type": "string",
            "enum": [
                "calendrier_dynamique_couvert",
                "luzerne_post_coupe",
                "fenetre_epandage",
            ],
        },
        # `inputs_requis` accepte 2 shapes (back-compat) :
        #   - array de strings : forme legacy utilisée par types non-calculatrice
        #     (ex pc6 `fertirrigation`), simple liste de slugs.
        #   - array d'objets {id, label, type, placeholder} : forme calculatrice
        #     pour le mini-formulaire de saisie utilisateur (cf. spec
        #     grammaire calculatrice 2026-05-26).
        # Le validator durcit la shape selon `type` de la règle.
        "inputs_requis": {
            "type": "array",
            "items": {
                "oneOf": [
                    {"type": "string"},
                    {
                        "type": "object",
                        "required": ["id", "label", "type"],
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            # Libelle court pour les etiquettes du calendrier
                            # dynamique (cf. spec_rendu_simulateur_calculatrice.md).
                            # Optionnel : fallback heuristique cote rendu si
                            # absent (prendre les 1-2 premiers mots du `label`
                            # apres "de").
                            "label_court": {"type": "string"},
                            "type": {"enum": ["date"]},
                            "placeholder": {"type": "string"},
                        },
                    },
                ]
            },
        },
        "parametres": {"type": "object"},
        # Marqueur brouillon : regle non finalisee, a completer plus tard.
        "a_completer": {"type": "boolean"},
    },
}

# Primitive `noeud` : interne, soit "formulaire" (question utilisateur), soit
# "catalogue" (donnee resolue automatiquement).
NOEUD_SCHEMA = {
    "type": "object",
    "required": ["type_noeud", "id", "champ", "branches"],
    "properties": {
        "type_noeud": {"enum": ["formulaire", "catalogue"]},
        "id": {"type": "string", "pattern": "^[qn]_[a-zA-Z0-9_]+$"},
        "champ": {"type": "string"},
        "branches": {
            "type": "array",
            "minItems": 1,
            "items": {"$ref": "#/$defs/branche"},
        },
        # Champs formulaire
        "niveau": {
            "enum": ["culture", "sous_culture", "type_fertilisant", "complement"]
        },
        "texte": {"type": "string"},
        "aide": {"type": "string"},
        # Champs catalogue
        "source": {"enum": ["sig", "mapping_referentiel", "calcul"]},
        "reference": {"type": "string"},
    },
    "allOf": [
        # Si type_noeud=formulaire, niveau est requis
        {
            "if": {"properties": {"type_noeud": {"const": "formulaire"}}},
            "then": {"required": ["niveau", "texte"]},
        },
        # Si type_noeud=catalogue, source est requis
        {
            "if": {"properties": {"type_noeud": {"const": "catalogue"}}},
            "then": {"required": ["source"]},
        },
    ],
}

# Primitive `branche` : reponse possible. Doit contenir EXACTEMENT UN de
# {noeud, regle, renvoi_vers} et EXACTEMENT UN de {valeur, valeurs}.
#
# `valeurs: [a, b]` (pluriel) permet de grouper plusieurs valeurs sur une
# meme branche (ex `plan_epandage` qui matche `icpe_e_ou_d` = soit `icpe_e`
# soit `icpe_d`). Le walker du parcours teste l'appartenance a la liste.
# Cf. #61 phase 3 : extension de la grammaire pour les regroupements DB.
BRANCHE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "valeur": {"type": ["string", "boolean", "integer"]},
        "valeurs": {
            "type": "array",
            "minItems": 1,
            "items": {"type": ["string", "boolean", "integer"]},
        },
        "libelle": {"type": "string"},
        "noeud": {"$ref": "#/$defs/noeud"},
        "regle": {"$ref": "#/$defs/regle"},
        "renvoi_vers": {"type": "string"},
    },
    "allOf": [
        # Exactement un de {valeur, valeurs} :
        {
            "oneOf": [
                {"required": ["valeur"]},
                {"required": ["valeurs"]},
            ]
        },
        # Exactement un de {noeud, regle, renvoi_vers} :
        {
            "oneOf": [
                {"required": ["noeud"]},
                {"required": ["regle"]},
                {"required": ["renvoi_vers"]},
            ]
        },
    ],
}

# Schema racine pour un fichier arbre national :
#   metadata: { version, source, ... }
#   arbre:    { noeud: ... }   — point d'entree de l'arbre
#   plafonnements: [ { regle: ... }, ... ]   — regles libres reutilisables
ARBRE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["arbre"],
    "properties": {
        "metadata": {"type": "object"},
        "arbre": {
            "type": "object",
            "required": ["noeud"],
            "additionalProperties": False,
            "properties": {"noeud": {"$ref": "#/$defs/noeud"}},
        },
        "plafonnements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["regle"],
                "properties": {"regle": {"$ref": "#/$defs/regle"}},
            },
        },
        # Regles reutilisables top-level, ciblees par renvoi_vers depuis
        # n'importe quelle branche. Utile pour les regles communes (ex:
        # couvert d'interculture courte, plafonds, etc.).
        "regles_partagees": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["regle"],
                "properties": {"regle": {"$ref": "#/$defs/regle"}},
            },
        },
    },
    "$defs": {
        "noeud": NOEUD_SCHEMA,
        "branche": BRANCHE_SCHEMA,
        "regle": REGLE_SCHEMA,
    },
}


# Schema pour un fichier d'override regional (PAR).
OVERRIDE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["metadata", "overrides"],
    "properties": {
        "metadata": {
            "type": "object",
            "required": ["region"],
            "properties": {
                "region": {"type": "string", "pattern": "^R[0-9]+$"},
            },
        },
        "overrides": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["remplace", "par"],
                "additionalProperties": False,
                "properties": {
                    "remplace": {"type": "string"},
                    "par": {
                        "type": "object",
                        "required": ["regle"],
                        "additionalProperties": False,
                        "properties": {"regle": {"$ref": "#/$defs/regle"}},
                    },
                },
            },
        },
    },
    "$defs": {
        "regle": REGLE_SCHEMA,
    },
}
