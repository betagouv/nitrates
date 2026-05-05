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
                    # Optionnel : regime de cette periode specifique. Si
                    # absent, on retombe sur le `type` global de la regle
                    # parente. Permet d'exprimer des regles a regimes
                    # mixtes successifs (ex: colza Type III note_5 :
                    # autorisation_sous_condition puis interdiction).
                    # Seuls les 3 regimes "vrais" sont autorises ; les
                    # types `plafonnement`, `non_applicable`,
                    # `calculatrice`, `a_completer` ne sont pas des
                    # regimes valides pour une periode.
                    "regime": {
                        "enum": [
                            "interdiction",
                            "autorisation_sous_condition",
                            "libre",
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
        # Calculatrice
        "composant": {"type": "string"},
        "inputs_requis": {
            "type": "array",
            "items": {"type": "string"},
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
# {noeud, regle, renvoi_vers}.
BRANCHE_SCHEMA = {
    "type": "object",
    "required": ["valeur"],
    "additionalProperties": False,
    "properties": {
        "valeur": {"type": ["string", "boolean", "integer"]},
        "libelle": {"type": "string"},
        "noeud": {"$ref": "#/$defs/noeud"},
        "regle": {"$ref": "#/$defs/regle"},
        "renvoi_vers": {"type": "string"},
    },
    "oneOf": [
        {"required": ["noeud"]},
        {"required": ["regle"]},
        {"required": ["renvoi_vers"]},
    ],
}

# Schema racine pour un fichier arbre national :
#   metadata: { version, source, ... }
#   arbre:    { noeud: ... }   — point d'entree de l'arbre
#   plafonnements: [ { regle: ... }, ... ]      — regles libres reutilisables
#   regles_partagees: [ { regle: ... }, ... ]   — regles cibles de renvoi_vers
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
