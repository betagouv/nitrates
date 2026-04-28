"""Critere `arbre_decision` : pilote l'arbre YAML PAN.

Ce critere remplace la mecanique CODE_MATRIX / RESULT_MATRIX d'Envergo
par notre propre arbre de decision YAML : on override `evaluate()` pour
brancher sur `parcours()` au lieu de la table de decision codee en dur.

Le critere :
  1. charge l'arbre approprie (PAR si dispo pour la region, sinon PAN)
  2. construit le contexte initial (en_zone_vulnerable depuis le SIG +
     reponses du formulaire)
  3. appelle parcours() en boucle, resolvant les BesoinCatalogue au
     fil de l'eau via des requetes PostGIS
  4. mappe le type de regle final vers les RESULTS Envergo

C3a : stub `non_disponible`. La logique reelle arrive en C3b.
"""

from envergo.evaluations.models import RESULTS
from envergo.moulinette.regulations import CriterionEvaluator


class ArbreDecisionEvaluator(CriterionEvaluator):
    slug = "arbre_decision"
    choice_label = "Arbre de decision PAN"

    def evaluate(self):
        # C3a : stub. C3b branchera parcours() ici.
        self._result_code = RESULTS.non_disponible
        self._result = RESULTS.non_disponible
