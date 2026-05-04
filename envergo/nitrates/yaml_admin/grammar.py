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
]

CATALOGUE_SOURCES = ["sig", "mapping_referentiel", "calcul"]

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
    elif kind == "regle":
        errors.extend(_validate_regle(data))
    elif kind == "branche":
        errors.extend(_validate_branche(data))
    elif kind == "renvoi_vers":
        errors.extend(_validate_renvoi_vers(data, arbre))
    else:
        errors.append(FieldError("kind", f"Type inconnu : {kind!r}."))

    # Unicite de l'id dans l'arbre (sauf branche qui n'a pas d'id propre).
    if arbre is not None and kind in {"noeud_formulaire", "noeud_catalogue", "regle"}:
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
    if "valeur" not in data:
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
      - "valeur_seule" (branche feuille sans contenu, ex: 0/1/2/3 sous une question)
      - "noeud_formulaire_culture"
      - "noeud_formulaire_sous_culture"
      - "noeud_formulaire_type_fertilisant"
      - "noeud_formulaire_complement"
      - "noeud_catalogue"
      - "regle"
      - "renvoi_vers"

    Les niveaux formulaire deja vus sur le chemin sont exclus (sauf
    `complement` qui peut se chainer 0..N fois).
    """
    parent_node = _get_node_at(arbre, parent_path)
    niveaux_vus = _niveaux_formulaire_sur_chemin(arbre, parent_path)

    allowed: list[str] = []

    # Valeur seule : utile pour les questions a choix multiples sans
    # noeud enfant (ex: type_fertilisant 0/1/2/3 -- chaque branche est
    # juste une valeur sans contenu).
    allowed.append("valeur_seule")

    # Niveaux formulaire : on autorise tout niveau >= au plus haut deja vu,
    # et si pas encore vu (sauf complement qui peut se repeter).
    if niveaux_vus:
        max_idx = max(NIVEAUX_FORMULAIRE_ORDRE.index(n) for n in niveaux_vus)
    else:
        max_idx = -1
    for i, niveau in enumerate(NIVEAUX_FORMULAIRE_ORDRE):
        if i < max_idx:
            continue  # ordre violerait
        if niveau != "complement" and niveau in niveaux_vus:
            continue  # doublon interdit pour les 3 premiers
        allowed.append(f"noeud_formulaire_{niveau}")

    # Catalogue, regle, renvoi_vers : toujours autorises.
    allowed.append("noeud_catalogue")
    allowed.append("regle")
    allowed.append("renvoi_vers")

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


def _collect_ids(arbre: dict) -> set[str]:
    """Tous les ids de noeuds et regles dans l'arbre."""
    ids: set[str] = set()
    racine = (arbre or {}).get("arbre", {}).get("noeud")
    if racine:
        _collect_ids_in_node(racine, ids)
    for entry in arbre.get("plafonnements") or []:
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
