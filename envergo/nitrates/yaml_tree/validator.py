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


def validate_arbre(
    arbre: dict,
    referentiels: dict | None = None,
    references_sig_supportees: set[str] | None = None,
) -> None:
    """Lance toute la chaine de validation. Leve ValidationError si KO.

    referentiels (optionnel) : si fourni, on verifie aussi que les
    code_prescription / note / evenements_phenologiques referencees existent.

    references_sig_supportees (optionnel) : set des references SIG que le
    backend sait resoudre (cf. catalogue_refs.CATALOGUE_RESOLVERS).
    Si fourni, on signale les noeuds catalogue source=sig dont la
    reference n'est pas couverte par le backend (= dataset SIG manquant).
    Pas une erreur bloquante en MVP -- l'arbre brouillon evolue plus vite
    que les datasets -- mais on les liste pour traque.
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
    errors.extend(_check_regimes_coherents(arbre))
    errors.extend(_check_regime_mixte(arbre))
    errors.extend(_check_branches_booleennes_exhaustives(arbre))

    if referentiels:
        errors.extend(_check_references_referentiels(arbre, referentiels))

    if references_sig_supportees is not None:
        errors.extend(
            _check_references_sig_supportees(arbre, references_sig_supportees)
        )

    if errors:
        raise ValidationError(errors)


def collect_references_sig(arbre: dict) -> list[tuple[str, str]]:
    """Liste les references SIG (source=sig) utilisees par l'arbre,
    avec leur noeud_id pour pouvoir les localiser. Utile pour savoir
    quels datasets il faut importer."""
    refs: list[tuple[str, str]] = []
    for obj in _walk_objects(arbre):
        if not isinstance(obj, dict):
            continue
        if obj.get("type_noeud") != "catalogue":
            continue
        if obj.get("source") != "sig":
            continue
        ref = obj.get("reference")
        if ref:
            refs.append((obj.get("id", "?"), ref))
    return refs


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
    """Generator qui yield tous les noeuds, branches et regles d'un arbre.

    Inclut les regles definies au top-level dans les sections
    `plafonnements` et `regles_partagees` -- toutes deux sont des
    listes de `{regle: ...}` reutilisables (cibles de renvoi_vers).
    """
    racine = arbre.get("arbre", {}).get("noeud")
    if racine:
        yield from _walk_node(racine)
    for section in ("plafonnements", "regles_partagees"):
        for entry in arbre.get(section, []) or []:
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


# ─── Coherence type / regime par periode ────────────────────────────────────


def _check_regimes_coherents(arbre: dict) -> list[str]:
    """Refuse les combinaisons type / regime intra-regle absurdes.

    Convention grammaire 2026-05-08 : `type` est le regime principal
    autorise par la regle. Les sous-periodes peuvent UNIQUEMENT raffiner
    vers PLUS RESTRICTIF. Une regle `type=interdiction` ne peut donc
    pas avoir de periode `regime=autorisation_sous_condition` (ce serait
    plus permissif que le type parent).

    Ordre de severite (plus restrictif en haut) :
        interdiction > plafonnement > autorisation_sous_condition > libre

    Permissions :
      type=libre               : aucun raffinement utile (regle libre = pas
                                 de periode contrainte normalement). Si on
                                 met un regime, ce serait incoherent. Refus.
      type=autorisation_sous_condition : peut raffiner vers `interdiction`,
                                 `plafonnement`, ou `autorisation_sous_condition`
                                 (idempotent). Refuse `libre` (plus permissif).
      type=plafonnement        : peut raffiner vers `interdiction`. Refuse
                                 `autorisation_sous_condition` et `libre`.
      type=interdiction        : ne peut PAS etre raffine vers plus permissif.
                                 Tolere `regime=interdiction` (idempotent).
                                 Refuse autorisation_sous_condition / plafonnement
                                 / libre.

    Le `non_applicable` / `calculatrice` / `a_completer` n'ont pas de
    periodes typiquement, on ne valide rien (laisse passer si pas de regime).
    """
    errors: list[str] = []
    # Plus le rang est BAS, plus le regime est RESTRICTIF.
    severite = {
        "interdiction": 0,
        "plafonnement": 1,
        "autorisation_sous_condition": 2,
        "libre": 3,
    }
    for obj in _walk_objects(arbre):
        rtype = obj.get("type")
        if rtype not in severite:
            continue
        rang_type = severite[rtype]
        for i, periode in enumerate(obj.get("periodes", []) or [], start=1):
            preg = periode.get("regime")
            if preg is None:
                continue
            if preg not in severite:
                errors.append(
                    f"[regime] regle '{obj.get('id')}' periode #{i} : "
                    f"regime={preg!r} inconnu (attendu : "
                    f"interdiction / plafonnement / autorisation_sous_condition / libre)"
                )
                continue
            if severite[preg] > rang_type:
                errors.append(
                    f"[regime] regle '{obj.get('id')}' periode #{i} : "
                    f"regime={preg!r} est plus permissif que le type "
                    f"parent {rtype!r}. Une periode ne peut raffiner que "
                    f"vers PLUS RESTRICTIF (convention grammaire 2026-05-08). "
                    f"Si l'intention est d'avoir un regime mixte, declarer "
                    f"type='mixte' au niveau regle."
                )
    return errors


# ─── Type "mixte" : exige >=2 regimes distincts dans les periodes ──────────


def _check_regime_mixte(arbre: dict) -> list[str]:
    """Pour `type=mixte`, chaque periode doit declarer son `regime` et il
    faut au moins 2 regimes distincts (sinon `mixte` n'a pas de sens : la
    regle devrait declarer le type unique de ses periodes).

    Convention 2026-05-11 : `mixte` exprime explicitement la coexistence
    de plusieurs regimes dans une meme regle (ex. autorisation_sous_condition
    sur une fenetre + interdiction sur une autre). Plus carre que de declarer
    `type=autorisation_sous_condition` + periode `regime=interdiction` (qui
    laissait penser que toute la regle etait permissive).
    """
    errors: list[str] = []
    regimes_valides = {
        "interdiction",
        "plafonnement",
        "autorisation_sous_condition",
        "libre",
    }
    for obj in _walk_objects(arbre):
        if obj.get("type") != "mixte":
            continue
        rid = obj.get("id")
        periodes = obj.get("periodes") or []
        if len(periodes) < 2:
            errors.append(
                f"[mixte] regle '{rid}' : type='mixte' exige au moins 2 periodes "
                f"(avec regimes distincts). Trouve : {len(periodes)}."
            )
            continue
        regimes_vus: set[str] = set()
        for i, periode in enumerate(periodes, start=1):
            preg = periode.get("regime")
            if not preg:
                errors.append(
                    f"[mixte] regle '{rid}' periode #{i} : `regime` obligatoire "
                    f"sur chaque periode quand type='mixte' (pas d'heritage)."
                )
                continue
            if preg not in regimes_valides:
                errors.append(
                    f"[mixte] regle '{rid}' periode #{i} : regime={preg!r} "
                    f"invalide (attendu : {sorted(regimes_valides)})."
                )
                continue
            regimes_vus.add(preg)
        if len(regimes_vus) < 2:
            errors.append(
                f"[mixte] regle '{rid}' : type='mixte' exige >=2 regimes "
                f"distincts dans les periodes. Trouve : {sorted(regimes_vus)}."
            )
    return errors


# ─── Ordre des niveaux formulaire ───────────────────────────────────────────


def _check_niveaux_formulaire(arbre: dict) -> list[str]:
    """Sur tout chemin racine -> feuille, les noeuds formulaire respectent
    l'ordre culture -> sous_culture -> type_fertilisant -> complement.

    Sauts autorises (on peut passer directement de culture a complement),
    retour interdit (on ne peut pas voir un sous_culture apres un complement).

    Doublon de niveau : tolere si les noeuds portent des `champ` differents
    (cas legitime : interculture pose 2 questions de niveau "sous_culture",
    une sur la duree (`sous_culture`) et une sur le type de couvert
    (`sous_culture_couvert`)). Doublon strict (meme niveau ET meme champ)
    interdit.
    """
    errors = []
    racine = arbre.get("arbre", {}).get("noeud")
    if racine:
        _walk_paths(racine, [], errors)
    return errors


def _walk_paths(noeud: dict, chemin: list[tuple[str, str]], errors: list[str]) -> None:
    """`chemin` : liste de (niveau, champ) des noeuds formulaire deja
    rencontres dans la branche."""
    nouveau_chemin = list(chemin)
    if noeud.get("type_noeud") == "formulaire":
        niveau = noeud.get("niveau")
        champ = noeud.get("champ", "")
        if niveau:
            err = _check_niveau_ajout(nouveau_chemin, niveau, champ, noeud.get("id"))
            if err:
                errors.append(err)
            nouveau_chemin.append((niveau, champ))

    for branche in noeud.get("branches", []):
        if "noeud" in branche:
            _walk_paths(branche["noeud"], nouveau_chemin, errors)


def _check_niveau_ajout(
    chemin: list[tuple[str, str]], niveau: str, champ: str, noeud_id: str
) -> str | None:
    if niveau not in NIVEAUX_FORMULAIRE_ORDRE:
        return None  # le schema l'aurait deja attrape
    idx_nouveau = NIVEAUX_FORMULAIRE_ORDRE.index(niveau)
    # Convention 2026-05-12 : `complement` est le dernier niveau autorise.
    # Une fois entre dans une chaine de complements, on ne peut PAS revenir
    # vers culture / sous_culture / type_fertilisant. Donc des qu'un
    # complement apparait dans le chemin, tout niveau suivant doit etre
    # complement aussi.
    if any(n == "complement" for n, _ in chemin) and niveau != "complement":
        return (
            f"[niveau] noeud '{noeud_id}' : niveau {niveau!r} apres "
            f"'complement' dans le chemin (retour en arriere interdit)"
        )
    for prec_niveau, prec_champ in chemin:
        idx_prec = NIVEAUX_FORMULAIRE_ORDRE.index(prec_niveau)
        if idx_nouveau < idx_prec:
            return (
                f"[niveau] noeud '{noeud_id}' : niveau {niveau!r} apres "
                f"{prec_niveau!r} dans le chemin (retour en arriere interdit)"
            )
        if idx_nouveau == idx_prec and niveau != "complement" and champ == prec_champ:
            return (
                f"[niveau] noeud '{noeud_id}' : niveau {niveau!r} et champ "
                f"{champ!r} en doublon sur le chemin (deja vus avec champ "
                f"{prec_champ!r})"
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


# ─── References SIG resolvables par le backend ──────────────────────────────


def _check_references_sig_supportees(
    arbre: dict, references_supportees: set[str]
) -> list[str]:
    """Signale les noeuds catalogue source=sig dont la reference n'est pas
    dans le set passe en parametre (= dataset/mapping non implementes
    cote backend). Permet de detecter au plus tot les trous d'integration
    plutot que de tomber sur une erreur runtime au milieu d'un parcours."""
    errors = []
    for obj in _walk_objects(arbre):
        if not isinstance(obj, dict):
            continue
        if obj.get("type_noeud") != "catalogue":
            continue
        if obj.get("source") != "sig":
            continue
        ref = obj.get("reference")
        if ref and ref not in references_supportees:
            errors.append(
                f"[sig] noeud '{obj.get('id')}' (champ='{obj.get('champ')}') : "
                f"reference SIG '{ref}' non supportee par le backend (dataset "
                f"manquant ou resolveur a ajouter dans catalogue_refs.CATALOGUE_RESOLVERS)"
            )
    return errors


# ─── Exhaustivite des branches booleennes ──────────────────────────────────


def _check_branches_booleennes_exhaustives(arbre: dict) -> list[str]:
    """Pour un noeud dont au moins une branche a `valeur: true` ou `valeur: false`,
    on attend que les deux valeurs booleennes soient couvertes.

    Cas typique : noeud catalogue source=sig avec champ booleen
    (`en_zone_vulnerable`, `parcelle_communique`, etc.) ou noeud formulaire
    niveau=complement (question oui/non). Supprimer la feuille `true` ou
    `false` laisse un sous-arbre incomplet -- l'utilisateur dont le champ
    prend l'autre valeur n'a pas de chemin.

    On ne contraint pas les noeuds dont les branches sont des slugs
    (type_0, colza, ...) : leur domaine n'est pas connu a coup sur depuis
    l'arbre seul.
    """
    errors = []
    racine = arbre.get("arbre", {}).get("noeud")
    if not isinstance(racine, dict):
        return errors
    for noeud in _walk_node(racine):
        if not isinstance(noeud, dict):
            continue
        if "branches" not in noeud:
            continue
        branches = noeud.get("branches") or []
        valeurs = {b.get("valeur") for b in branches if isinstance(b, dict)}
        has_bool = True in valeurs or False in valeurs
        if not has_bool:
            continue
        manquantes = {True, False} - valeurs
        if manquantes:
            mqt = ", ".join(repr(v) for v in sorted(manquantes, key=str))
            errors.append(
                f"[exhaustivite] noeud '{noeud.get('id')}' "
                f"(champ='{noeud.get('champ')}') : branche(s) booleenne(s) "
                f"manquante(s) : {mqt}. Toutes les valeurs booleennes du "
                f"champ doivent etre couvertes."
            )
    return errors


# ─── Utilitaires ────────────────────────────────────────────────────────────


def _short_repr(obj: dict) -> str:
    return obj.get("id") or obj.get("valeur") or "(?)"
