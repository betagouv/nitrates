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
        if branche.get("valeur") == valeur:
            return branche
    raise ParcoursError(
        f"noeud '{noeud['id']}' (champ={noeud['champ']!r}) : aucune branche "
        f"ne correspond a la valeur {valeur!r}. "
        f"Valeurs possibles : {[b.get('valeur') for b in noeud.get('branches', [])]}"
    )


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
    """A partir d'un noeud formulaire bloquant, retourne la liste des questions
    a poser. On commence par celle qui bloque, puis on collecte les noeuds
    formulaire qui suivent sur les branches qu'on pourrait prendre apres
    avoir repondu (questions de sous-niveau qui seront forcement posees).

    Strategie pragmatique : pour chaque branche, on plonge et on collecte
    les premiers noeuds formulaire rencontres. Si toutes les branches
    convergent vers les memes niveaux suivants, ca evite un aller-retour.
    Si elles divergent, on liste tout ce qui pourrait etre demande -- le
    front filtrera selon les reponses au fur et a mesure."""
    questions: list[QuestionFormulaire] = [_question_de(noeud_formulaire)]
    deja_vus: set[str] = {noeud_formulaire["id"]}
    for branche in noeud_formulaire.get("branches", []):
        _collecter_questions_aval(branche, deja_vus, questions, index_ids)
    return questions


def _collecter_questions_aval(
    branche: dict,
    deja_vus: set[str],
    questions: list[QuestionFormulaire],
    index_ids: dict[str, dict],
) -> None:
    if "noeud" in branche:
        sous = branche["noeud"]
        if sous.get("type_noeud") == "formulaire" and sous["id"] not in deja_vus:
            deja_vus.add(sous["id"])
            questions.append(_question_de(sous))
            for sb in sous.get("branches", []):
                _collecter_questions_aval(sb, deja_vus, questions, index_ids)
        elif sous.get("type_noeud") == "catalogue":
            # On traverse les catalogues sans les inclure (ils ne sont pas
            # poses a l'utilisateur).
            for sb in sous.get("branches", []):
                _collecter_questions_aval(sb, deja_vus, questions, index_ids)


def _question_de(noeud: dict) -> QuestionFormulaire:
    return QuestionFormulaire(
        noeud_id=noeud["id"],
        champ=noeud["champ"],
        niveau=noeud["niveau"],
        texte=noeud["texte"],
        aide=noeud.get("aide"),
        choix=[
            {"valeur": b["valeur"], "libelle": b.get("libelle")}
            for b in noeud.get("branches", [])
        ],
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
