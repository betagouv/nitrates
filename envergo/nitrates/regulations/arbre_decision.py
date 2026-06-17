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
from envergo.moulinette.regulations import CriterionEvaluator
from envergo.nitrates.models import DecisionTree
from envergo.nitrates.yaml_admin.catalogue_refs import (
    CATALOGUE_NON_RESOLVABLE,
    ResolveContext,
    get_resolver,
)
from envergo.nitrates.yaml_tree import (
    ArbreCandidat,
    BesoinCatalogue,
    ParcoursError,
    QuestionsSubsidiaires,
    RenvoiArbre,
    Resultat,
    candidat_by_id,
    parcours,
    select_active_trees,
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

# Champs du form principal lus depuis le catalog (ceux passes par le form
# Django valide). Les questions subsidiaires (effluent_peu_charge,
# fertirrigation, culture_irriguee, plan_epandage, fertilisant_iaa, etc.)
# sont lues directement depuis form_kwargs["data"] (request.GET brut)
# parce que l'ensemble des champs possibles est dicte par l'arbre YAML --
# on ne veut pas les declarer un par un dans MoulinetteFormNitrates.
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
    "categorie_culture",  # tracabilite front (cf. mapping_sous_culture_vers_branche)
    # sous_culture_form (= identifiant Culture precis, ex 'mais',
    # 'prairie_moins_6_mois_printemps') et categorie_fertilisant (ex 'fumiers',
    # 'digestats') NE sont PLUS exclus : ils portent une distinction fine que
    # les noeuds catalogue_parametre des PAR exploitent par expression Python
    # (sous_culture / type_fertilisant seuls ne suffisent pas a discriminer).
    "leaflet-base-layers_64",  # parametre Leaflet leftover, non metier
    "draft_tree_id",  # preview admin d'un brouillon, route le chargement de l'arbre
}

# Garde-fou contre une boucle infinie de resolutions catalogue (un arbre
# normal n'a pas plus de quelques noeuds catalogue empiles).
MAX_ITERATIONS_CATALOGUE = 20

# Garde-fou contre une boucle de renvois cross-arbre (ZAR -> PAR -> ZAR ...).
# Borne large : en pratique la cascade fait au plus quelques sauts.
MAX_ITERATIONS_CASCADE = 20

# Sentinelle : _evaluer_un_arbre la retourne quand l'arbre courant ne mene a
# aucune feuille (no-match) -> la cascade passe a l'arbre suivant.
_NO_MATCH = object()

# Alias historique : la sentinelle vit maintenant dans `catalogue_refs`
# (cf. CATALOGUE_NON_RESOLVABLE). On expose un alias prive ici pour
# l'identite (`is`) et pour eviter de toucher aux call-sites qui
# l'utilisent en comparaison.
_CATALOGUE_NON_RESOLVABLE = CATALOGUE_NON_RESOLVABLE


class ArbreDecisionEvaluator(CriterionEvaluator):
    slug = "arbre_decision"
    choice_label = "Arbre de decision PAN"

    def evaluate(self):
        arbres = self._load_decision_trees()  # [ArbreCandidat, ...] poids desc
        contexte = self._contexte_initial()
        # On garde une reference sur le contexte pour l'exposer dans le
        # panel debug (utile pour comprendre la resolution complete :
        # quelles valeurs ont ete poussees par le form, quelles ont ete
        # resolues par les noeuds catalogue, etc.).
        self._contexte = contexte

        # Trace de la cascade pour le panel debug : ordre + statut de chaque
        # arbre candidat (selectionne / no-match / renvoi / matche).
        self._candidats = list(arbres)  # liste ArbreCandidat (ordre de poids)
        self._cascade_trace: list[dict] = []
        self._arbre_matche = None  # l'ArbreCandidat qui a produit le resultat

        # CASCADE d'overrides (cf. plan LOT 1b) : les arbres sont tries par
        # poids decroissant [ZAR, PAR, PAN]. On tente le plus specifique
        # ENTIEREMENT ; s'il ne mene a aucune feuille (no-match = override
        # partiel), ou s'il fait un renvoi explicite (renvoi_arbre), on
        # RECOMMENCE le parcours sur l'arbre suivant/cible avec LE MEME contexte
        # cumulatif. Le PAN (couvrant) est le filet final.
        restants = list(arbres)
        par_scope = {a.scope: a for a in arbres}
        dernier_no_match = None

        for _ in range(MAX_ITERATIONS_CASCADE):
            if not restants:
                break
            candidat = restants.pop(0)
            # Memorise l'arbre en cours : c'est lui (et non le PAN par defaut)
            # qui porte les questions subsidiaires / le resultat final. La vue
            # s'en sert pour re-collecter les QC + le lien admin.
            self._arbre_courant = candidat.contenu
            self._arbre_courant_candidat = candidat
            issue = self._evaluer_un_arbre(candidat.contenu, contexte)

            if issue is _NO_MATCH:
                self._cascade_trace.append({"candidat": candidat, "statut": "no-match"})
                dernier_no_match = self._parcours_error
                continue

            if isinstance(issue, RenvoiArbre):
                self._cascade_trace.append(
                    {
                        "candidat": candidat,
                        "statut": f"renvoi -> {issue.scope_cible}",
                    }
                )
                cible = par_scope.get(issue.scope_cible)
                if cible is None:
                    self._parcours_error = (
                        f"renvoi_arbre vers scope '{issue.scope_cible}' : aucun "
                        f"arbre actif de ce scope pour ce point."
                    )
                    self._result_code = RESULTS.non_disponible
                    self._result = RESULTS.non_disponible
                    return
                restants = [a for a in restants if a.scope != issue.scope_cible]
                restants.insert(0, cible)
                continue

            # Statut terminal : resultat / questions / catalogue manquant.
            statut = "matche" if self.regle else "questions/incomplet"
            self._cascade_trace.append({"candidat": candidat, "statut": statut})
            self._arbre_matche = candidat
            return

        # Tous en no-match (PAN inclus = anormal) ou boucle de renvois.
        self._parcours_error = dernier_no_match or "cascade epuisee"
        self._result_code = RESULTS.non_disponible
        self._result = RESULTS.non_disponible

    def _evaluer_un_arbre(self, arbre: dict, contexte: dict):
        """Parcourt UN arbre (avec resolution des catalogues internes).

        Retourne :
          - `_NO_MATCH` si le parcours bute sur un no-match (ParcoursError)
            -> l'appelant tente l'arbre suivant ;
          - un `RenvoiArbre` si l'arbre renvoie explicitement vers un autre
            -> l'appelant bascule sur l'arbre cible ;
          - None si un statut terminal a ete pose sur self (resultat /
            questions subsidiaires / catalogue manquant / boucle).

        Le `contexte` est partage et mute (les valeurs catalogue resolues y
        sont ecrites) -> elles sont reinjectees dans les arbres suivants.
        """
        # Boucle catalogue : tant que parcours() bute sur un noeud catalogue
        # interne (genre zone_note_5), on resout via SIG et on relance.
        for _ in range(MAX_ITERATIONS_CATALOGUE):
            try:
                res = parcours(arbre, contexte)
            except ParcoursError as exc:
                # No-match : la valeur du contexte n'a pas de branche dans CET
                # arbre. Pour un PAR non couvrant, c'est normal -> on signale a
                # l'appelant de passer a l'arbre suivant (override en cascade).
                self._parcours_error = str(exc)
                return _NO_MATCH

            if isinstance(res, RenvoiArbre):
                # Renvoi explicite vers un autre arbre : remonte a la cascade.
                self._chemin = res.chemin_partiel
                return res

            if isinstance(res, BesoinCatalogue):
                resolu = self._resoudre_catalogue(res)
                if resolu is _CATALOGUE_NON_RESOLVABLE:
                    # Dataset SIG manquant pour cette reference. On ne peut pas
                    # continuer : non_disponible avec un message debug. Cas
                    # typique MVP : zonage montagne, zone_note_5, etc.
                    self._catalogue_manquant = res
                    self._chemin = res.chemin_partiel
                    self._result_code = RESULTS.non_disponible
                    self._result = RESULTS.non_disponible
                    return None
                contexte[res.champ] = resolu
                continue

            if isinstance(res, QuestionsSubsidiaires):
                # L'arbre courant a besoin de reponses : il PRIME, on ne tombe
                # PAS sur l'arbre suivant (R3). On batch toutes ses questions.
                self._questions_subsidiaires = res
                self._chemin = res.chemin_partiel
                self._result_code = RESULTS.non_disponible
                self._result = RESULTS.non_disponible
                return None

            if isinstance(res, Resultat):
                self._appliquer_resultat(res)
                return None

            # Inattendu (parcours() ne retourne que ces dataclasses)
            self._result_code = RESULTS.non_disponible
            self._result = RESULTS.non_disponible
            return None

        # Trop de catalogues empiles : on protege contre une boucle.
        self._result_code = RESULTS.non_disponible
        self._result = RESULTS.non_disponible
        return None

    # ─── Construction du contexte ──────────────────────────────────────────

    def _load_decision_trees(self) -> list[ArbreCandidat]:
        """Liste ORDONNEE (poids decroissant) d'ArbreCandidat a tenter en
        cascade.

        Cas preview admin : si `draft_tree_id` est dans le QS, on previsualise
        CE draft SEUL (pas de cascade -- on veut voir ce draft precis). La
        verification d'autorisation est faite cote vue (MoulinetteView) qui
        strip le parametre si l'utilisateur n'a pas le droit.

        Sinon : selection dynamique PAN / PAR / ZAR selon la geo du point. Le
        catalog (region_code, zar_zone_id) a deja ete peuple par
        MoulinetteNitrates.get_catalog_data avant l'evaluation des criteres.
        """
        raw_data = self.moulinette.form_kwargs.get("data", {}) or {}
        draft_id = raw_data.get("draft_tree_id")
        if draft_id:
            try:
                # Preview d'un draft : un seul arbre (pas de cascade en
                # preview), mais sous forme d'ArbreCandidat comme le reste de
                # la cascade (la boucle evaluate() lit .scope/.contenu/.pk).
                return [candidat_by_id(int(draft_id))]
            except (DecisionTree.DoesNotExist, ValueError, TypeError):
                # Draft inexistant : fallback silencieux sur la cascade active.
                pass
        return select_active_trees(self.catalog)

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
        """Resoud un noeud catalogue via le registre `catalogue_refs`.

        Retourne la valeur a injecter dans le contexte, ou la sentinelle
        `CATALOGUE_NON_RESOLVABLE` si on ne sait pas resoudre la
        reference (resolveur absent, dataset SIG manquant, source non
        geree). L'evaluator bascule alors en RESULTS.non_disponible.
        """
        if besoin.source != "sig":
            # source `mapping_referentiel` ou `calcul` : pas dans le scope
            # du MVP, on ne sait pas resoudre.
            return _CATALOGUE_NON_RESOLVABLE

        resolver = get_resolver(besoin.reference)
        if resolver is None:
            return _CATALOGUE_NON_RESOLVABLE

        raw_data = self.moulinette.form_kwargs.get("data", {}) or {}
        ctx = ResolveContext(
            code_insee=raw_data.get("code_insee") or self.catalog.get("code_insee"),
            lng_lat=self.catalog.get("lng_lat"),
        )
        return resolver.resolve(ctx)

    # ─── Application du resultat ───────────────────────────────────────────

    def _appliquer_resultat(self, res: Resultat) -> None:
        """Mappe le Resultat parcours -> RESULTS Envergo et expose les
        infos metier (periodes, plafond, etc.) sur l'evaluator pour le
        template."""
        result = TYPE_REGLE_TO_RESULT.get(res.type, RESULTS.non_disponible)
        # Cas mixte : on resout sur le regime le plus restrictif trouve dans
        # les periodes (interdiction > plafonnement > autorisation_sous_condition
        # > libre). Coherent avec l'affichage : si une periode interdit, le
        # statut global doit le reporter.
        if res.type == "mixte":
            severite = {
                "interdiction": 0,
                "plafonnement": 1,
                "autorisation_sous_condition": 2,
                "libre": 3,
            }
            periodes = res.periodes or []
            regimes = [p.get("regime") for p in periodes if p.get("regime")]
            if regimes:
                pire = min(regimes, key=lambda r: severite.get(r, 99))
                result = TYPE_REGLE_TO_RESULT.get(pire, RESULTS.non_disponible)
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
    def arbre_courant(self):
        """L'arbre (contenu) REELLEMENT utilise par la cascade (peut etre un
        PAR/ZAR, pas le PAN). La vue s'en sert pour re-collecter les questions
        complementaires du bon arbre (sinon le PAN n'a pas les QC du ZAR)."""
        return getattr(self, "_arbre_courant", None)

    @property
    def arbre_matche(self):
        """L'ArbreCandidat (pk/name/scope) qui a effectivement produit le
        resultat ou les questions. Sert au lien admin (cible le bon arbre) et au
        debug. None si la cascade n'a rien produit."""
        return getattr(self, "_arbre_matche", None) or getattr(
            self, "_arbre_courant_candidat", None
        )

    @property
    def candidats(self):
        """Liste ordonnee (poids desc) des ArbreCandidat actives pour ce point."""
        return getattr(self, "_candidats", [])

    @property
    def cascade_trace(self):
        """Trace de la cascade : [{candidat, statut}] (selectionne -> no-match /
        renvoi / matche). Pour le panel debug resultat."""
        return getattr(self, "_cascade_trace", [])

    @property
    def catalogue_manquant(self):
        """Si le parcours s'est arrete parce qu'un noeud catalogue n'a
        pas pu etre resolu (dataset SIG absent), retourne le
        BesoinCatalogue correspondant. Sinon None."""
        return getattr(self, "_catalogue_manquant", None)

    @property
    def contexte(self):
        """Etat final du contexte de parcours : tous les champs poussés
        par le form principal + les valeurs resolues par les noeuds
        catalogue (en_zone_vulnerable, zone_note_5, zone_montagne_*,
        etc.). Utilise pour le panel debug."""
        return getattr(self, "_contexte", {})
