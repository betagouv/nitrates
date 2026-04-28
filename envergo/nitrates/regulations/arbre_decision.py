"""Critere `arbre_decision` : pilote l'arbre YAML PAN.

Ce critere remplace la mecanique CODE_MATRIX / RESULT_MATRIX d'Envergo
par notre propre arbre de decision YAML : on override `evaluate()` pour
brancher sur `parcours()` au lieu de la table de decision codee en dur.

Cycle :
  1. Charge l'arbre PAN national. (Plus tard : PAR si dispo pour la
     region, sinon PAN.)
  2. Construit le contexte initial : `en_zone_vulnerable` depuis le SIG
     (catalog moulinette) + reponses du form additionnel (champs cascade
     occupation_sol / sous_culture / type_fertilisant / sous_fertilisant
     + reponses subsidiaires).
  3. Appelle `parcours()` en boucle, resolvant les `BesoinCatalogue` au
     fil de l'eau via des requetes PostGIS sur les Map+Zone deja
     importees (zv_nitrates pour l'instant ; les autres references
     n'ont pas encore de dataset, on retourne False par defaut).
  4. Selon ce que retourne `parcours()` :
     - `Resultat`  -> mappe `regle.type` -> RESULTS Envergo, copie les
       infos metier (periodes, plafond, code_prescription, note...)
       sur l'evaluator pour qu'elles soient accessibles depuis le
       template.
     - `QuestionsSubsidiaires` -> RESULTS.non_disponible. Envergo gere
       deja le 2e tour : il appelle `get_form()` pour batir le form
       additionnel, l'utilisateur repond, on rappelle `evaluate()`
       avec le contexte enrichi.
     - `BesoinCatalogue` non resolvable (pas de map disponible) ->
       RESULTS.non_disponible.
"""

from django import forms

from envergo.evaluations.models import RESULTS
from envergo.geodata.models import MAP_TYPES, Zone
from envergo.moulinette.regulations import CriterionEvaluator
from envergo.nitrates.yaml_tree import (
    BesoinCatalogue,
    QuestionsSubsidiaires,
    Resultat,
    load_arbre,
    parcours,
)

# Mapping regle.type (YAML) -> RESULTS Envergo.
TYPE_REGLE_TO_RESULT = {
    "interdiction": RESULTS.interdit,
    "autorisation_sous_condition": RESULTS.action_requise,
    "plafonnement": RESULTS.action_requise,
    "libre": RESULTS.non_soumis,
    "non_applicable": RESULTS.non_concerne,
    # Calculatrice : pour le MVP on traite comme action_requise. C3+ :
    # delegation a un composant qui fera le calcul.
    "calculatrice": RESULTS.action_requise,
    # Stub brouillon (regle a_completer sans type) -> on ne sait pas
    # encore quoi afficher.
    "a_completer": RESULTS.non_disponible,
}

# Mapping noeud.reference (YAML) -> MAP_TYPES Envergo, pour resoudre les
# noeuds catalogue de source `sig`. Les references dont on n'a pas encore
# le dataset retournent False par defaut (et on log un warning).
REFERENCE_TO_MAP_TYPE = {
    "zone_vulnerable_nitrates": MAP_TYPES.zv_nitrates,
    # zone_note_5 : pas encore de dataset, retournera False.
}

# Champs du form principal qui peuvent alimenter le contexte (cf.
# MoulinetteFormNitrates).
CHAMPS_CASCADE = (
    "occupation_sol",
    "sous_culture",
    "type_fertilisant",
    "sous_fertilisant",
)

# Garde-fou contre une boucle infinie de resolutions catalogue (un arbre
# normal n'a pas plus de quelques noeuds catalogue empiles).
MAX_ITERATIONS_CATALOGUE = 20


class ArbreDecisionEvaluator(CriterionEvaluator):
    slug = "arbre_decision"
    choice_label = "Arbre de decision PAN"

    def evaluate(self):
        arbre = self._charger_arbre()
        contexte = self._contexte_initial()

        # Boucle catalogue : tant que parcours() bute sur un noeud
        # catalogue interne (genre zone_note_5), on resout via SIG et
        # on relance.
        for _ in range(MAX_ITERATIONS_CATALOGUE):
            res = parcours(arbre, contexte)

            if isinstance(res, BesoinCatalogue):
                contexte[res.champ] = self._resoudre_catalogue(res)
                continue

            if isinstance(res, QuestionsSubsidiaires):
                self._questions_subsidiaires = res
                self._chemin = res.chemin_partiel
                self._result_code = RESULTS.non_disponible
                self._result = RESULTS.non_disponible
                return

            if isinstance(res, Resultat):
                self._appliquer_resultat(res)
                return

            # Inattendu (parcours() ne retourne que ces 3 dataclasses)
            self._result_code = RESULTS.non_disponible
            self._result = RESULTS.non_disponible
            return

        # Trop de catalogues empiles : on protege contre une boucle.
        self._result_code = RESULTS.non_disponible
        self._result = RESULTS.non_disponible

    # ─── Construction du contexte ──────────────────────────────────────────

    def _charger_arbre(self) -> dict:
        # MVP : toujours PAN national. Plus tard : PAR si dispo pour la
        # region.
        return load_arbre("arbre_decision_national")

    def _contexte_initial(self) -> dict:
        contexte = {
            "en_zone_vulnerable": self.catalog.get("en_zone_vulnerable", True),
        }
        # Reponses cascade depuis le form principal (catalog les contient
        # une fois le form valide).
        for champ in CHAMPS_CASCADE:
            valeur = self.catalog.get(champ)
            if valeur not in (None, ""):
                contexte[champ] = valeur
        return contexte

    def _resoudre_catalogue(self, besoin: BesoinCatalogue):
        """Resoud un noeud catalogue via SIG. Retourne la valeur a injecter
        dans le contexte. Pour les references non mappees ou sans dataset
        on retourne False (interpretation prudente : pas de zone speciale)."""
        if besoin.source != "sig":
            # source `mapping_referentiel` ou `calcul` : pas dans le scope
            # du MVP, on retourne False par defaut.
            return False

        map_type = REFERENCE_TO_MAP_TYPE.get(besoin.reference)
        if map_type is None:
            return False

        point = self.catalog.get("lng_lat")
        if point is None:
            return False

        return Zone.objects.filter(
            map__map_type=map_type, geometry__intersects=point
        ).exists()

    # ─── Application du resultat ───────────────────────────────────────────

    def _appliquer_resultat(self, res: Resultat) -> None:
        """Mappe le Resultat parcours -> RESULTS Envergo et expose les
        infos metier (periodes, plafond, etc.) sur l'evaluator pour le
        template."""
        result = TYPE_REGLE_TO_RESULT.get(res.type, RESULTS.non_disponible)
        # Cas a_completer : meme si le mapping a donne autre chose, on
        # force non_disponible parce qu'on ne veut pas afficher un
        # resultat partiel issu d'un stub brouillon.
        if res.a_completer:
            result = RESULTS.non_disponible

        # result_code = un identifiant unique de la regle, sert a choisir
        # le template a rendre (ex : `r_mais_principal`). result = la
        # categorie standardisee Envergo.
        self._result_code = res.regle_id
        self._result = result

        # Infos metier copiees pour acces template.
        self._regle_yaml = res
        self._chemin = res.chemin

    # ─── Form additionnel (questions subsidiaires) ─────────────────────────

    def get_form(self):
        """Retourne un Form Django dynamique base sur les questions
        subsidiaires renvoyees par parcours() lors du dernier evaluate().

        Le pattern Envergo veut un `form_class` statique, mais nos
        questions varient selon le contexte (chemin dans l'arbre,
        culture choisie...). On le construit a la volee.
        """
        if not getattr(self, "_questions_subsidiaires", None):
            return None
        questions = self._questions_subsidiaires.questions
        if not questions:
            return None

        fields = {}
        for q in questions:
            choices = [
                (c["valeur"], c.get("libelle") or str(c["valeur"])) for c in q.choix
            ]
            fields[q.champ] = forms.ChoiceField(
                label=q.texte,
                choices=choices,
                required=False,
                help_text=q.aide or "",
            )

        form_class = type("ArbreDecisionForm", (forms.Form,), fields)
        return form_class(**self.moulinette.form_kwargs)

    # ─── Accesseurs publics ────────────────────────────────────────────────

    @property
    def regle(self):
        """Le `Resultat` final si on est arrive a une feuille, sinon None."""
        return getattr(self, "_regle_yaml", None)

    @property
    def chemin(self):
        """La trace des noeuds traverses dans l'arbre (pour debug juriste)."""
        return getattr(self, "_chemin", [])

    @property
    def questions_subsidiaires(self):
        """Les questions a poser si on n'a pas encore atteint une feuille."""
        return getattr(self, "_questions_subsidiaires", None)
