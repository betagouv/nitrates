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

from envergo.nitrates.yaml_tree.expression import evaluer_expression


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
    # Code(s) de prescription conditionnee. Le YAML accepte un scalaire (1 PC)
    # ou une liste (plusieurs PC) ; en interne on normalise TOUJOURS en liste
    # (`codes_prescription`). `code_prescription` est conserve pour la compat
    # (= le 1er code, ou None) -- les call-sites historiques continuent de
    # marcher, les nouveaux (templates, patch) iterent sur la liste.
    codes_prescription: list[str] = field(default_factory=list)
    note: str | None = None
    source_juridique: str | None = None
    plafond_azote_kg_n_ha: float | None = None
    plafonnement_associe: str | None = None
    composant: str | None = None
    # inputs_requis : liste polymorphe (cf. spec_grammaire_calculatrice.md) :
    #   - list[str] pour les composants legacy (luzerne_post_coupe, fenetre_epandage)
    #   - list[dict{id,label,type,placeholder,label_court?}] pour la
    #     nouvelle grammaire calculatrice (calendrier_dynamique_couvert).
    inputs_requis: list | None = None
    parametres: dict | None = None
    a_completer: bool = False

    @property
    def code_prescription(self) -> str | None:
        """Compat : 1er code de prescription (ou None). Les nouveaux call-sites
        utilisent `codes_prescription` (liste complete)."""
        return self.codes_prescription[0] if self.codes_prescription else None

    @property
    def has_borne_flottante(self) -> bool:
        """True si au moins une periode contient une borne phenologique
        (slug type `brunissement_des_soies`, `derniere_coupe_luzerne`,
        etc.) plutot qu'une date fixe JJ/MM.
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

    @property
    def has_autorisation_sous_condition(self) -> bool:
        """True si au moins une periode est de regime
        `autorisation_sous_condition`. Utilise par le template pour
        gater le prefixe "Sinon, regle de base —" (cf. #88)."""
        if not self.periodes:
            return False
        return any(
            p.get("regime") == "autorisation_sous_condition" for p in self.periodes
        )

    @property
    def has_interdiction(self) -> bool:
        """True si au moins une periode est de regime `interdiction`
        (regle de base). Combine avec has_autorisation_sous_condition,
        sert a decider si on affiche la mention "Sinon, regle de base —"
        au-dessus de la ligne d'interdiction (#88)."""
        if not self.periodes:
            return False
        return any(p.get("regime") == "interdiction" for p in self.periodes)

    def to_json_dict(self) -> dict:
        """Serialise pour exposition JSON cote front (json_script Django).

        Utilise par :
          - calculatrice-calendrier.js : rendu du calendrier dynamique
            pour les feuilles type=calculatrice. Besoin de regle_id / type /
            periodes / texte_condition / composant / inputs_requis /
            verdict (= message).
        """
        return {
            "regle_id": self.regle_id,
            "type": self.type,
            "periodes": self.periodes or [],
            "texte_condition": self.texte_condition,
            "message": self.message,
            "code_prescription": self.code_prescription,  # compat : 1er PC
            "codes_prescription": self.codes_prescription,
            # Champs calculatrice (None si type != calculatrice).
            "composant": self.composant,
            "inputs_requis": self.inputs_requis or [],
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


@dataclass
class RenvoiArbre:
    """Le parcours a atteint une feuille `renvoi_arbre` : renvoi EXPLICITE vers
    un autre arbre de la cascade (ex une branche ZAR qui renvoie au PAR).

    `scope_cible` designe l'arbre vise par son scope (region / national).
    L'evaluateur, qui connait la liste des arbres actifs pour ce point, bascule
    sur l'arbre candidat de ce scope et le re-parcourt depuis sa racine avec le
    meme contexte cumulatif."""

    scope_cible: str  # "region" | "national" | "zar"
    chemin_partiel: list[str] = field(default_factory=list)


class ParcoursError(Exception):
    """Levee quand l'arbre est dans un etat impossible a parcourir
    (ex : valeur du contexte ne correspond a aucune branche)."""


def parcours(
    arbre: dict,
    contexte: dict[str, Any],
    resoudre_catalogue=None,
) -> Resultat | QuestionsSubsidiaires | BesoinCatalogue | RenvoiArbre:
    """Point d'entree principal. Descend l'arbre depuis la racine.

    `resoudre_catalogue` (optionnel) : callback `(noeud_catalogue) -> valeur`
    fourni par l'evaluateur, capable de resoudre un noeud catalogue SIG a la
    demande (via code_insee / geo). Il n'est PAS utilise pour le routage reel
    (l'evaluateur gere ca via BesoinCatalogue), mais UNIQUEMENT pour aplatir le
    sous-arbre au moment de collecter les questions complementaires en batch :
    les noeuds SIG/catalogue_parametre intercales entre deux QC sont resolus a
    la volee pour que la QC descendante soit prefetchee sans aller-retour
    (cf. #187). Retourne None si irresolvable -> la collecte s'arrete
    proprement sur ce noeud (fallback submit)."""
    racine = arbre.get("arbre", {}).get("noeud")
    if not racine:
        raise ParcoursError("arbre sans noeud racine")
    index_ids = _build_id_index(arbre)
    return _descendre(racine, contexte, [], index_ids, resoudre_catalogue)


# ─── Descente ───────────────────────────────────────────────────────────────


def _descendre(
    noeud: dict,
    contexte: dict[str, Any],
    chemin: list[str],
    index_ids: dict[str, dict],
    resoudre_catalogue=None,
) -> Resultat | QuestionsSubsidiaires | BesoinCatalogue:
    """Descend un noeud. Recursif sur les sous-noeuds atteints."""
    chemin = chemin + [noeud["id"]]
    type_noeud = noeud.get("type_noeud")
    champ = noeud["champ"]

    # Noeud catalogue parametre (cf. issue #128) : le branchement ne se fait
    # PAS par lecture de contexte.get(champ) mais par evaluation d'une
    # expression Python par branche (premiere vraie l'emporte). On le traite
    # avant la lecture de `valeur` car `champ` n'est ici qu'un nom logique de
    # sortie (trace), pas une cle de routage.
    if type_noeud == "catalogue_parametre":
        return _resoudre_catalogue_parametre(
            noeud, contexte, chemin, index_ids, resoudre_catalogue
        )

    valeur = contexte.get(champ)

    if valeur is None:
        # Reponse manquante : on s'arrete et on retourne ce qu'il faut
        if type_noeud == "formulaire":
            questions = _collecter_questions(
                noeud, contexte, index_ids, resoudre_catalogue
            )
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
    return _descendre_branche(branche, contexte, chemin, index_ids, resoudre_catalogue)


def _descendre_branche(
    branche: dict,
    contexte: dict[str, Any],
    chemin: list[str],
    index_ids: dict[str, dict],
    resoudre_catalogue=None,
) -> Resultat | QuestionsSubsidiaires | BesoinCatalogue | RenvoiArbre:
    """Une fois la branche choisie, on suit ce qu'elle pointe."""
    if branche.get("feuille_vide"):
        # Feuille vide : reponse explicite SANS regle (rend la branche
        # cliquable dans le formulaire sans produire de resultat). Au runtime
        # = no-match -> la cascade tombe sur l'arbre inferieur (PAR puis PAN).
        # Reservee aux PAR/ZAR (le PAN doit etre couvrant, cf. validateur).
        raise ParcoursError(
            f"feuille_vide atteinte (chemin {'/'.join(chemin)}) : "
            f"pas de regle ici, fallback vers l'arbre inferieur."
        )
    if "noeud" in branche:
        return _descendre(
            branche["noeud"], contexte, chemin, index_ids, resoudre_catalogue
        )
    if "regle" in branche:
        return _faire_resultat(branche["regle"], chemin, index_ids)
    if "renvoi_arbre" in branche:
        # Renvoi explicite vers un autre arbre de la cascade (ex ZAR -> PAR).
        # L'evaluateur resout le scope cible et re-parcourt cet arbre.
        scope_cible = branche["renvoi_arbre"]
        return RenvoiArbre(
            scope_cible=scope_cible,
            chemin_partiel=chemin + [f"renvoi_arbre:{scope_cible}"],
        )
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
        if cible.get("type_noeud") in (
            "formulaire",
            "catalogue",
            "catalogue_parametre",
        ):
            res = _descendre(cible, contexte, new_chemin, index_ids, resoudre_catalogue)
        else:
            res = _faire_resultat(cible, new_chemin, index_ids)
        # Patch optionnel : remappe les codes de prescription sur la feuille
        # atteinte (ex pc12 -> pc14). Permet de reutiliser un sous-arbre en ne
        # changeant que les PC, sans dupliquer toutes les feuilles.
        patch = branche.get("patch")
        if patch and isinstance(res, Resultat):
            _appliquer_patch(res, patch)
        return res
    raise ParcoursError(
        f"branche sans noeud/regle/renvoi_vers/renvoi_arbre : {branche!r}"
    )


def _resoudre_catalogue_parametre(
    noeud: dict,
    contexte: dict[str, Any],
    chemin: list[str],
    index_ids: dict[str, dict],
    resoudre_catalogue=None,
) -> Resultat | QuestionsSubsidiaires | BesoinCatalogue:
    """Resout un noeud `catalogue_parametre` (issue #128).

    On evalue l'`expression` de chaque branche dans l'ordre, en sandbox
    (cf. expression.evaluer_expression). La PREMIERE expression vraie
    l'emporte : on ecrit la `valeur` de la branche dans le contexte sous la
    cle `champ` du noeud (tracabilite + coherence avec les catalogues
    classiques, cf. spec #128 §4) puis on descend dedans.

    Aucune notion de branche `defaut` : si aucune expression n'est vraie, le
    parcours leve ParcoursError (l'arbre doit couvrir tous les cas via ses
    expressions ; un juriste qui veut un fallback ecrit `expression: "True"`
    en derniere branche). L'evaluateur retombe alors sur `non_disponible`.
    """
    champ = noeud["champ"]
    for branche in noeud.get("branches", []):
        expression = branche.get("expression")
        if evaluer_expression(expression, contexte):
            # Trace : la valeur resolue devient lisible dans le contexte
            # (debug, mini-app de validation). N'influe pas sur le routage.
            if "valeur" in branche:
                contexte[champ] = branche["valeur"]
            return _descendre_branche(
                branche, contexte, chemin, index_ids, resoudre_catalogue
            )

    expressions = [b.get("expression") for b in noeud.get("branches", [])]
    raise ParcoursError(
        f"noeud catalogue_parametre '{noeud['id']}' (champ={champ!r}) : "
        f"aucune expression vraie pour le contexte courant. "
        f"Expressions evaluees : {expressions}"
    )


def _choisir_branche(noeud: dict, valeur: Any) -> dict:
    for branche in noeud.get("branches", []):
        # Cas branche `valeur:` (singulier, valeur unique).
        if "valeur" in branche and _valeurs_egales(branche.get("valeur"), valeur):
            return branche
        # Cas branche `valeurs:` (pluriel, liste de valeurs équivalentes,
        # cf. grammaire #61 phase 3). Ex `valeurs: [icpe_e, icpe_d]` pour
        # regrouper enregistrement + déclaration sur la même branche.
        valeurs_liste = branche.get("valeurs")
        if valeurs_liste:
            for v in valeurs_liste:
                if _valeurs_egales(v, valeur):
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

    valeurs_disponibles = []
    for b in noeud.get("branches", []):
        if "valeur" in b:
            valeurs_disponibles.append(b["valeur"])
        elif "valeurs" in b:
            valeurs_disponibles.extend(b["valeurs"])
    raise ParcoursError(
        f"noeud '{noeud['id']}' (champ={noeud['champ']!r}) : aucune branche "
        f"ne correspond a la valeur {valeur!r}. "
        f"Valeurs possibles : {valeurs_disponibles}"
    )


def _valeurs_egales(branche_val: Any, contexte_val: Any) -> bool:
    """Compare une valeur de branche YAML (typee : bool, int, str) a une
    valeur du contexte (qui peut venir d'une query string et donc etre
    une string).

    Cas particuliers :
      - bool YAML vs string ('True'/'true'/'False'/'false') : on tolere
      - string YAML ('True'/'False'/...) vs bool contexte : on tolere aussi
        (filet de securite : un gate catalogue booleen mal type via l'editeur
        ne doit pas casser le routage runtime, cf. bug PAR Grand Est)
      - int YAML vs string numerique : on tolere
      - sinon comparaison stricte
    """
    if branche_val == contexte_val:
        return True
    _VRAI = ("true", "oui", "1")
    _FAUX = ("false", "non", "0")
    # Bool YAML <-> string contexte
    if isinstance(branche_val, bool) and isinstance(contexte_val, str):
        normalise = contexte_val.strip().lower()
        if branche_val is True and normalise in _VRAI:
            return True
        if branche_val is False and normalise in _FAUX:
            return True
    # String YAML <-> bool contexte (sens inverse : la branche a ete saisie en
    # string 'True'/'False' alors que le resolveur catalogue renvoie un bool).
    # `bool` est une sous-classe de `int` : on teste bool AVANT tout traitement
    # int pour ne pas confondre.
    if isinstance(branche_val, str) and isinstance(contexte_val, bool):
        normalise = branche_val.strip().lower()
        if contexte_val is True and normalise in _VRAI:
            return True
        if contexte_val is False and normalise in _FAUX:
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
    "note",
    "source_juridique",
    "plafond_azote_kg_n_ha",
    "plafonnement_associe",
    "composant",
    "inputs_requis",
    "parametres",
)


def normaliser_codes_prescription(valeur) -> list[str]:
    """Normalise le champ `code_prescription` d'une regle (YAML) en list[str].

    Accepte : None -> [] ; scalaire 'pc4' -> ['pc4'] ; liste -> telle quelle
    (vide ignoree). Source unique de verite pour passer du polymorphisme YAML
    (scalaire OU liste) a la representation interne (toujours liste)."""
    if valeur is None:
        return []
    if isinstance(valeur, (list, tuple)):
        return [str(c) for c in valeur if c]
    return [str(valeur)]


def _faire_resultat(
    regle: dict, chemin: list[str], index_ids: dict[str, dict] | None = None
) -> Resultat:
    """Convertit une regle YAML en dataclass Resultat. Les regles `a_completer`
    (stub brouillon) peuvent ne pas avoir de champ `type` -- on tolere.

    Si la regle porte un `plafonnement_associe` (id d'une regle de la section
    `plafonnements`), on resout cette reference et on COMPLETE les champs metier
    absents de la feuille (plafond_azote_kg_n_ha, code_prescription) avec ceux
    du plafonnement. Indispensable pour les regles partagees CIE/CINE courte :
    elles ne portent pas le plafond inline, il vit dans la regle plafonnement
    referencee. Sans ca le panneau resultat n'affiche ni plafond ni PC (cf.
    retour Max 2026-06-18). On ne complete QUE les champs vides -> une feuille
    qui a deja son propre plafond/PC inline (cas 99%) n'est pas touchee."""
    valeurs = {k: regle.get(k) for k in _REGLE_FIELDS}
    codes = normaliser_codes_prescription(regle.get("code_prescription"))

    plaf_id = regle.get("plafonnement_associe")
    if plaf_id and index_ids:
        plaf = index_ids.get(plaf_id)
        if isinstance(plaf, dict):
            # Plafond chiffre : on le remonte si la feuille ne l'a pas deja.
            if valeurs.get("plafond_azote_kg_n_ha") is None:
                valeurs["plafond_azote_kg_n_ha"] = plaf.get("plafond_azote_kg_n_ha")
            # Code(s) prescription du plafonnement : ajoutes si la feuille n'en
            # a aucun (sinon on garde ceux de la feuille, plus specifiques).
            if not codes:
                codes = normaliser_codes_prescription(plaf.get("code_prescription"))

    return Resultat(
        regle_id=regle["id"],
        type=regle.get("type", "a_completer"),
        chemin=chemin + [regle["id"]],
        a_completer=bool(regle.get("a_completer", False)),
        codes_prescription=codes,
        **valeurs,
    )


def _appliquer_patch(res: "Resultat", patch: dict) -> None:
    """Applique un patch d'une branche renvoi_vers sur la feuille atteinte.

    Aujourd'hui : remap des codes de prescription par valeur
    (`patch['code_prescription'] = {pc12: pc14}`). On ne touche que si la
    feuille porte un code present dans le mapping ; les autres restent intacts.
    """
    remap = (patch or {}).get("code_prescription") or {}
    if remap and res.codes_prescription:
        res.codes_prescription = [remap.get(cp, cp) for cp in res.codes_prescription]


def _collecter_questions(
    noeud_formulaire: dict,
    contexte: dict[str, Any],
    index_ids: dict[str, dict],
    resoudre_catalogue=None,
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
                _collecter_aval_si_chemin_unique(
                    branche, contexte, questions, index_ids, resoudre_catalogue
                )
                break
    else:
        # Cas standard : on explore toutes les sous-branches du noeud
        # bloquant pour proposer les questions conditionnelles en cascade.
        for branche in noeud_formulaire.get("branches", []):
            _collecter_aval_conditionnel(
                branche,
                contexte,
                questions,
                index_ids,
                resoudre_catalogue,
                parent_champ=noeud_formulaire["champ"],
                parent_valeur=branche.get("valeur"),
            )

    return questions


def _resoudre_renvoi(
    branche: dict, index_ids: dict[str, dict], visites: set[str] | None = None
) -> dict | None:
    """Si la branche est un `renvoi_vers` pointant vers un noeud traversable
    (formulaire / catalogue / catalogue_parametre), retourne ce noeud pour
    poursuivre la collecte des QC dedans. Retourne None sinon (branche normale,
    renvoi vers une regle terminale, ou id introuvable) : le prefetch QC
    n'a rien a collecter au-dela d'une feuille.

    `visites` : garde-fou anti-cycle. La collecte suit les `renvoi_vers` de
    facon recursive ; un renvoi cyclique dans le YAML (A -> B -> A) provoquerait
    sinon une recursion infinie. On memorise les cibles deja traversees et on
    coupe (retourne None) si on retombe dessus. Les arbres actuels n'ont aucun
    cycle, c'est une securite pour un futur editeur d'arbre."""
    cible_id = branche.get("renvoi_vers")
    if not cible_id:
        return None
    if visites is not None and cible_id in visites:
        return None
    cible = index_ids.get(cible_id)
    if cible and cible.get("type_noeud") in (
        "formulaire",
        "catalogue",
        "catalogue_parametre",
    ):
        if visites is not None:
            visites.add(cible_id)
        return cible
    return None


def _valeur_catalogue(noeud: dict, contexte: dict[str, Any], resoudre_catalogue):
    """Valeur d'un noeud catalogue (SIG) pour la collecte QC.

    On lit d'abord le contexte (catalogue deja resolu par un tour precedent ou
    par la moulinette). Si absente ET qu'un `resoudre_catalogue` est fourni, on
    resout le noeud A LA VOLEE (via code_insee/geo) et on ecrit la valeur dans le
    contexte -> le sous-arbre s'aplatit : tout noeud SIG intercale entre deux QC
    devient transparent, quel que soit l'arbre (cf. #187). Les SIG etant
    geo-deterministes (fixes des le chargement, independants des reponses QC),
    cette resolution anticipee ne change aucun routage : elle le devance juste.

    Retourne None si irresolvable (pas de callback, dataset absent) -> la
    collecte s'arrete proprement sur ce noeud (fallback submit)."""
    valeur = contexte.get(noeud["champ"])
    if valeur is not None:
        return valeur
    if resoudre_catalogue is None:
        return None
    try:
        valeur = resoudre_catalogue(noeud)
    except Exception:
        return None
    if valeur is None:
        return None
    contexte[noeud["champ"]] = valeur
    return valeur


def _collecter_aval_si_chemin_unique(
    branche: dict,
    contexte: dict[str, Any],
    questions: list[QuestionFormulaire],
    index_ids: dict[str, dict],
    resoudre_catalogue=None,
    _visites_renvoi: set[str] | None = None,
) -> None:
    """Suit la branche en cours et collecte les noeuds formulaire en aval
    tant qu'on peut identifier le chemin (valeurs presentes dans le
    contexte ou catalogue resolu)."""
    if _visites_renvoi is None:
        _visites_renvoi = set()
    # Branche `renvoi_vers` : sous-arbre reutilisable (cf. _descendre_branche).
    # On resout la cible et on continue la collecte dedans, sinon la QC en aval
    # d'un renvoi n'est jamais prefetchee. `_visites_renvoi` coupe les cycles.
    cible = _resoudre_renvoi(branche, index_ids, _visites_renvoi)
    if cible is not None:
        _collecter_aval_si_chemin_unique(
            {"noeud": cible},
            contexte,
            questions,
            index_ids,
            resoudre_catalogue,
            _visites_renvoi,
        )
        return
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
                _collecter_aval_si_chemin_unique(
                    sb,
                    contexte,
                    questions,
                    index_ids,
                    resoudre_catalogue,
                    _visites_renvoi,
                )
                break
        return

    if type_noeud == "catalogue":
        # Catalogue SIG : pas de question utilisateur. On resout (contexte ou
        # callback SIG) pour le rendre transparent et continuer vers la QC aval.
        valeur = _valeur_catalogue(sous, contexte, resoudre_catalogue)
        if valeur is None:
            return
        for sb in sous.get("branches", []):
            if _valeurs_egales(sb.get("valeur"), valeur):
                _collecter_aval_si_chemin_unique(
                    sb,
                    contexte,
                    questions,
                    index_ids,
                    resoudre_catalogue,
                    _visites_renvoi,
                )
                break
        return

    if type_noeud == "catalogue_parametre":
        # Catalogue parametre : pas de question utilisateur, mais on doit le
        # TRAVERSER pour atteindre les questions en aval (sinon le batch
        # s'arrete net et le front rejoue un aller-retour). Le branchement se
        # fait par expression (premiere vraie l'emporte), comme dans le
        # parcours reel.
        for sb in sous.get("branches", []):
            if evaluer_expression(sb.get("expression"), contexte):
                _collecter_aval_si_chemin_unique(
                    sb,
                    contexte,
                    questions,
                    index_ids,
                    resoudre_catalogue,
                    _visites_renvoi,
                )
                break


def _collecter_aval_conditionnel(
    branche: dict,
    contexte: dict[str, Any],
    questions: list[QuestionFormulaire],
    index_ids: dict[str, dict],
    resoudre_catalogue=None,
    parent_champ: str = None,
    parent_valeur: Any = None,
    _visites_renvoi: set[str] | None = None,
) -> None:
    """Comme `_collecter_aval_si_chemin_unique` mais pour le cas "1re
    question pas encore repondue" : on remonte les questions formulaire
    rencontrees en les annotant avec leur dependance au parent.

    Le front cachera les questions tant que `parent_champ` ne vaut pas
    `parent_valeur` cote utilisateur, et les revelera au clic. Aucun
    aller-retour serveur intermediaire necessaire.

    Si la sous-question est DEJA repondue dans le contexte (typiquement
    via un pre-fill cascade.js -> mapping_sous_culture_vers_branche.flags,
    cf. culture_irriguee_type=mais quand on a clique 'Mais' en sous-culture),
    on ne la propose pas : c'est de la redondance UX.

    Les noeuds catalogue (SIG) et catalogue_parametre intermediaires sont
    TRAVERSES (pas listes : ils ne posent pas de question a l'utilisateur)
    pour atteindre la QC descendante (bug #187). Le catalogue SIG est resolu a
    la volee via `resoudre_catalogue` (geo-deterministe) pour rendre le noeud
    transparent. On garde l'annotation `parent_champ`/`parent_valeur` d'origine :
    la QC en aval reste conditionnelle a la reponse de la QC parente, quel que
    soit le nombre de noeuds traverses entre les deux. On ne descend en revanche
    pas au-dela de la 1re sous-question formulaire (les cascades a 2 niveaux de
    QC sont rares et alourdiraient le rendu)."""
    if _visites_renvoi is None:
        _visites_renvoi = set()
    # Branche `renvoi_vers` : on resout la cible (sous-arbre reutilisable) et on
    # poursuit dedans, en conservant l'annotation parent. `_visites_renvoi`
    # coupe les cycles.
    cible = _resoudre_renvoi(branche, index_ids, _visites_renvoi)
    if cible is not None:
        _collecter_aval_conditionnel(
            {"noeud": cible},
            contexte,
            questions,
            index_ids,
            resoudre_catalogue,
            parent_champ,
            parent_valeur,
            _visites_renvoi,
        )
        return
    if "noeud" not in branche:
        return
    sous = branche["noeud"]
    type_noeud = sous.get("type_noeud")

    if type_noeud == "catalogue":
        # Catalogue SIG : resolu par la moulinette, pas par l'utilisateur. On le
        # resout (contexte ou callback SIG geo-deterministe) pour le rendre
        # transparent et suivre la bonne branche vers la QC aval. Sinon (pas de
        # callback / irresolvable) on s'arrete : fallback submit.
        valeur = _valeur_catalogue(sous, contexte, resoudre_catalogue)
        if valeur is None:
            return
        for sb in sous.get("branches", []):
            if _valeurs_egales(sb.get("valeur"), valeur):
                _collecter_aval_conditionnel(
                    sb,
                    contexte,
                    questions,
                    index_ids,
                    resoudre_catalogue,
                    parent_champ,
                    parent_valeur,
                    _visites_renvoi,
                )
                break
        return

    if type_noeud == "catalogue_parametre":
        # Catalogue parametre : branche choisie par expression (premiere vraie),
        # comme dans le parcours reel. Pas de question, on traverse.
        for sb in sous.get("branches", []):
            if evaluer_expression(sb.get("expression"), contexte):
                _collecter_aval_conditionnel(
                    sb,
                    contexte,
                    questions,
                    index_ids,
                    resoudre_catalogue,
                    parent_champ,
                    parent_valeur,
                    _visites_renvoi,
                )
                break
        return

    if type_noeud != "formulaire":
        return
    # Skip si la sous-question est deja resolue par le contexte (pre-fill).
    if contexte.get(sous["champ"]) is not None:
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
    # Regles hors-arbre referencables par renvoi_vers : plafonnements et
    # regles partagees (ex: r_cie_courte_types_0_I_II, atteint depuis les
    # branches type_0/I/II du couvert courte). Sans ca, le parcours leve
    # ParcoursError sur ces feuilles.
    for cle in ("plafonnements", "regles_partagees"):
        for entry in arbre.get(cle, []) or []:
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
    arbre: dict, contexte: dict[str, Any], resoudre_catalogue=None
) -> list[QuestionFormulaire]:
    """Retourne TOUTES les questions complementaires (niveau formulaire =
    'complement') qui se trouvent sur le chemin actuel d'apres `contexte`,
    qu'elles soient deja repondues ou pas.

    Sert au rendu du panneau gauche : on doit reafficher chaque QC en cours
    avec ses choix REELS issus de l'arbre (pas une table hardcodee), y compris
    pour les QC en aval qui n'ont pas encore ete repondues.

    `resoudre_catalogue` : meme callback qu'`parcours()` -> les noeuds catalogue
    SIG intercales sont resolus a la volee (geo-deterministe) pour ne pas
    bloquer la descente (cf. #187).
    """
    qc: list[QuestionFormulaire] = []
    racine = arbre.get("arbre", {}).get("noeud")
    if not racine:
        return qc
    index_ids = _build_id_index(arbre)
    _suivre_chemin_pour_qc(
        racine,
        contexte,
        index_ids,
        qc,
        visites=set(),
        resoudre_catalogue=resoudre_catalogue,
    )
    return qc


def _suivre_chemin_pour_qc(
    noeud: dict,
    contexte: dict[str, Any],
    index_ids: dict[str, dict],
    qc: list[QuestionFormulaire],
    visites: set[str],
    resoudre_catalogue=None,
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

    # Noeud catalogue parametre : pas une QC (aucune question posee). On suit
    # la branche dont l'expression est vraie pour continuer a collecter les QC
    # en aval, sans rien ajouter ici.
    if type_noeud == "catalogue_parametre":
        for branche in noeud.get("branches", []):
            if evaluer_expression(branche.get("expression"), contexte):
                if "noeud" in branche:
                    _suivre_chemin_pour_qc(
                        branche["noeud"],
                        contexte,
                        index_ids,
                        qc,
                        visites,
                        resoudre_catalogue,
                    )
                elif "renvoi_vers" in branche:
                    cible = index_ids.get(branche["renvoi_vers"])
                    if cible and cible.get("type_noeud") in (
                        "formulaire",
                        "catalogue",
                        "catalogue_parametre",
                    ):
                        _suivre_chemin_pour_qc(
                            cible,
                            contexte,
                            index_ids,
                            qc,
                            visites,
                            resoudre_catalogue,
                        )
                return
        return

    # QC = formulaire de niveau complement. On les collecte (repondues ou pas).
    if type_noeud == "formulaire" and noeud.get("niveau") == "complement":
        _ajouter_question(qc, noeud)

    # Noeud catalogue SIG : resolu a la volee (contexte ou callback) pour ne pas
    # bloquer la descente vers les QC en aval.
    if type_noeud == "catalogue":
        valeur = _valeur_catalogue(noeud, contexte, resoudre_catalogue)
    else:
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
        _suivre_chemin_pour_qc(
            branche["noeud"], contexte, index_ids, qc, visites, resoudre_catalogue
        )
    elif "renvoi_vers" in branche:
        cible = index_ids.get(branche["renvoi_vers"])
        if cible and cible.get("type_noeud") in (
            "formulaire",
            "catalogue",
            "catalogue_parametre",
        ):
            _suivre_chemin_pour_qc(
                cible, contexte, index_ids, qc, visites, resoudre_catalogue
            )


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
