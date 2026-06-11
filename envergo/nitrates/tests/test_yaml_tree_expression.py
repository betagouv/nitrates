"""Tests de l'evaluation securisee d'expressions (issue #128).

Couvre :
  - evaluation nominale (egalite, in, regex, variable absente = None, bool)
  - exception a l'eval => False (jamais de propagation)
  - SANDBOX (coeur securite) : tentatives d'evasion RCE bloquees
    (__import__, open, exec, eval, remontee de classes via dunder,
    re.__builtins__...) => toujours False, jamais d'effet de bord
  - valider_expression : compile-time, rejet syntaxe + dunder, sans executer

Pas besoin de DB ni de Django : expression.py est pur Python.
"""

import re

from envergo.nitrates.yaml_tree.expression import evaluer_expression, valider_expression

CTX = {
    "sous_fertilisant": "effluents_peu_charges_elevage",
    "type_fertilisant": "type_II",
    "zone_note_5": True,
    "plan_epandage": "icpe_a",
}


# ─── Evaluation nominale ────────────────────────────────────────────────────


def test_egalite_vraie():
    assert evaluer_expression(
        "sous_fertilisant == 'effluents_peu_charges_elevage'", CTX
    )


def test_egalite_fausse():
    assert not evaluer_expression("sous_fertilisant == 'autre_chose'", CTX)


def test_in_tuple():
    assert evaluer_expression(
        "sous_fertilisant in ('x', 'effluents_peu_charges_elevage')", CTX
    )


def test_regex_match():
    assert evaluer_expression(
        "re.match(r'.*_elevage$', sous_fertilisant or '') is not None", CTX
    )


def test_regex_search():
    assert evaluer_expression("re.search('II', type_fertilisant) is not None", CTX)


def test_variable_absente_vaut_none():
    # `fertirrigation` n'est pas dans le contexte -> None -> l'expression
    # `is None` est vraie (modelise "non renseigne").
    assert evaluer_expression("fertirrigation is None", CTX)


def test_variable_absente_or_fallback():
    assert evaluer_expression("'elevage' in (champ_absent or 'x_elevage')", CTX)


def test_combinaison_bool():
    assert evaluer_expression(
        "zone_note_5 is True and type_fertilisant == 'type_II'", CTX
    )


def test_expression_vide_est_fausse():
    assert not evaluer_expression("", CTX)
    assert not evaluer_expression("   ", CTX)
    assert not evaluer_expression(None, CTX)


def test_resultat_non_booleen_est_caste():
    # Une expression qui retourne une string non vide -> bool() -> True.
    assert evaluer_expression("sous_fertilisant", CTX) is True
    # String vide -> False.
    assert evaluer_expression("champ_absent or ''", CTX) is False


# ─── Exception a l'evaluation => False ──────────────────────────────────────


def test_erreur_de_type_est_fausse():
    # int + str leve TypeError a l'eval -> False (pas de propagation).
    assert evaluer_expression("zone_note_5 + 'x'", CTX) is False


def test_syntaxe_invalide_est_fausse():
    assert evaluer_expression("sous_fertilisant ==", CTX) is False
    assert evaluer_expression("1 +", CTX) is False


def test_appel_fonction_inexistante_est_faux():
    # `foo` n'est ni une variable ni un helper -> None -> None() => TypeError
    # -> False.
    assert evaluer_expression("foo('x')", CTX) is False


# ─── SANDBOX : tentatives d'evasion (coeur securite) ───────────────────────

EVASIONS = [
    "__import__('os').system('echo pwned')",
    "open('/etc/passwd').read()",
    "exec('import os')",
    "eval('1+1')",
    "getattr(re, 'compile')",
    "globals()",
    "locals()",
    "vars()",
    "().__class__.__bases__[0].__subclasses__()",
    "[].__class__",
    "''.__class__.__mro__[1].__subclasses__()",
    "re.__builtins__",
    "re.__class__.__init__.__globals__",
    "[x for x in ().__class__.__mro__]",
    "(lambda: __import__('os'))()",
]


def test_toutes_les_evasions_retournent_false():
    for expr in EVASIONS:
        assert evaluer_expression(expr, CTX) is False, f"evasion non bloquee: {expr}"


def test_evasion_import_n_a_aucun_effet(tmp_path):
    # On verifie qu'aucune ecriture fichier n'est possible via la sandbox.
    cible = tmp_path / "pwned.txt"
    expr = f"open({str(cible)!r}, 'w').write('x')"
    assert evaluer_expression(expr, CTX) is False
    assert not cible.exists()


def test_builtins_indisponibles():
    # Meme les builtins inoffensifs ne sont pas exposes (whitelist stricte).
    for expr in ["len('abc') > 0", "str(1) == '1'", "bool(1)", "abs(-1) == 1"]:
        assert evaluer_expression(expr, CTX) is False


def test_re_reste_disponible():
    # Seul helper whiteliste : re. Doit marcher.
    assert evaluer_expression("re.fullmatch('type_II', type_fertilisant)", CTX)


def test_objet_non_sur_exclu_du_scope():
    # Une valeur de contexte non primitive (objet, liste...) ne doit pas
    # entrer dans le scope : la variable vaut None a l'eval.
    ctx = {**CTX, "obj": object(), "liste": [1, 2], "fn": len}
    # `obj` filtre -> None -> `obj is None` vrai.
    assert evaluer_expression("obj is None", ctx) is True
    assert evaluer_expression("liste is None", ctx) is True
    assert evaluer_expression("fn is None", ctx) is True


# ─── valider_expression (compile-time) ──────────────────────────────────────


def test_valider_ok():
    assert valider_expression("sous_fertilisant == 'x'") is None
    assert valider_expression("re.match('a', sous_fertilisant or '') is None") is None


def test_valider_rejette_vide():
    assert valider_expression("") is not None
    assert valider_expression("   ") is not None
    assert valider_expression(None) is not None


def test_valider_rejette_syntaxe():
    msg = valider_expression("1 +")
    assert msg is not None
    assert "syntaxe" in msg.lower()


def test_valider_rejette_dunder():
    for expr in ["().__class__", "re.__builtins__", "x.__globals__"]:
        msg = valider_expression(expr)
        assert msg is not None, f"dunder non rejete: {expr}"
        assert "__" in msg or "interdit" in msg.lower()


def test_valider_n_execute_pas():
    # Une expression au runtime couteux / a effet de bord ne doit PAS etre
    # executee par la validation (seulement compilee). Ici on ne peut pas
    # facilement prouver l'absence d'execution, mais une expression
    # syntaxiquement valide qui leverait a l'eval (TypeError) passe la
    # validation -> preuve qu'on ne l'evalue pas.
    assert valider_expression("1 + 'a'") is None
    assert re  # re importe utilise (lint)
