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

    @property
    def has_borne_flottante(self) -> bool:
        """True si au moins une periode contient une borne phenologique
        (slug type `brunissement_des_soies`, `derniere_coupe_luzerne`,
        etc.) plutot qu'une date fixe JJ/MM.

        Utilise par le template pour gater le prefixe "Sinon, regle de
        base —" qui n'a de sens que dans le cas mixte phenologique
        (un fallback complete une regle conditionnelle). En mixte
        purement a dates fixes, ce prefixe est trompeur (fix #81).
        """
        if not self.periodes:
            return False
        for p in self.periodes:
            du = p.get("du", "")
            au = p.get("au", "")
            # Une date fixe est de la forme JJ/MM (caractere 2 = '/').
            # Toute autre forme (slug phenologique) est une borne flottante.
            if len(du) != 5 or du[2] != "/":
                return True
            if len(au) != 5 or au[2] != "/":
                return True
        return False

    def to_json_dict(self) -> dict:
        """Serialise pour exposition JSON cote front (json_script Django).

        Utilise par le module epandage_aujourdhui.js pour calculer le
        statut effectif a la date du jour : besoin uniquement des champs
        regle_id / type / periodes (avec regime) / texte_condition.
        On expose aussi message / code_prescription pour info debug, mais
        le calcul de statut ne s'en sert pas.
        """
        return {
            "regle_id": self.regle_id,
            "type": self.type,
            "periodes": self.periodes or [],
            "texte_condition": self.texte_condition,
            "message": self.message,
            "code_prescription": self.code_prescription,
        }


@dataclass
class QuestionFormulaire:
    """Une question a poser a l'utilisateur.

    Quand `parent_champ` est non None, cette question n'est pertinente que
    si l'utilisateur a repondu `parent_valeur` a la question `parent_champ`
    en amont. Le template peut alors cacher/afficher dynamiquement la
    question selon la valeur choisie cote front, sans aller-retour serveur
    (cf. #58.1).
    """

    noeud_id: str
    champ: str
    niveau: str
    texte: str
    aide: str | None = None
    choix: list[dict] = field(default_factory=list)  # [{valeur, libelle?}, ...]
    parent_champ: str | None = None
    parent_valeur: Any = None


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
        new_chemin = chemin + [f"renvoi_vers:{cible_id}"]
        # Si la cible est un noeud (sous-arbre reutilisable), on re-descend
        # dedans avec le meme contexte. Sinon (cible = regle), on retourne
        # directement le resultat.
        if cible.get("type_noeud") in ("formulaire", "catalogue"):
            return _descendre(cible, contexte, new_chemin, index_ids)
        return _faire_resultat(cible, new_chemin)
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

    Pour les questions conditionnelles (en aval d'une branche dont le
    parent n'a pas encore ete repondu), on les remonte aussi mais en
    annotant `parent_champ` + `parent_valeur` : le template les rendra
    cachees au depart et le mini-JS subsidiaires_cascade.js les affichera
    quand l'utilisateur cliquera la bonne valeur. Resultat : un seul
    aller-retour serveur quel que soit le nombre de questions en cascade
    (cf. #58.1)."""
    questions: list[QuestionFormulaire] = []
    _ajouter_question(questions, noeud_formulaire)

    valeur = contexte.get(noeud_formulaire["champ"])
    if valeur is not None:
        # Cas "1re question deja repondue dans l'URL" : on descend
        # uniquement la branche choisie, sans questions conditionnelles.
        for branche in noeud_formulaire.get("branches", []):
            if _valeurs_egales(branche.get("valeur"), valeur):
                _collecter_aval_si_chemin_unique(branche, contexte, questions)
                break
    else:
        # Cas standard : on explore toutes les sous-branches du noeud
        # bloquant pour proposer les questions conditionnelles en cascade.
        for branche in noeud_formulaire.get("branches", []):
            _collecter_aval_conditionnel(
                branche,
                contexte,
                questions,
                parent_champ=noeud_formulaire["champ"],
                parent_valeur=branche.get("valeur"),
            )

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


def _collecter_aval_conditionnel(
    branche: dict,
    contexte: dict[str, Any],
    questions: list[QuestionFormulaire],
    parent_champ: str,
    parent_valeur: Any,
) -> None:
    """Comme `_collecter_aval_si_chemin_unique` mais pour le cas "1re
    question pas encore repondue" : on remonte les questions formulaire
    rencontrees en les annotant avec leur dependance au parent.

    Le front cachera les questions tant que `parent_champ` ne vaut pas
    `parent_valeur` cote utilisateur, et les revelera au clic. Aucun
    aller-retour serveur intermediaire necessaire.

    On ne descend pas les catalogues internes (resolus serveur uniquement)
    ni les sous-branches conditionnelles a 2 niveaux (rare en pratique,
    et ca alourdirait inutilement le rendu)."""
    if "noeud" not in branche:
        return
    sous = branche["noeud"]
    type_noeud = sous.get("type_noeud")
    if type_noeud != "formulaire":
        return
    _ajouter_question(
        questions,
        sous,
        parent_champ=parent_champ,
        parent_valeur=parent_valeur,
    )


def _ajouter_question(
    questions: list[QuestionFormulaire],
    noeud: dict,
    parent_champ: str | None = None,
    parent_valeur: Any = None,
) -> None:
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
            parent_champ=parent_champ,
            parent_valeur=parent_valeur,
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
    # Index les noeuds aussi pour autoriser renvoi_vers vers un sous-arbre
    # entier (pattern "include"). Ex: la branche luzerne / type_0 renvoie vers
    # q_prairie_plus6_type_0_icpe pour reutiliser la question complementaire
    # ICPE et toutes les feuilles sous-jacentes.
    if "id" in noeud:
        index[noeud["id"]] = noeud
    for branche in noeud.get("branches", []):
        if "regle" in branche and "id" in branche["regle"]:
            index[branche["regle"]["id"]] = branche["regle"]
        elif "noeud" in branche:
            _walk_for_index(branche["noeud"], index)


# ─── QC sur le chemin actuel (repondues + en attente) ──────────────────────


def collecter_qc_du_chemin(
    arbre: dict, contexte: dict[str, Any]
) -> list[QuestionFormulaire]:
    """Retourne TOUTES les questions complementaires (niveau formulaire =
    'complement') qui se trouvent sur le chemin actuel d'apres `contexte`,
    qu'elles soient deja repondues ou pas.

    Sert au rendu du panneau gauche : on doit reafficher chaque QC en cours
    avec ses choix REELS issus de l'arbre (pas une table hardcodee), y compris
    pour les QC en aval qui n'ont pas encore ete repondues.
    """
    qc: list[QuestionFormulaire] = []
    racine = arbre.get("arbre", {}).get("noeud")
    if not racine:
        return qc
    index_ids = _build_id_index(arbre)
    _suivre_chemin_pour_qc(racine, contexte, index_ids, qc, visites=set())
    return qc


def _suivre_chemin_pour_qc(
    noeud: dict,
    contexte: dict[str, Any],
    index_ids: dict[str, dict],
    qc: list[QuestionFormulaire],
    visites: set[str],
) -> None:
    """Descend un noeud en suivant la branche dictee par `contexte`. Collecte
    les QC de niveau complement croisees. S'arrete si la valeur du champ
    courant n'est pas dans le contexte (= QC bloquante atteinte ; on l'ajoute
    AVEC ses choix arbre puis on stop).
    """
    if "id" in noeud and noeud["id"] in visites:
        return
    if "id" in noeud:
        visites.add(noeud["id"])

    type_noeud = noeud.get("type_noeud")
    champ = noeud.get("champ")

    # QC = formulaire de niveau complement. On les collecte (repondues ou pas).
    if type_noeud == "formulaire" and noeud.get("niveau") == "complement":
        _ajouter_question(qc, noeud)

    valeur = contexte.get(champ) if champ else None
    if valeur is None:
        # On ne peut pas continuer plus loin sans reponse. Cas typique :
        # 1ere QC pas repondue -> on s'arrete ici. Pour les noeuds non-QC
        # (catalogue ou form principal), c'est pareil mais on a deja
        # collecte ce qu'il fallait.
        return

    branche = _choisir_branche_safe(noeud, valeur)
    if branche is None:
        return
    if "noeud" in branche:
        _suivre_chemin_pour_qc(branche["noeud"], contexte, index_ids, qc, visites)
    elif "renvoi_vers" in branche:
        cible = index_ids.get(branche["renvoi_vers"])
        if cible and cible.get("type_noeud") in ("formulaire", "catalogue"):
            _suivre_chemin_pour_qc(cible, contexte, index_ids, qc, visites)


def _choisir_branche_safe(noeud: dict, valeur) -> dict | None:
    """Comme _choisir_branche mais retourne None au lieu de raise quand la
    valeur ne matche pas une branche (cas d'un contexte incoherent qu'on
    veut tolerer dans la collecte QC pour ne pas casser l'affichage).
    Applique le meme fallback type_I = {type_Ia, type_Ib} que le parcours."""
    for branche in noeud.get("branches", []) or []:
        if _valeurs_egales(branche.get("valeur"), valeur):
            return branche
    # Fallback type_I (cf. _choisir_branche).
    if noeud.get("champ") == "type_fertilisant" and valeur in ("type_Ia", "type_Ib"):
        for branche in noeud.get("branches", []) or []:
            if branche.get("valeur") == "type_I":
                return branche
    return None
