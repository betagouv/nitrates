"""Parcours stateless de l'arbre de decision.

Le parcours prend (arbre, contexte) et descend l'arbre. Il s'arrete soit :
  - sur une feuille `regle` -> Resultat
  - sur une feuille `renvoi_vers` -> Resultat (resolu via l'id cible)
  - sur un noeud formulaire dont la reponse manque dans le contexte
    -> QuestionsSubsidiaires (avec collecte des autres noeuds formulaire
    bloquants des branches qu'on aurait pu prendre)
  - sur un noeud catalogue dont la reponse manque -> BesoinCatalogue
    (cas suppose rare : la moulinette pre-remplit normalement les noeuds
    catalogue racine ; les catalogues internes peuvent quand meme apparaitre
    si l'arbre fait des sous-requetes SIG plus profondes).

Le parcours est totalement stateless : on lui repasse arbre + contexte
enrichi et il retourne soit le resultat final, soit la prochaine etape.

Conception : on conserve l'arbre dans son integralite (cf. discussion avec
les juristes) -- y compris le noeud catalogue racine `n_zvn`. La moulinette
Envergo se charge d'injecter `en_zone_vulnerable=True/False` dans le
contexte avant d'appeler `parcours()`, et l'arbre descend tout seul.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Resultat:
    """Feuille atteinte : on a une regle finale a appliquer."""

    regle_id: str
    type: str
    chemin: list[str] = field(default_factory=list)
    # Champs metier copies depuis la regle (tous optionnels, dependent du type)
    message: str | None = None
    texte: str | None = None
    texte_condition: str | None = None
    periodes: list[dict] | None = None
    code_prescription: str | None = None
    note: str | None = None
    source_juridique: str | None = None
    plafond_azote_kg_n_ha: float | None = None
    plafonnement_associe: str | None = None
    composant: str | None = None
    inputs_requis: list[str] | None = None
    parametres: dict | None = None
    a_completer: bool = False


@dataclass
class QuestionFormulaire:
    """Une question a poser a l'utilisateur."""

    noeud_id: str
    champ: str
    niveau: str
    texte: str
    aide: str | None = None
    choix: list[dict] = field(default_factory=list)  # [{valeur, libelle?}, ...]


@dataclass
class QuestionsSubsidiaires:
    """Le parcours a bute sur un ou plusieurs noeuds formulaire dont la
    reponse manque. On les retourne tous d'un coup pour eviter le
    ping-pong question-par-question."""

    questions: list[QuestionFormulaire]
    chemin_partiel: list[str] = field(default_factory=list)

    @property
    def champs_set(self) -> set[str]:
        """Set des champs des questions en cours. Utile cote template
        pour ne pas re-render ces champs en hidden input (collision)."""
        return {q.champ for q in self.questions}


@dataclass
class BesoinCatalogue:
    """Le parcours a bute sur un noeud catalogue interne dont la reponse
    manque dans le contexte. La moulinette doit le resoudre puis rappeler
    parcours() avec le contexte enrichi."""

    noeud_id: str
    champ: str
    source: str  # sig / mapping_referentiel / calcul
    reference: str | None = None
    chemin_partiel: list[str] = field(default_factory=list)


class ParcoursError(Exception):
    """Levee quand l'arbre est dans un etat impossible a parcourir
    (ex : valeur du contexte ne correspond a aucune branche)."""


def parcours(
    arbre: dict, contexte: dict[str, Any]
) -> Resultat | QuestionsSubsidiaires | BesoinCatalogue:
    """Point d'entree principal. Descend l'arbre depuis la racine."""
    racine = arbre.get("arbre", {}).get("noeud")
    if not racine:
        raise ParcoursError("arbre sans noeud racine")
    index_ids = _build_id_index(arbre)
    return _descendre(racine, contexte, [], index_ids)


# ─── Descente ───────────────────────────────────────────────────────────────


def _descendre(
    noeud: dict,
    contexte: dict[str, Any],
    chemin: list[str],
    index_ids: dict[str, dict],
) -> Resultat | QuestionsSubsidiaires | BesoinCatalogue:
    """Descend un noeud. Recursif sur les sous-noeuds atteints."""
    chemin = chemin + [noeud["id"]]
    type_noeud = noeud.get("type_noeud")
    champ = noeud["champ"]
    valeur = contexte.get(champ)

    if valeur is None:
        # Reponse manquante : on s'arrete et on retourne ce qu'il faut
        if type_noeud == "formulaire":
            questions = _collecter_questions(noeud, contexte, index_ids)
            return QuestionsSubsidiaires(
                questions=questions, chemin_partiel=chemin[:-1]
            )
        # catalogue
        return BesoinCatalogue(
            noeud_id=noeud["id"],
            champ=champ,
            source=noeud.get("source", ""),
            reference=noeud.get("reference"),
            chemin_partiel=chemin[:-1],
        )

    branche = _choisir_branche(noeud, valeur)
    return _descendre_branche(branche, contexte, chemin, index_ids)


def _descendre_branche(
    branche: dict,
    contexte: dict[str, Any],
    chemin: list[str],
    index_ids: dict[str, dict],
) -> Resultat | QuestionsSubsidiaires | BesoinCatalogue:
    """Une fois la branche choisie, on suit ce qu'elle pointe."""
    if "noeud" in branche:
        return _descendre(branche["noeud"], contexte, chemin, index_ids)
    if "regle" in branche:
        return _faire_resultat(branche["regle"], chemin)
    if "renvoi_vers" in branche:
        cible_id = branche["renvoi_vers"]
        cible = index_ids.get(cible_id)
        if cible is None:
            raise ParcoursError(
                f"renvoi_vers '{cible_id}' ne pointe vers aucun id existant"
            )
        # On marque le renvoi dans le chemin pour que la trace reste lisible.
        return _faire_resultat(cible, chemin + [f"renvoi_vers:{cible_id}"])
    raise ParcoursError(f"branche sans noeud/regle/renvoi_vers : {branche!r}")


def _choisir_branche(noeud: dict, valeur: Any) -> dict:
    for branche in noeud.get("branches", []):
        if _valeurs_egales(branche.get("valeur"), valeur):
            return branche

    # Fallback metier : sur un noeud `type_fertilisant`, l'arbre peut avoir
    # une branche generique `type_I` qui couvre l'union {type_Ia, type_Ib}.
    # Selon spec metier 2026-04 : "type I" = "type Ia ou Ib" indistinctement.
    # Le mapping sous_fertilisant -> type genere uniquement type_Ia ou
    # type_Ib (jamais type_I), donc on retombe sur type_I si dispo.
    if noeud.get("champ") == "type_fertilisant" and valeur in ("type_Ia", "type_Ib"):
        for branche in noeud.get("branches", []):
            if branche.get("valeur") == "type_I":
                return branche

    raise ParcoursError(
        f"noeud '{noeud['id']}' (champ={noeud['champ']!r}) : aucune branche "
        f"ne correspond a la valeur {valeur!r}. "
        f"Valeurs possibles : {[b.get('valeur') for b in noeud.get('branches', [])]}"
    )


def _valeurs_egales(branche_val: Any, contexte_val: Any) -> bool:
    """Compare une valeur de branche YAML (typee : bool, int, str) a une
    valeur du contexte (qui peut venir d'une query string et donc etre
    une string).

    Cas particuliers :
      - bool YAML vs string ('True'/'true'/'False'/'false') : on tolere
      - int YAML vs string numerique : on tolere
      - sinon comparaison stricte
    """
    if branche_val == contexte_val:
        return True
    # Bool YAML <-> string contexte
    if isinstance(branche_val, bool) and isinstance(contexte_val, str):
        normalise = contexte_val.strip().lower()
        if branche_val is True and normalise in ("true", "oui", "1"):
            return True
        if branche_val is False and normalise in ("false", "non", "0"):
            return True
    # Int YAML <-> string numerique. (`bool` etant une sous-classe de `int`,
    # on l'exclut explicitement pour ne pas matcher 0/1 comme True/False
    # ici -- deja gere ci-dessus.)
    if (
        isinstance(branche_val, int)
        and not isinstance(branche_val, bool)
        and isinstance(contexte_val, str)
    ):
        try:
            return branche_val == int(contexte_val)
        except ValueError:
            return False
    return False


# ─── Resultat ───────────────────────────────────────────────────────────────


_REGLE_FIELDS = (
    "message",
    "texte",
    "texte_condition",
    "periodes",
    "code_prescription",
    "note",
    "source_juridique",
    "plafond_azote_kg_n_ha",
    "plafonnement_associe",
    "composant",
    "inputs_requis",
    "parametres",
)


def _faire_resultat(regle: dict, chemin: list[str]) -> Resultat:
    """Convertit une regle YAML en dataclass Resultat. Les regles `a_completer`
    (stub brouillon) peuvent ne pas avoir de champ `type` -- on tolere."""
    return Resultat(
        regle_id=regle["id"],
        type=regle.get("type", "a_completer"),
        chemin=chemin + [regle["id"]],
        a_completer=bool(regle.get("a_completer", False)),
        **{k: regle.get(k) for k in _REGLE_FIELDS},
    )


# ─── Collecte des questions subsidiaires ────────────────────────────────────


def _collecter_questions(
    noeud_formulaire: dict, contexte: dict[str, Any], index_ids: dict[str, dict]
) -> list[QuestionFormulaire]:
    """A partir d'un noeud formulaire bloquant, retourne la liste des
    questions a poser en BATCH **sur la branche en cours uniquement**.

    Strategie :
      - Le 1er noeud qui bloque est inclus.
      - On ne descend dans les sous-branches que si le contexte fournit
        deja une valeur permettant de choisir la branche (cas typique :
        l'utilisateur a rempli les niveaux precedents, on suit son
        chemin specifique). On collecte ainsi les questions strictement
        en aval du chemin choisi.
      - Si le noeud bloque sans qu'aucune valeur ne soit dans le contexte,
        on n'explore PAS toutes les sous-branches latĂŠrales : on s'arrete
        sur ce noeud, l'utilisateur repondra et on collectera la suite au
        prochain tour.
      - Les noeuds catalogue sont traverses sans etre listes (resolus par
        la moulinette via SIG, pas par l'utilisateur). Mais on ne descend
        que si le catalogue est resolu dans le contexte ; sinon on
        s'arrete.

    Cette strategie garantit que l'utilisateur ne voit jamais de questions
    qui ne le concernent pas (branches laterales non choisies)."""
    questions: list[QuestionFormulaire] = []
    _ajouter_question(questions, noeud_formulaire)

    # On essaie de descendre seulement si la valeur du noeud bloquant est
    # connue dans le contexte. Mais par definition, si on arrive ici c'est
    # que la valeur est absente : donc on s'arrete au 1er noeud.
    # CEPENDANT : le walker peut etre appele depuis un point ou la 1re
    # question est repondue mais d'autres en aval ne le sont pas.
    # Pour rester correct, on essaie de descendre branche par branche
    # selon le contexte.
    valeur = contexte.get(noeud_formulaire["champ"])
    if valeur is not None:
        for branche in noeud_formulaire.get("branches", []):
            if _valeurs_egales(branche.get("valeur"), valeur):
                _collecter_aval_si_chemin_unique(branche, contexte, questions)
                break

    return questions


def _collecter_aval_si_chemin_unique(
    branche: dict,
    contexte: dict[str, Any],
    questions: list[QuestionFormulaire],
) -> None:
    """Suit la branche en cours et collecte les noeuds formulaire en aval
    tant qu'on peut identifier le chemin (valeurs presentes dans le
    contexte ou catalogue resolu)."""
    if "noeud" not in branche:
        return
    sous = branche["noeud"]
    type_noeud = sous.get("type_noeud")

    if type_noeud == "formulaire":
        # Question : on l'ajoute. Si la reponse est dans le contexte, on
        # peut continuer a descendre ; sinon on s'arrete.
        _ajouter_question(questions, sous)
        valeur = contexte.get(sous["champ"])
        if valeur is None:
            return
        for sb in sous.get("branches", []):
            if _valeurs_egales(sb.get("valeur"), valeur):
                _collecter_aval_si_chemin_unique(sb, contexte, questions)
                break
        return

    if type_noeud == "catalogue":
        # Catalogue : pas de question utilisateur. On descend uniquement si
        # la valeur est dans le contexte (catalogue deja resolu par la
        # moulinette ou par un tour precedent).
        valeur = contexte.get(sous["champ"])
        if valeur is None:
            return
        for sb in sous.get("branches", []):
            if _valeurs_egales(sb.get("valeur"), valeur):
                _collecter_aval_si_chemin_unique(sb, contexte, questions)
                break


def _ajouter_question(questions: list[QuestionFormulaire], noeud: dict) -> None:
    """Ajoute une question si pas deja presente (par champ)."""
    champ = noeud["champ"]
    if any(q.champ == champ for q in questions):
        return
    questions.append(
        QuestionFormulaire(
            noeud_id=noeud["id"],
            champ=champ,
            niveau=noeud["niveau"],
            texte=noeud["texte"],
            aide=noeud.get("aide"),
            choix=[
                {"valeur": b["valeur"], "libelle": b.get("libelle")}
                for b in noeud.get("branches", [])
            ],
        )
    )


# ─── Index des ids (pour resoudre renvoi_vers) ──────────────────────────────


def _build_id_index(arbre: dict) -> dict[str, dict]:
    """Construit {id: regle_dict} pour resoudre les renvoi_vers en O(1)."""
    index: dict[str, dict] = {}
    racine = arbre.get("arbre", {}).get("noeud")
    if racine:
        _walk_for_index(racine, index)
    for entry in arbre.get("plafonnements", []) or []:
        regle = entry.get("regle")
        if regle and "id" in regle:
            index[regle["id"]] = regle
    return index


def _walk_for_index(noeud: dict, index: dict[str, dict]) -> None:
    for branche in noeud.get("branches", []):
        if "regle" in branche and "id" in branche["regle"]:
            index[branche["regle"]["id"]] = branche["regle"]
        elif "noeud" in branche:
            _walk_for_index(branche["noeud"], index)
