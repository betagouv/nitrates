"""Grammaire d'edition du draft -- regles contextuelles utilisees par
l'editeur htmx (etape 5b).

Trois niveaux de validation distincts :

  1. `validate_node_local(data, kind, tree, path)` :
     valide intrinsequement un noeud / branche / regle isole.
     Tolerant aux squelettes (un noeud nouvellement cree peut n'avoir
     que son id + niveau + texte sans branches encore). Refuse seulement
     les erreurs irrecuperables (id mal forme, valeur d'enum invalide,
     date invalide, collision d'id dans l'arbre).

  2. `get_allowed_child_kinds(tree, parent_path)` :
     liste les types de noeud qu'on peut inserer comme enfant a un
     endroit donne. Applique l'ordre des niveaux formulaire et les
     contraintes de la grammaire.

  3. `validate_arbre()` (dans yaml_tree/validator.py) :
     validation profonde, deja ecrite par l'autre agent, lancee
     uniquement a l'activation d'un draft.

Module independant de Django : passe le `tree.contenu` (dict) en
argument, pas le DecisionTree lui-meme.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from envergo.nitrates.yaml_tree.expression import valider_expression

# ─── Constantes grammaire ──────────────────────────────────────────────────

NIVEAUX_FORMULAIRE_ORDRE = ["culture", "sous_culture", "type_fertilisant", "complement"]
"""Ordre strict des niveaux formulaire. Un descendant ne peut pas avoir
un niveau strictement anterieur a un de ses ancetres. Les 3 premiers ne
peuvent pas se repeter sur un chemin ; complement peut s'enchainer."""

REGLE_TYPES = [
    "interdiction",
    "autorisation_sous_condition",
    "plafonnement",
    "libre",
    "non_applicable",
    "calculatrice",
    "mixte",
]

CATALOGUE_SOURCES = ["sig", "mapping_referentiel", "calcul"]

# Valeur de `source` (UI uniquement) qui bascule un catalogue en mode
# "resolution par expression Python" (#128). N'est PAS stockee dans le YAML :
# elle determine que le builder produit un type_noeud catalogue_parametre.
SOURCE_EXPRESSION = "expression"

# Sources proposees dans le dropdown du formulaire catalogue (ordre = ordre
# d'affichage). `expression` en dernier (mode avance).
CATALOGUE_SOURCES_UI = CATALOGUE_SOURCES + [SOURCE_EXPRESSION]

ID_NOEUD_FORMULAIRE_RE = re.compile(r"^q_[a-zA-Z0-9_]+$")
ID_NOEUD_CATALOGUE_RE = re.compile(r"^n_[a-zA-Z0-9_]+$")
ID_REGLE_RE = re.compile(r"^r_[a-zA-Z0-9_]+$")
DATE_FIXE_RE = re.compile(r"^\d{2}/\d{2}$")


# ─── Resultat de validation ────────────────────────────────────────────────


@dataclass
class FieldError:
    """Une erreur localisee sur un champ. Sert au rendu form htmx."""

    field: str
    message: str


@dataclass
class ValidationResult:
    ok: bool
    errors: list[FieldError] = field(default_factory=list)

    @classmethod
    def success(cls) -> "ValidationResult":
        return cls(ok=True)

    @classmethod
    def fail(cls, errors: list[FieldError]) -> "ValidationResult":
        return cls(ok=False, errors=errors)


# ─── Validation locale ─────────────────────────────────────────────────────


def validate_node_local(
    data: dict,
    kind: str,
    arbre: dict | None = None,
    own_path: tuple[str, ...] | None = None,
) -> ValidationResult:
    """Valide un noeud / regle / branche isole, dans le contexte d'une
    edition.

    `kind` : "noeud_formulaire" | "noeud_catalogue" | "regle" | "branche" |
             "renvoi_vers".
    `arbre` (optionnel) : si fourni, on verifie l'unicite de l'id du
             noeud / regle dans l'arbre (en excluant own_path s'il est
             fourni : on ne se confond pas avec soi-meme lors d'un edit).
    `own_path` (optionnel) : chemin du noeud / regle qu'on est en train
             de modifier, pour exclure de la verification d'unicite.
    """
    errors: list[FieldError] = []
    if not isinstance(data, dict):
        return ValidationResult.fail([FieldError("", "Donnees invalides.")])

    if kind == "noeud_formulaire":
        errors.extend(_validate_noeud_formulaire(data))
    elif kind == "noeud_catalogue":
        errors.extend(_validate_noeud_catalogue(data))
    elif kind == "noeud_catalogue_parametre":
        errors.extend(_validate_noeud_catalogue_parametre(data))
    elif kind == "regle":
        errors.extend(_validate_regle(data))
    elif kind == "branche":
        errors.extend(_validate_branche(data))
    elif kind == "renvoi_vers":
        errors.extend(_validate_renvoi_vers(data, arbre))
    elif kind == "renvoi_arbre":
        errors.extend(_validate_renvoi_arbre(data))
    elif kind == "feuille_vide":
        errors.extend(_validate_feuille_vide(data))
    else:
        errors.append(FieldError("kind", f"Type inconnu : {kind!r}."))

    # Unicite de l'id dans l'arbre (sauf branche qui n'a pas d'id propre).
    if arbre is not None and kind in {
        "noeud_formulaire",
        "noeud_catalogue",
        "noeud_catalogue_parametre",
        "regle",
    }:
        new_id = data.get("id")
        if new_id and _id_already_used(arbre, new_id, exclude_path=own_path):
            errors.append(
                FieldError(
                    "id",
                    f"L'identifiant {new_id!r} est deja utilise dans l'arbre.",
                )
            )

    return ValidationResult.success() if not errors else ValidationResult.fail(errors)


def _validate_noeud_formulaire(data: dict) -> list[FieldError]:
    errors: list[FieldError] = []
    nid = data.get("id")
    if not nid:
        errors.append(FieldError("id", "L'identifiant est requis."))
    elif not ID_NOEUD_FORMULAIRE_RE.match(nid):
        errors.append(
            FieldError(
                "id",
                "Format invalide : l'identifiant d'un noeud formulaire doit "
                "commencer par 'q_' (ex: q_culture_principale).",
            )
        )
    niveau = data.get("niveau")
    if niveau and niveau not in NIVEAUX_FORMULAIRE_ORDRE:
        errors.append(
            FieldError(
                "niveau",
                f"Niveau {niveau!r} inconnu. "
                f"Attendu : {', '.join(NIVEAUX_FORMULAIRE_ORDRE)}.",
            )
        )
    if not niveau:
        errors.append(FieldError("niveau", "Le niveau est requis."))
    if not data.get("texte"):
        errors.append(FieldError("texte", "Le texte de la question est requis."))
    if not data.get("champ"):
        errors.append(FieldError("champ", "Le champ technique est requis."))
    return errors


def _validate_noeud_catalogue(data: dict) -> list[FieldError]:
    errors: list[FieldError] = []
    nid = data.get("id")
    if not nid:
        errors.append(FieldError("id", "L'identifiant est requis."))
    elif not ID_NOEUD_CATALOGUE_RE.match(nid):
        errors.append(
            FieldError(
                "id",
                "Format invalide : l'identifiant d'un noeud catalogue doit "
                "commencer par 'n_' (ex: n_zone_vulnerable).",
            )
        )
    if not data.get("champ"):
        errors.append(FieldError("champ", "Le champ technique est requis."))
    source = data.get("source")
    if not source:
        errors.append(FieldError("source", "La source est requise."))
    elif source not in CATALOGUE_SOURCES:
        errors.append(
            FieldError(
                "source",
                f"Source {source!r} inconnue. "
                f"Attendu : {', '.join(CATALOGUE_SOURCES)}.",
            )
        )
    return errors


def _validate_noeud_catalogue_parametre(data: dict) -> list[FieldError]:
    """Noeud catalogue_parametre (issue #128) : id n_*, champ requis, PAS de
    source (le branchement se fait par expression, pas par lecture SIG).

    On valide aussi les expressions des branches deja presentes (un noeud
    fraichement cree peut n'en avoir aucune -- tolere comme squelette)."""
    errors: list[FieldError] = []
    nid = data.get("id")
    if not nid:
        errors.append(FieldError("id", "L'identifiant est requis."))
    elif not ID_NOEUD_CATALOGUE_RE.match(nid):
        errors.append(
            FieldError(
                "id",
                "Format invalide : l'identifiant d'un noeud catalogue parametre "
                "doit commencer par 'n_' (ex: n_origine_effluent).",
            )
        )
    if not data.get("champ"):
        errors.append(FieldError("champ", "Le champ technique est requis."))
    for i, branche in enumerate(data.get("branches") or []):
        if not isinstance(branche, dict):
            continue
        expr = branche.get("expression")
        if expr is None:
            # Branche sans expression sous un catalogue_parametre : invalide
            # (le routage se fait par expression). Tolere uniquement si la
            # branche est un squelette totalement vide.
            if branche:
                errors.append(
                    FieldError(
                        f"branches[{i}].expression",
                        "Chaque branche d'un catalogue parametre doit porter "
                        "une expression.",
                    )
                )
            continue
        err = valider_expression(expr)
        if err:
            errors.append(FieldError(f"branches[{i}].expression", err))
    return errors


def _validate_regle(data: dict) -> list[FieldError]:
    errors: list[FieldError] = []
    rid = data.get("id")
    if not rid:
        errors.append(FieldError("id", "L'identifiant est requis."))
    elif not ID_REGLE_RE.match(rid):
        errors.append(
            FieldError(
                "id",
                "Format invalide : l'identifiant d'une regle doit "
                "commencer par 'r_' (ex: r_colza_type_0).",
            )
        )

    rtype = data.get("type")
    if not rtype and not data.get("a_completer"):
        errors.append(
            FieldError(
                "type",
                "Le type de regle est requis (sauf si marquee comme " "'a_completer').",
            )
        )
    elif rtype and rtype not in REGLE_TYPES:
        errors.append(
            FieldError(
                "type",
                f"Type {rtype!r} inconnu. " f"Attendu : {', '.join(REGLE_TYPES)}.",
            )
        )

    # Periodes : si presentes, dates valides
    for i, periode in enumerate(data.get("periodes") or []):
        if not isinstance(periode, dict):
            errors.append(FieldError(f"periodes[{i}]", "Format invalide."))
            continue
        for borne in ("du", "au"):
            val = periode.get(borne)
            if val is None:
                errors.append(FieldError(f"periodes[{i}].{borne}", "Date requise."))
            elif DATE_FIXE_RE.match(str(val)):
                if not _is_valid_date_jjmm(val):
                    errors.append(
                        FieldError(
                            f"periodes[{i}].{borne}",
                            f"Date {val!r} invalide (jour ou mois hors borne).",
                        )
                    )
            # Sinon : evenement phenologique, on ne verifie pas localement
            # qu'il existe (verifie en deep validate avec referentiels).
    return errors


def _validate_branche(data: dict) -> list[FieldError]:
    errors: list[FieldError] = []
    # Une branche porte soit `valeur` (catalogue/formulaire classique), soit
    # `expression` (branche d'un catalogue_parametre, #128). Si elle porte
    # une expression, on la valide ; la `valeur` devient alors optionnelle
    # (tracabilite).
    if "expression" in data:
        err = valider_expression(data.get("expression"))
        if err:
            errors.append(FieldError("expression", err))
    elif "valeur" not in data:
        errors.append(FieldError("valeur", "La valeur de branche est requise."))
    # On accepte les branches sans contenu (squelette draft).
    # Une branche peut avoir 0 ou 1 de {noeud, regle, renvoi_vers}.
    contents = sum(
        1 for k in ("noeud", "regle", "renvoi_vers") if data.get(k) is not None
    )
    if contents > 1:
        errors.append(
            FieldError(
                "",
                "Une branche ne peut contenir qu'un seul de "
                "{noeud, regle, renvoi_vers}.",
            )
        )
    return errors


def _validate_renvoi_vers(data: dict, arbre: dict | None) -> list[FieldError]:
    errors: list[FieldError] = []
    cible = data.get("renvoi_vers") if isinstance(data, dict) else None
    if not cible:
        errors.append(FieldError("renvoi_vers", "L'identifiant cible est requis."))
        return errors
    if arbre is not None:
        ids = _collect_ids(arbre)
        if cible not in ids:
            errors.append(
                FieldError(
                    "renvoi_vers",
                    f"L'identifiant {cible!r} n'existe pas dans l'arbre.",
                )
            )
    return errors


RENVOI_ARBRE_SCOPES = ("region", "national")


def _validate_renvoi_arbre(data: dict) -> list[FieldError]:
    cible = data.get("renvoi_arbre") if isinstance(data, dict) else None
    if not cible:
        return [FieldError("renvoi_arbre", "Le scope cible est requis.")]
    if cible not in RENVOI_ARBRE_SCOPES:
        return [
            FieldError(
                "renvoi_arbre",
                f"Scope invalide {cible!r} : attendu "
                f"{' ou '.join(RENVOI_ARBRE_SCOPES)}.",
            )
        ]
    return []


def _validate_feuille_vide(data: dict) -> list[FieldError]:
    # Marqueur booleen sans autre champ : on tolere {feuille_vide: True}.
    if not (isinstance(data, dict) and data.get("feuille_vide") is True):
        return [FieldError("feuille_vide", "feuille_vide doit valoir true.")]
    return []


def _is_valid_date_jjmm(s: str) -> bool:
    try:
        jour, mois = s.split("/")
        j, m = int(jour), int(mois)
        return 1 <= j <= 31 and 1 <= m <= 12
    except (ValueError, AttributeError):
        return False


# ─── Allowed children ──────────────────────────────────────────────────────


def get_allowed_child_kinds(arbre: dict, parent_path: tuple[str, ...]) -> list[str]:
    """Retourne les types de noeud autorises a inserer comme enfant d'une
    branche d'un noeud parent.

    `parent_path` : suite d'ids du noeud parent (le noeud dont on veut
    ajouter une branche, ou la branche dont on veut ajouter un contenu).
    Vide pour la racine.

    Retourne une liste de strings parmi :
      - "noeud_formulaire_culture"
      - "noeud_formulaire_sous_culture"
      - "noeud_formulaire_type_fertilisant"
      - "noeud_formulaire_complement"
      - "noeud_catalogue"
      - "regle"
      - "renvoi_vers"

    Les niveaux formulaire deja vus sur le chemin sont exclus (sauf
    `complement` qui peut se chainer 0..N fois). Une feuille est
    toujours une regle (ou un renvoi_vers une regle) -- pas de valeur
    sans contenu.
    """
    parent_node = _get_node_at(arbre, parent_path)
    niveaux_vus = _niveaux_formulaire_sur_chemin(arbre, parent_path)

    allowed: list[str] = []

    # `complement` est transparent : il peut apparaitre n'importe ou
    # entre les autres niveaux, et ne contraint pas l'ordre. On l'ignore
    # pour le calcul du plus haut niveau deja vu.
    niveaux_significatifs = [n for n in niveaux_vus if n != "complement"]
    if niveaux_significatifs:
        max_idx = max(NIVEAUX_FORMULAIRE_ORDRE.index(n) for n in niveaux_significatifs)
    else:
        max_idx = -1
    for i, niveau in enumerate(NIVEAUX_FORMULAIRE_ORDRE):
        if niveau == "complement":
            allowed.append(f"noeud_formulaire_{niveau}")
            continue
        if i < max_idx:
            continue  # ordre violerait
        if niveau in niveaux_significatifs:
            continue  # doublon interdit pour les 3 niveaux principaux
        allowed.append(f"noeud_formulaire_{niveau}")

    # Catalogue (le mode de resolution -- sig / referentiel / calcul /
    # expression -- est choisi DANS le formulaire catalogue, pas comme un
    # kind separe), regle, renvoi_vers : toujours autorises.
    allowed.append("noeud_catalogue")
    allowed.append("regle")
    allowed.append("renvoi_vers")
    # Renvoi explicite vers un autre arbre + feuille vide : utiles pour les
    # PAR/ZAR (overrides partiels). Proposes toujours ; la validation deep
    # (a l'activation) refuse une feuille_vide dans un PAN national.
    allowed.append("renvoi_arbre")
    allowed.append("feuille_vide")

    # Garde-fou : si parent_node est None (chemin invalide), on ne fait
    # confiance a rien.
    if parent_node is None and parent_path:
        return []
    return allowed


# ─── Walk helpers ──────────────────────────────────────────────────────────


def _get_node_at(arbre: dict, path: tuple[str, ...]) -> dict | None:
    """Retrouve un noeud par son chemin (suite d'ids). Si chemin vide,
    retourne la racine. Renvoie None si le chemin n'existe pas."""
    racine = (arbre or {}).get("arbre", {}).get("noeud")
    if not racine:
        return None
    if not path:
        return racine
    if racine.get("id") != path[0]:
        return None
    current = racine
    for nid in path[1:]:
        found = None
        for branche in current.get("branches") or []:
            if isinstance(branche, dict) and isinstance(branche.get("noeud"), dict):
                if branche["noeud"].get("id") == nid:
                    found = branche["noeud"]
                    break
        if found is None:
            return None
        current = found
    return current


def _niveaux_formulaire_sur_chemin(arbre: dict, path: tuple[str, ...]) -> list[str]:
    """Niveaux formulaire des noeuds traverses sur ce chemin."""
    racine = (arbre or {}).get("arbre", {}).get("noeud")
    if not racine or not path:
        return []
    niveaux: list[str] = []
    if racine.get("type_noeud") == "formulaire" and racine.get("niveau"):
        niveaux.append(racine["niveau"])
    if racine.get("id") != path[0]:
        return niveaux
    current = racine
    for nid in path[1:]:
        found = None
        for branche in current.get("branches") or []:
            if isinstance(branche, dict) and isinstance(branche.get("noeud"), dict):
                if branche["noeud"].get("id") == nid:
                    found = branche["noeud"]
                    break
        if found is None:
            return niveaux
        if found.get("type_noeud") == "formulaire" and found.get("niveau"):
            niveaux.append(found["niveau"])
        current = found
    return niveaux


def collect_champs_by_niveau(arbre: dict) -> dict[str, list[str]]:
    """Retourne {niveau: [champs uniques deja utilises dans l'arbre]}.

    Sert de datalist pour l'edition d'un noeud formulaire : le juriste
    peut reutiliser un `champ` deja employe ailleurs (au lieu d'inventer
    un slug random qui casserait le parser de la moulinette).

    Le champ est plus parlant pour `complement` (questions annexes
    sans nom canonique : `plan_epandage`, `fertilisant_iaa`, etc.).
    """
    result: dict[str, set[str]] = {n: set() for n in NIVEAUX_FORMULAIRE_ORDRE}
    racine = (arbre or {}).get("arbre", {}).get("noeud")
    if racine:
        _walk_collect_champs(racine, result)
    # Tri stable
    return {k: sorted(v) for k, v in result.items()}


def _walk_collect_champs(noeud: dict, out: dict[str, set]) -> None:
    if not isinstance(noeud, dict):
        return
    if noeud.get("type_noeud") == "formulaire":
        niveau = noeud.get("niveau")
        champ = noeud.get("champ")
        if niveau in out and champ:
            out[niveau].add(champ)
    for branche in noeud.get("branches") or []:
        if isinstance(branche, dict) and isinstance(branche.get("noeud"), dict):
            _walk_collect_champs(branche["noeud"], out)


def _collect_ids(arbre: dict) -> set[str]:
    """Tous les ids de noeuds et regles dans l'arbre."""
    ids: set[str] = set()
    racine = (arbre or {}).get("arbre", {}).get("noeud")
    if racine:
        _collect_ids_in_node(racine, ids)
    # Regles top-level reutilisables : `plafonnements` (legacy) et
    # `regles_partagees` (couvert d'interculture, etc.).
    for top_key in ("plafonnements", "regles_partagees"):
        for entry in (arbre or {}).get(top_key) or []:
            regle = entry.get("regle") if isinstance(entry, dict) else None
            if isinstance(regle, dict) and regle.get("id"):
                ids.add(regle["id"])
    return ids


def _collect_ids_in_node(noeud: dict, ids: set[str]) -> None:
    if not isinstance(noeud, dict):
        return
    nid = noeud.get("id")
    if nid:
        ids.add(nid)
    for branche in noeud.get("branches") or []:
        if not isinstance(branche, dict):
            continue
        if isinstance(branche.get("noeud"), dict):
            _collect_ids_in_node(branche["noeud"], ids)
        elif isinstance(branche.get("regle"), dict):
            rid = branche["regle"].get("id")
            if rid:
                ids.add(rid)


def _id_already_used(
    arbre: dict, target_id: str, exclude_path: tuple[str, ...] | None
) -> bool:
    """True si target_id existe deja dans l'arbre, modulo un chemin a
    exclure (utile pour l'edit : on ne se confond pas avec soi-meme)."""
    if exclude_path is None:
        return target_id in _collect_ids(arbre)
    excluded_id = exclude_path[-1] if exclude_path else None
    other_ids = _collect_ids(arbre) - ({excluded_id} if excluded_id else set())
    return target_id in other_ids
