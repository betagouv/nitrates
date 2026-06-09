"""Sous-module qui parse, valide et parcourt l'arbre de decision YAML.

Trois primitives (cf. grammaire.yaml) : `noeud`, `branche`, `regle`.

Modules :
    schema      : JSON Schema derive de la grammaire (validation structurelle)
    loader      : chargement YAML depuis NITRATES_SPECS_DIR + cache (utilise
                  pour l'import initial et les tests du brouillon disque)
    loader_db   : chargement DB de l'arbre actif (source de verite runtime)
    validator   : checks semantiques en plus du schema (id unique, renvois,
                  references referentiels, etc.)
    parcours    : descente stateless de l'arbre depuis un contexte de reponses
"""

from envergo.nitrates.yaml_tree.loader import load_arbre, load_referentiels
from envergo.nitrates.yaml_tree.loader_db import (
    load_active_tree,
    load_active_tree_admin,
    load_active_tree_raw,
    load_tree_admin,
    load_tree_by_id,
    load_tree_raw,
)
from envergo.nitrates.yaml_tree.parcours import (
    BesoinCatalogue,
    ParcoursError,
    QuestionFormulaire,
    QuestionsSubsidiaires,
    Resultat,
    collecter_qc_du_chemin,
    parcours,
)
from envergo.nitrates.yaml_tree.validator import ValidationError, validate_arbre

__all__ = [
    "load_arbre",
    "load_referentiels",
    "load_active_tree",
    "load_active_tree_raw",
    "load_active_tree_admin",
    "load_tree_admin",
    "load_tree_by_id",
    "load_tree_raw",
    "validate_arbre",
    "ValidationError",
    "parcours",
    "Resultat",
    "QuestionsSubsidiaires",
    "QuestionFormulaire",
    "BesoinCatalogue",
    "ParcoursError",
    "collecter_qc_du_chemin",
]
