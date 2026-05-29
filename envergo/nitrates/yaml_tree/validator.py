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

from envergo.nitrates.yaml_tree.condition import validate_condition
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

    referentiels (optionnel) : ensemble d'ids attendu par les checks
    semantiques (codes_prescription, notes, evenements_phenologiques).
    Si non fourni, on les lit DIRECTEMENT depuis l'ORM (CodePrescription,
    NoteReglementaire, EvenementPhenologique) -- pas via le rewrap dict
    de `load_referentiels()`. Garantit que l'admin qui ajoute une nouvelle
    note via l'admin Django la voit immediatement reconnue par le validator
    (carte #61).

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

    if referentiels is None:
        referentiels = _referentiels_depuis_orm()

    ids_definis = _collect_ids(arbre)
    errors.extend(_check_ids_uniques(ids_definis))
    errors.extend(_check_renvois_vers(arbre, ids_definis))
    errors.extend(_check_dates(arbre, referentiels))
    errors.extend(_check_niveaux_formulaire(arbre))
    errors.extend(_check_regimes_coherents(arbre))
    errors.extend(_check_regime_mixte(arbre))
    errors.extend(_check_calculatrice(arbre))
    errors.extend(_check_branches_booleennes_exhaustives(arbre))

    if referentiels:
        errors.extend(_check_references_referentiels(arbre, referentiels))

    if references_sig_supportees is not None:
        errors.extend(
            _check_references_sig_supportees(arbre, references_sig_supportees)
        )

    if errors:
        raise ValidationError(errors)


def _referentiels_depuis_orm() -> dict:
    """Construit le dict minimal attendu par les checks semantiques
    en lisant directement les modeles ORM. Beaucoup plus leger que
    `load_referentiels()` qui materialise tout le YAML : ici on n'a
    besoin que des sets d'identifiants pour valider les references.

    Renvoie {} si l'ORM n'est pas dispo (cas import_decision_tree
    appele hors contexte Django, ou tests qui mockent). Le validator
    saute alors silencieusement les checks de reference, ce qui est le
    comportement historique avant la migration #61.
    """
    try:
        from envergo.nitrates.models import (
            CodePrescription,
            EvenementPhenologique,
            NoteReglementaire,
        )
    except ImportError:
        return {}

    try:
        codes = dict.fromkeys(
            CodePrescription.objects.values_list("identifiant", flat=True), {}
        )
        notes = dict.fromkeys(
            NoteReglementaire.objects.values_list("identifiant", flat=True), {}
        )
        evenements = dict.fromkeys(
            EvenementPhenologique.objects.values_list("identifiant", flat=True), {}
        )
    except Exception:
        # DB indispo (tests sans django_db, ou ORM non initialise) :
        # on retombe sur les checks structurels seulement.
        return {}

    return {
        "codes_prescription": codes,
        "notes": notes,
        "evenements_phenologiques": evenements,
    }


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
    declare dans referentiels.yaml (si referentiels fourni).

    Cas particulier : les feuilles `type=calculatrice` ont leur propre
    grammaire de bornes (event nu, event+offset, cf. spec_grammaire_calculatrice),
    validee par `_check_calculatrice`. On les skip ici pour eviter les faux
    positifs (`date_semis_couvert+4semaines` n'est pas un evenement
    phenologique mais c'est une borne calculatrice legitime).
    """
    errors = []
    evenements = set()
    if referentiels:
        evenements = set(referentiels.get("evenements_phenologiques", {}).keys())

    for obj in _walk_objects(arbre):
        if obj.get("type") == "calculatrice":
            continue  # delegue a _check_calculatrice
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


# ─── Type "calculatrice" : inputs_requis + bornes event +/- offset ─────────


# Borne calculatrice :
#   date_fixe       : "JJ/MM"
#   event nu        : "<event_id>"
#   event + offset  : "<event_id>(+|-)<n>(jours|semaines|mois)"
_CALCULATRICE_REGIMES = {
    "interdiction",
    "autorisation_sous_condition",
    "plafonnement",
    "libre",
    "non_applicable",
}
_CALCULATRICE_COMPOSANTS = {
    "calendrier_dynamique_couvert",
    # Composants legacy de l'arbre PAN actuel (a migrer plus tard vers
    # le nouveau composant calendrier_dynamique_couvert).
    "luzerne_post_coupe",
    "fenetre_epandage",
}

# Composants legacy : on saute la nouvelle validation grammaire calculatrice
# pour eux (ils suivent l'ancienne shape : inputs_requis = [str], pas de
# periodes). A migrer vers calendrier_dynamique_couvert plus tard.
_CALCULATRICE_COMPOSANTS_LEGACY = {"luzerne_post_coupe", "fenetre_epandage"}
_CALCULATRICE_OFFSET_UNITES = {"jours", "semaines", "mois"}
_CALCULATRICE_INPUT_TYPES = {"date"}
_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_BORNE_EVENT_OFFSET_RE = re.compile(
    r"^(?P<event>[a-z][a-z0-9_]*)"
    r"(?:(?P<sign>[+-])(?P<n>\d+)(?P<unit>jours|semaines|mois))?$"
)


def _parse_borne_calculatrice(val: str, input_ids: set[str]) -> tuple[bool, str | None]:
    """Parse une borne calculatrice. Retourne (is_event_based, error).

    - "JJ/MM" valide -> (False, None) -> borne date fixe
    - "<event>" ou "<event>±N<unit>" avec event dans input_ids -> (True, None)
    - sinon -> (False, "message d'erreur")
    """
    if not isinstance(val, str) or not val:
        return False, "valeur vide"
    if DATE_FIXE_RE.match(val):
        return (False, None) if _is_valid_date(val) else (False, "date invalide")
    m = _BORNE_EVENT_OFFSET_RE.match(val)
    if not m:
        return (
            False,
            f"borne {val!r} : ni date JJ/MM, ni event nu, ni event±N(jours|semaines|mois)",
        )
    event_id = m.group("event")
    if event_id not in input_ids:
        return (
            True,
            f"borne {val!r} : event {event_id!r} absent de inputs_requis",
        )
    if m.group("sign"):
        try:
            n = int(m.group("n"))
        except ValueError:
            return True, f"borne {val!r} : offset numerique invalide"
        if n < 1:
            return True, f"borne {val!r} : offset doit etre >= 1"
    return True, None


def _check_calculatrice(arbre: dict) -> list[str]:
    """Validation specifique au type=calculatrice (cf. spec grammaire
    calculatrice 2026-05-26). Vit en parallele des autres types : aucun
    impact sur interdiction / autorisation_sous_condition / plafonnement /
    libre / non_applicable / mixte.

    Regles (1-9 de la spec) :
      1. `inputs_requis` obligatoire et non vide.
      2. Chaque input : id (slug), label (str), type ('date'), placeholder (JJ/MM).
      3. Unicite des `id` dans inputs_requis.
      4. `periodes` obligatoire et non vide.
      5. Chaque borne (du, au) : date fixe OU event nu OU event+/-N(unit),
         avec event dans inputs_requis et N >= 1.
      6. Au moins une borne reference un event.
      7. `regime` dans l'enum standard.
      8. `composant` obligatoire, valeur dans la liste fermee.
      9. Tout id de inputs_requis doit etre reference par au moins une borne
         (warning sinon -- input mort).
    """
    errors: list[str] = []
    for obj in _walk_objects(arbre):
        if not isinstance(obj, dict) or obj.get("type") != "calculatrice":
            continue
        # La nouvelle grammaire calculatrice ne s'applique qu'au composant
        # `calendrier_dynamique_couvert`. Les composants legacy
        # (luzerne_post_coupe, fenetre_epandage) suivent l'ancienne shape
        # (inputs_requis = [str], pas de periodes) et sont laisses passer
        # en attendant leur migration. Une calculatrice SANS composant
        # explicit reste validee par la nouvelle grammaire (regle 8 : composant
        # obligatoire).
        if obj.get("composant") in _CALCULATRICE_COMPOSANTS_LEGACY:
            continue
        rid = obj.get("id", "?")

        # Regle 1 : inputs_requis obligatoire et non vide
        inputs = obj.get("inputs_requis") or []
        if not inputs:
            errors.append(
                f"[calculatrice] regle '{rid}' : `inputs_requis` obligatoire et non vide."
            )

        # Regle 2-3 : chaque input bien forme + unicite des ids
        input_ids: list[str] = []
        for i, inp in enumerate(inputs, start=1):
            if not isinstance(inp, dict):
                errors.append(
                    f"[calculatrice] regle '{rid}' input #{i} : doit etre un "
                    f"objet {{id, label, type, placeholder}}, pas {type(inp).__name__}."
                )
                continue
            iid = inp.get("id")
            if not isinstance(iid, str) or not iid or not _SLUG_RE.match(iid):
                errors.append(
                    f"[calculatrice] regle '{rid}' input #{i} : `id` "
                    f"obligatoire au format slug snake_case (recu {iid!r})."
                )
            else:
                input_ids.append(iid)
            label = inp.get("label")
            if not isinstance(label, str) or not label.strip():
                errors.append(
                    f"[calculatrice] regle '{rid}' input #{i} : `label` "
                    f"obligatoire (chaine non vide)."
                )
            itype = inp.get("type")
            if itype not in _CALCULATRICE_INPUT_TYPES:
                errors.append(
                    f"[calculatrice] regle '{rid}' input #{i} : `type` doit "
                    f"etre dans {sorted(_CALCULATRICE_INPUT_TYPES)} "
                    f"(recu {itype!r})."
                )
            ph = inp.get("placeholder")
            if ph is not None:
                if (
                    not isinstance(ph, str)
                    or not DATE_FIXE_RE.match(ph)
                    or not _is_valid_date(ph)
                ):
                    errors.append(
                        f"[calculatrice] regle '{rid}' input #{i} : "
                        f"`placeholder` doit etre une date JJ/MM valide "
                        f"(recu {ph!r})."
                    )
            # label_court optionnel (cf. spec_rendu_simulateur_calculatrice.md).
            # Si present, doit etre une chaine non vide.
            label_court = inp.get("label_court")
            if label_court is not None and (
                not isinstance(label_court, str) or not label_court.strip()
            ):
                errors.append(
                    f"[calculatrice] regle '{rid}' input #{i} : "
                    f"`label_court` doit etre une chaine non vide "
                    f"si present (recu {label_court!r})."
                )
        # Regle 3 : unicite des ids
        if len(input_ids) != len(set(input_ids)):
            from collections import Counter

            dup = [k for k, n in Counter(input_ids).items() if n > 1]
            errors.append(
                f"[calculatrice] regle '{rid}' : ids d'inputs dupliques : {dup}."
            )

        input_ids_set = set(input_ids)

        # Regle 4 : periodes obligatoire et non vide
        periodes = obj.get("periodes") or []
        if not periodes:
            errors.append(
                f"[calculatrice] regle '{rid}' : `periodes` obligatoire et non vide."
            )

        # Regles 5 + 6 + 7 : bornes valides, au moins une event, regime ok
        # + condition (extension grammaire spec_extension_grammaire_condition).
        events_utilises: set[str] = set()
        au_moins_une_event = False
        # inputs_requis sous forme dict pour la validation de condition.
        inputs_for_condition = [i for i in inputs if isinstance(i, dict)]
        for i, p in enumerate(periodes, start=1):
            for borne_name in ("du", "au"):
                val = p.get(borne_name)
                if val is None:
                    continue
                is_event, err = _parse_borne_calculatrice(val, input_ids_set)
                if err:
                    errors.append(
                        f"[calculatrice] regle '{rid}' periode #{i} {borne_name} : {err}"
                    )
                if is_event:
                    au_moins_une_event = True
                    m = _BORNE_EVENT_OFFSET_RE.match(val)
                    if m and m.group("event") in input_ids_set:
                        events_utilises.add(m.group("event"))
            preg = p.get("regime")
            if preg is not None and preg not in _CALCULATRICE_REGIMES:
                errors.append(
                    f"[calculatrice] regle '{rid}' periode #{i} : regime "
                    f"{preg!r} inconnu (attendu : {sorted(_CALCULATRICE_REGIMES)})."
                )
            raw_cond = p.get("condition")
            if raw_cond is not None:
                if not isinstance(raw_cond, str) or not raw_cond.strip():
                    errors.append(
                        f"[calculatrice] regle '{rid}' periode #{i} : "
                        f"`condition` doit etre une chaine non vide si presente."
                    )
                else:
                    _, cond_err = validate_condition(raw_cond, inputs_for_condition)
                    if cond_err:
                        errors.append(
                            f"[calculatrice] regle '{rid}' periode #{i} : {cond_err}"
                        )
        # Warning "duplicate condition" : laisse hors validator (spec
        # spec_extension_grammaire_condition : non-bloquant, suggestion
        # stylistique). A reintegrer si on cree un canal warnings dedie.
        if periodes and not au_moins_une_event:
            errors.append(
                f"[calculatrice] regle '{rid}' : aucune borne ne reference un "
                f"event (auquel cas un `type: mixte` suffit, calculatrice "
                f"n'a pas de sens)."
            )

        # Regle 8 : composant obligatoire et dans la liste fermee
        composant = obj.get("composant")
        if not composant:
            errors.append(f"[calculatrice] regle '{rid}' : `composant` obligatoire.")
        elif composant not in _CALCULATRICE_COMPOSANTS:
            errors.append(
                f"[calculatrice] regle '{rid}' : `composant` {composant!r} "
                f"inconnu (attendu : {sorted(_CALCULATRICE_COMPOSANTS)})."
            )

        # Regle 9 : tout input declare doit etre utilise par au moins une borne
        orphans = sorted(input_ids_set - events_utilises)
        if orphans:
            errors.append(
                f"[calculatrice] regle '{rid}' : inputs declares mais non "
                f"reference par aucune borne (inputs morts) : {orphans}."
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
