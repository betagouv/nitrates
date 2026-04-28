"""Sous-module qui parse, valide et marche dans l'arbre de decision YAML.

Trois primitives (cf. grammaire.yaml) : `noeud`, `branche`, `regle`.

Modules :
    schema      : JSON Schema derive de la grammaire (validation structurelle)
    loader      : chargement YAML depuis NITRATES_SPECS_DIR + cache
    validator   : checks semantiques en plus du schema (id unique, renvois,
                  references referentiels, etc.)
"""

from envergo.nitrates.yaml_tree.loader import load_arbre, load_referentiels
from envergo.nitrates.yaml_tree.validator import ValidationError, validate_arbre

__all__ = [
    "load_arbre",
    "load_referentiels",
    "validate_arbre",
    "ValidationError",
]
