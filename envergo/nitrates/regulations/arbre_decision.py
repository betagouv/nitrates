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
    load_active_tree,
    parcours,
)
from envergo.nitrates.zonage_montagne import (
    est_zone_montagne_d113_14,
    zonage_montagne_pour_commune,
)
from envergo.nitrates.zonage_note_5 import zone_note_5_pour_commune

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
}

# Reference YAML zone_note_5 : zone Sud-Ouest (PACA, Occitanie, depts
# 24/33/40/47/64) definie geographiquement par codes INSEE region/dept.
# Resolution sans PostGIS via le code INSEE de la commune (cf.
# envergo.nitrates.zonage_note_5). Retourne un bool, l'arbre branche
# sur valeur: true / false.
REFERENCES_ZONE_NOTE_5 = {"zone_note_5"}

# References YAML resolues via le mapping commune INSEE -> zone
# montagne (cf. envergo.nitrates.zonage_montagne). Elles partagent la
# meme semantique (montagne_note_7 / montagne_note_6 / non_montagne)
# et sont resolues sans PostGIS, juste sur le code INSEE pousse par
# le front.
#
# `zonage_prairie_III` -> noeud catalogue prairie+6 type_III dans
#   l'arbre PAN (2 ou 3 valeurs selon version : note_7 / note_6 /
#   non_montagne).
# `zone_note_7_vs_note_6` (renommee 30/04) -> noeud catalogue
#   imbrique apres un 1er catalogue zone montagne D113-14 : tranche
#   entre note_7 et note_6 quand on sait deja qu'on est en montagne.
# `zone_note_7_montagne` -> ancien nom (compatibilite descendante).
REFERENCES_ZONE_MONTAGNE = {
    "zonage_prairie_III",
    "zone_note_7_vs_note_6",
    "zone_note_7_montagne",
}

# `zone_montagne_d113_14` -> noeud catalogue qui branche sur bool
# (true/false) : la commune est-elle en zone montagne au sens
# D113-14, peu importe la note 6 vs 7. Resolution sur le code INSEE
# via le CSV juriste (cf. zonage_montagne._mapping).
REFERENCES_ZONE_MONTAGNE_BOOL = {"zone_montagne_d113_14"}

# Champs du form principal lus depuis le catalog (ceux passes par le form
# Django valide). Les questions subsidiaires (effluent_peu_charge,
# fertirrigation, culture_irriguee, plan_epandage, fertilisant_iaa, etc.)
# sont lues directement depuis form_kwargs["data"] (request.GET brut)
# parce que l'ensemble des champs possibles est dicte par l'arbre YAML --
# on ne veut pas les declarer un par un dans MoulinetteFormNitrates.
# categorie_fertilisant est exclu du contexte parcours : c'est de la
# tracabilite front, l'arbre ne s'en sert pas (le mapping vers
# type_fertilisant est deja resolu cote client via referentiels.yaml).
CHAMPS_CATALOG = (
    "occupation_sol",
    "sous_culture",
    "type_fertilisant",
    "sous_fertilisant",
)
# Champs explicitement exclus du contexte parcours (ils ne sont jamais
# utilises comme `champ` de noeud dans l'arbre, juste comme tracabilite
# front ou meta).
CHAMPS_EXCLUS_CONTEXTE = {
    "lat",
    "lng",
    "code_insee",  # utilise pour resoudre la zone montagne, pas un champ d'arbre
    "categorie_fertilisant",
    "leaflet-base-layers_64",  # parametre Leaflet leftover, non metier
}

# Garde-fou contre une boucle infinie de resolutions catalogue (un arbre
# normal n'a pas plus de quelques noeuds catalogue empiles).
MAX_ITERATIONS_CATALOGUE = 20

# Sentinelle retournee par _resoudre_catalogue quand on ne sait pas
# resoudre la reference (dataset SIG manquant, source non geree).
_CATALOGUE_NON_RESOLVABLE = object()


class ArbreDecisionEvaluator(CriterionEvaluator):
    slug = "arbre_decision"
    choice_label = "Arbre de decision PAN"

    def evaluate(self):
        arbre = self._load_decision_tree()
        contexte = self._contexte_initial()

        # Boucle catalogue : tant que parcours() bute sur un noeud
        # catalogue interne (genre zone_note_5), on resout via SIG et
        # on relance.
        for _ in range(MAX_ITERATIONS_CATALOGUE):
            res = parcours(arbre, contexte)

            if isinstance(res, BesoinCatalogue):
                resolu = self._resoudre_catalogue(res)
                if resolu is _CATALOGUE_NON_RESOLVABLE:
                    # Dataset SIG manquant pour cette reference. On ne
                    # peut pas continuer : on retourne non_disponible
                    # avec un message debug. Cas typique MVP : zonage
                    # montagne, zone_note_5, etc.
                    self._catalogue_manquant = res
                    self._chemin = res.chemin_partiel
                    self._result_code = RESULTS.non_disponible
                    self._result = RESULTS.non_disponible
                    return
                contexte[res.champ] = resolu
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

    def _load_decision_tree(self) -> dict:
        # Source de verite : la table DecisionTree (un seul actif a la fois).
        # La gestion du PAR R44 viendra plus tard via un champ region_code
        # sur le modele.
        return load_active_tree()

    def _contexte_initial(self) -> dict:
        contexte = {
            "en_zone_vulnerable": self.catalog.get("en_zone_vulnerable", True),
        }
        # 1) Reponses cascade depuis le form principal (catalog : champs
        #    validees par MoulinetteFormNitrates).
        for champ in CHAMPS_CATALOG:
            valeur = self.catalog.get(champ)
            if valeur not in (None, ""):
                contexte[champ] = valeur

        # 2) Toutes les autres reponses subsidiaires viennent directement
        #    de la query string (form_kwargs["data"]). On ne les declare
        #    pas une par une dans le Form Django parce que l'ensemble des
        #    champs possibles est dicte par l'arbre YAML, qui evolue.
        raw_data = self.moulinette.form_kwargs.get("data", {}) or {}
        for cle, valeur in raw_data.items():
            if cle in CHAMPS_EXCLUS_CONTEXTE:
                continue
            if cle in contexte:
                continue
            if valeur in (None, ""):
                continue
            contexte[cle] = valeur

        return contexte

    def _resoudre_catalogue(self, besoin: BesoinCatalogue):
        """Resoud un noeud catalogue via SIG. Retourne la valeur a injecter
        dans le contexte, ou la sentinelle `_CATALOGUE_NON_RESOLVABLE` si
        on ne sait pas resoudre la reference (dataset manquant, source
        non geree).

        L'evaluator detecte la sentinelle et retourne RESULTS.non_disponible
        au lieu de planter ou de retomber sur une valeur qui ne match
        aucune branche."""
        if besoin.source != "sig":
            # source `mapping_referentiel` ou `calcul` : pas dans le scope
            # du MVP, on ne sait pas resoudre.
            return _CATALOGUE_NON_RESOLVABLE

        # Resolution speciale pour la zone montagne (D113-14) : on a un
        # mapping commune INSEE -> classification (note_6 / note_7 / non),
        # pas besoin de PostGIS. Le code INSEE est pousse par le front au
        # clic carte (cf. simulator.js).
        if besoin.reference in REFERENCES_ZONE_MONTAGNE:
            raw_data = self.moulinette.form_kwargs.get("data", {}) or {}
            code_insee = raw_data.get("code_insee") or self.catalog.get("code_insee")
            return zonage_montagne_pour_commune(code_insee)

        # Resolution bool pour zone_montagne_d113_14 (oui/non commune
        # en zone montagne au sens D113-14, peu importe la note).
        if besoin.reference in REFERENCES_ZONE_MONTAGNE_BOOL:
            raw_data = self.moulinette.form_kwargs.get("data", {}) or {}
            code_insee = raw_data.get("code_insee") or self.catalog.get("code_insee")
            return est_zone_montagne_d113_14(code_insee)

        # Resolution speciale pour zone_note_5 (Sud-Ouest + PACA/Occitanie) :
        # purement geographique, resolu sur le code INSEE comme la zone
        # montagne mais retourne un bool (l'arbre branche sur true/false).
        if besoin.reference in REFERENCES_ZONE_NOTE_5:
            raw_data = self.moulinette.form_kwargs.get("data", {}) or {}
            code_insee = raw_data.get("code_insee") or self.catalog.get("code_insee")
            return zone_note_5_pour_commune(code_insee)

        map_type = REFERENCE_TO_MAP_TYPE.get(besoin.reference)
        if map_type is None:
            # Reference non mappee : dataset SIG pas encore importe pour
            # cette reference (ex : zone_note_5).
            return _CATALOGUE_NON_RESOLVABLE

        point = self.catalog.get("lng_lat")
        if point is None:
            return _CATALOGUE_NON_RESOLVABLE

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

    @property
    def catalogue_manquant(self):
        """Si le parcours s'est arrete parce qu'un noeud catalogue n'a
        pas pu etre resolu (dataset SIG absent), retourne le
        BesoinCatalogue correspondant. Sinon None."""
        return getattr(self, "_catalogue_manquant", None)
