"""Evaluation securisee d'expressions Python pour les noeuds
`catalogue_parametre` (cf. issue #128).

Un noeud `catalogue_parametre` choisit sa branche en evaluant, dans l'ordre,
une `expression` Python par branche : la premiere vraie l'emporte. L'expression
porte sur les variables du contexte de parcours (parametres formulaire +
catalogues deja resolus a ce point de l'arbre).

    expression: "sous_fertilisant == 'effluents_peu_charges_elevage'"
    expression: "sous_fertilisant in ('a', 'b')"
    expression: "re.match(r'.*_elevage$', sous_fertilisant or '') is not None"

⚠️ SECURITE — c'est le coeur du ticket.

Le YAML est editable par des juristes via l'admin. Un `eval()` Python nu sur
une string du YAML serait une faille RCE (`__import__('os').system(...)`).
On evalue donc dans un namespace verrouille :

  - `eval(code, {"__builtins__": {}, "re": re}, vars_sures)` : pas de builtins,
    donc pas d'`__import__`, `open`, `exec`, `eval`, `getattr`... Seuls les
    helpers explicitement whitelistes (ici `re`) sont disponibles.
  - **interdiction des attributs dunder** (analyse AST) : `__builtins__: {}`
    seul ne suffit PAS, car on peut remonter aux builtins par l'arbre des
    classes -- `().__class__.__bases__[0].__subclasses__()`, ou
    `re.__builtins__`. On rejette donc, AVANT toute evaluation, toute
    expression qui accede a un attribut commencant par `_`. Les expressions
    metier legitimes n'en utilisent jamais.
  - `vars_sures` = contexte filtre aux seuls types primitifs surs
    (str / bool / int / None). Aucun objet, aucun callable, aucune methode
    exploitable n'entre dans le scope.
  - les noms reference par l'expression mais absents du contexte valent `None`
    (c'est ainsi qu'on teste « non renseigne » : `sous_fertilisant is None`).
  - toute exception a l'evaluation (NameError, TypeError, AttributeError,
    SyntaxError...) => l'expression est consideree FAUSSE et loggee en debug.
    On ne propage jamais : une expression cassee fait juste rater sa branche.

Cette sandbox n'est PAS une garantie absolue contre un attaquant determine
ayant deja un acces ecriture au YAML (le perimetre de confiance, ce sont les
juristes authentifies en admin). Elle bloque les vecteurs RCE connus
(builtins, remontee de classes via dunder) et contient les degats d'une
expression malformee. Le `compile(... 'eval')` interdit deja
statements/imports/lambdas multi-lignes.
"""

from __future__ import annotations

import ast
import logging
import re

logger = logging.getLogger(__name__)

# Helpers explicitement autorises dans le scope d'evaluation. On reste
# minimal : `re` couvre les besoins regex de la spec. Elargir ici (et ici
# seulement) si un besoin metier whiteliste apparait.
_HELPERS_AUTORISES = {"re": re}

# Types de valeurs de contexte autorisees a entrer dans le scope d'eval.
# bool est volontairement liste meme s'il derive de int : on le garde
# explicite pour la lisibilite. Tout le reste (objets, listes, dict,
# callables, Point geos, querysets...) est ecarte.
_TYPES_SURS = (str, bool, int, type(None))


def _erreur_attribut_dangereux(expression: str) -> str | None:
    """Analyse l'AST et rejette tout acces a un attribut dunder (commencant
    par `_`). C'est le garde-fou central contre la remontee aux builtins via
    l'arbre des classes (`().__class__.__bases__[0].__subclasses__()`,
    `re.__builtins__`, `x.__globals__`...).

    Retourne un message si l'expression est dangereuse ou non parsable en
    mode 'eval', sinon None. Ne leve jamais.
    """
    try:
        arbre = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        return f"erreur de syntaxe Python ({exc.msg})"
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Attribute) and noeud.attr.startswith("_"):
            return (
                f"acces a l'attribut {noeud.attr!r} interdit "
                f"(les attributs commencant par '_' sont bloques pour des "
                f"raisons de securite)"
            )
    return None


def _vars_sures(contexte: dict) -> dict:
    """Copie du contexte filtree aux seules cles dont la valeur est d'un
    type primitif sur. Empeche tout objet (callable, methode, instance ORM)
    d'entrer dans le scope d'eval."""
    return {
        cle: val
        for cle, val in contexte.items()
        if isinstance(val, _TYPES_SURS) and isinstance(cle, str) and cle.isidentifier()
    }


def evaluer_expression(expression: str, contexte: dict) -> bool:
    """Evalue `expression` (Python) sur `contexte`, en sandbox.

    Retourne le booleen de l'evaluation. Toute erreur (syntaxe, nom absent
    non gere, type incompatible...) => False (la branche est consideree non
    prise) + log debug pour le juriste.

    Les variables referencees par l'expression mais absentes du contexte
    valent None dans le scope (modelise « non renseigne »).
    """
    if not isinstance(expression, str) or not expression.strip():
        logger.debug("expression vide ou non-string: %r", expression)
        return False

    # Garde-fou securite : rejet des attributs dunder avant toute evaluation.
    err_attr = _erreur_attribut_dangereux(expression)
    if err_attr:
        logger.debug("expression %r rejetee : %s", expression, err_attr)
        return False

    try:
        code = compile(expression, "<expression>", "eval")
    except SyntaxError as exc:
        logger.debug("expression %r : erreur de syntaxe (%s)", expression, exc)
        return False

    vars_scope = _vars_sures(contexte)

    # Les noms reference par l'expression mais absents du scope (et non
    # whitelistes) sont injectes a None, pour que `var is None` / `var or ''`
    # fonctionnent au lieu de lever NameError. On ne touche pas aux helpers.
    for nom in code.co_names:
        if nom not in vars_scope and nom not in _HELPERS_AUTORISES:
            vars_scope[nom] = None

    globals_sandbox = {"__builtins__": {}, **_HELPERS_AUTORISES}

    try:
        resultat = eval(code, globals_sandbox, vars_scope)  # noqa: S307 (sandbox)
    except Exception as exc:  # noqa: BLE001 — on neutralise toute erreur d'eval
        logger.debug(
            "expression %r : erreur a l'evaluation (%s: %s)",
            expression,
            type(exc).__name__,
            exc,
        )
        return False

    return bool(resultat)


def valider_expression(expression: str) -> str | None:
    """Verifie qu'une expression est compilable (mode 'eval'), SANS l'executer.

    Retourne None si OK, sinon un message d'erreur (pour le validator de
    grammaire). Sert a attraper les fautes de frappe juriste a la validation
    de l'arbre plutot qu'au runtime.
    """
    if not isinstance(expression, str) or not expression.strip():
        return "expression vide (chaine Python non vide attendue)"
    err = _erreur_attribut_dangereux(expression)
    if err:
        return f"expression {expression!r} : {err}"
    return None
