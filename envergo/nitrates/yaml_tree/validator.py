"""Validation d'un arbre de decision YAML.

2 niveaux :
  1. Structure (JSON Schema) : fait par jsonschema.Draft202012Validator
  2. Semantique : id unique, renvoi_vers existant, code_prescription / note
     existent dans referentiels, dates JJ/MM valides ou evenements phenologiques
     connus, ordre des niveaux formulaire (culture -> sous_culture ->
     type_fertilisant -> complement, sans retour, sans doublon des 3 premiers).

Tout est rassemble dans `validate_arbre(arbre, referentiels=None)` qui leve
ValidationError avec une liste d'erreurs.
"""

from __future__ import annotations

import re
from typing import Iterable

from jsonschema import Draft202012Validator

from envergo.nitrates.yaml_tree.schema import ARBRE_SCHEMA

DATE_FIXE_RE = re.compile(r"^\d{2}/\d{2}$")
NIVEAUX_FORMULAIRE_ORDRE = ["culture", "sous_culture", "type_fertilisant", "complement"]


class ValidationError(Exception):
    """Levee quand un arbre ne passe pas la validation. `errors` liste tous
    les problemes trouves (on ne s'arrete pas au premier)."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"{len(errors)} erreur(s) de validation : {errors[:3]}...")


def validate_arbre(arbre: dict, referentiels: dict | None = None) -> None:
    """Lance toute la chaine de validation. Leve ValidationError si KO.

    referentiels (optionnel) : si fourni, on verifie aussi que les
    code_prescription / note / evenements_phenologiques referencees existent.
    """
    errors: list[str] = []

    errors.extend(_validate_structure(arbre))
    if errors:
        # Inutile de continuer si la structure est cassee, les checks
        # semantiques peuvent crasher sur des champs manquants.
        raise ValidationError(errors)

    ids_definis = _collect_ids(arbre)
    errors.extend(_check_ids_uniques(ids_definis))
    errors.extend(_check_renvois_vers(arbre, ids_definis))
    errors.extend(_check_dates(arbre, referentiels))
    errors.extend(_check_niveaux_formulaire(arbre))

    if referentiels:
        errors.extend(_check_references_referentiels(arbre, referentiels))

    if errors:
        raise ValidationError(errors)


# ─── Structure ──────────────────────────────────────────────────────────────


def _validate_structure(arbre: dict) -> list[str]:
    validator = Draft202012Validator(ARBRE_SCHEMA)
    errors = []
    for err in sorted(validator.iter_errors(arbre), key=lambda e: e.path):
        path = "/".join(str(p) for p in err.absolute_path) or "(racine)"
        errors.append(f"[structure] {path} : {err.message}")
    return errors


# ─── Ids ────────────────────────────────────────────────────────────────────


def _walk_objects(arbre: dict) -> Iterable[dict]:
    """Generator qui yield tous les noeuds, branches et regles d'un arbre."""
    racine = arbre.get("arbre", {}).get("noeud")
    if racine:
        yield from _walk_node(racine)
    for entry in arbre.get("plafonnements", []) or []:
        regle = entry.get("regle")
        if regle:
            yield regle


def _walk_node(noeud: dict) -> Iterable[dict]:
    yield noeud
    for branche in noeud.get("branches", []):
        yield branche
        if "noeud" in branche:
            yield from _walk_node(branche["noeud"])
        elif "regle" in branche:
            yield branche["regle"]


def _collect_ids(arbre: dict) -> dict[str, list[str]]:
    """Retourne {id: [chemin1, chemin2, ...]} ; un id duplique aura plusieurs
    chemins, ce qui sert a generer des messages d'erreur lisibles."""
    ids: dict[str, list[str]] = {}
    for obj in _walk_objects(arbre):
        oid = obj.get("id") if isinstance(obj, dict) else None
        if oid:
            ids.setdefault(oid, []).append(_short_repr(obj))
    return ids


def _check_ids_uniques(ids: dict[str, list[str]]) -> list[str]:
    return [
        f"[ids] id '{oid}' duplique : {len(paths)} occurrences"
        for oid, paths in ids.items()
        if len(paths) > 1
    ]


def _check_renvois_vers(arbre: dict, ids: dict[str, list[str]]) -> list[str]:
    errors = []
    for branche in _walk_branches(arbre):
        cible = branche.get("renvoi_vers")
        if cible and cible not in ids:
            errors.append(
                f"[renvoi_vers] '{cible}' (depuis branche valeur="
                f"{branche.get('valeur')!r}) ne pointe vers aucun id existant"
            )
    return errors


def _walk_branches(arbre: dict) -> Iterable[dict]:
    racine = arbre.get("arbre", {}).get("noeud")
    if racine:
        yield from _walk_node_branches(racine)


def _walk_node_branches(noeud: dict) -> Iterable[dict]:
    for branche in noeud.get("branches", []):
        yield branche
        if "noeud" in branche:
            yield from _walk_node_branches(branche["noeud"])


# ─── Dates et evenements ────────────────────────────────────────────────────


def _check_dates(arbre: dict, referentiels: dict | None) -> list[str]:
    """Une date est soit "JJ/MM" valide, soit un evenement phenologique
    declare dans referentiels.yaml (si referentiels fourni)."""
    errors = []
    evenements = set()
    if referentiels:
        evenements = set(referentiels.get("evenements_phenologiques", {}).keys())

    for obj in _walk_objects(arbre):
        for periode in obj.get("periodes", []) or []:
            for borne in ("du", "au"):
                val = periode.get(borne)
                if val is None:
                    continue
                if DATE_FIXE_RE.match(val):
                    if not _is_valid_date(val):
                        errors.append(
                            f"[date] regle '{obj.get('id')}' : "
                            f"date {borne}={val!r} invalide (mois ou jour hors borne)"
                        )
                elif evenements and val not in evenements:
                    errors.append(
                        f"[evenement] regle '{obj.get('id')}' : "
                        f"{borne}={val!r} n'est ni une date JJ/MM ni un "
                        f"evenement phenologique connu"
                    )
    return errors


def _is_valid_date(s: str) -> bool:
    try:
        jour, mois = s.split("/")
        j, m = int(jour), int(mois)
        return 1 <= j <= 31 and 1 <= m <= 12
    except (ValueError, AttributeError):
        return False


# ─── Ordre des niveaux formulaire ───────────────────────────────────────────


def _check_niveaux_formulaire(arbre: dict) -> list[str]:
    """Sur tout chemin racine -> feuille, les noeuds formulaire respectent
    l'ordre culture -> sous_culture -> type_fertilisant -> complement.

    Sauts autorises (on peut passer directement de culture a complement),
    retour interdit (on ne peut pas voir un sous_culture apres un complement),
    doublon interdit pour les 3 premiers niveaux.
    """
    errors = []
    racine = arbre.get("arbre", {}).get("noeud")
    if racine:
        _walk_paths(racine, [], errors)
    return errors


def _walk_paths(noeud: dict, path_niveaux: list[str], errors: list[str]) -> None:
    nouveau_chemin = list(path_niveaux)
    if noeud.get("type_noeud") == "formulaire":
        niveau = noeud.get("niveau")
        if niveau:
            err = _check_niveau_ajout(nouveau_chemin, niveau, noeud.get("id"))
            if err:
                errors.append(err)
            nouveau_chemin.append(niveau)

    for branche in noeud.get("branches", []):
        if "noeud" in branche:
            _walk_paths(branche["noeud"], nouveau_chemin, errors)


def _check_niveau_ajout(chemin: list[str], niveau: str, noeud_id: str) -> str | None:
    if niveau not in NIVEAUX_FORMULAIRE_ORDRE:
        return None  # le schema l'aurait deja attrape
    idx_nouveau = NIVEAUX_FORMULAIRE_ORDRE.index(niveau)
    for prec in chemin:
        idx_prec = NIVEAUX_FORMULAIRE_ORDRE.index(prec)
        if idx_nouveau < idx_prec:
            return (
                f"[niveau] noeud '{noeud_id}' : niveau {niveau!r} apres "
                f"{prec!r} dans le chemin (retour en arriere interdit)"
            )
        if idx_nouveau == idx_prec and niveau != "complement" and prec != "complement":
            return (
                f"[niveau] noeud '{noeud_id}' : niveau {niveau!r} en doublon "
                f"sur le chemin (les 3 premiers niveaux ne se repetent pas)"
            )
    return None


# ─── References referentiels ────────────────────────────────────────────────


def _check_references_referentiels(arbre: dict, referentiels: dict) -> list[str]:
    errors = []
    codes_pc = set(referentiels.get("codes_prescription", {}).keys())
    notes = set(referentiels.get("notes", {}).keys())

    for obj in _walk_objects(arbre):
        if not isinstance(obj, dict):
            continue
        cp = obj.get("code_prescription")
        if cp and cp not in codes_pc:
            errors.append(
                f"[reference] regle '{obj.get('id')}' : code_prescription "
                f"'{cp}' inconnu dans referentiels.yaml"
            )
        note = obj.get("note")
        if note and note not in notes:
            errors.append(
                f"[reference] regle '{obj.get('id')}' : note '{note}' "
                f"inconnue dans referentiels.yaml"
            )
    return errors


# ─── Utilitaires ────────────────────────────────────────────────────────────


def _short_repr(obj: dict) -> str:
    return obj.get("id") or obj.get("valeur") or "(?)"
