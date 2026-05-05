"""Regulation `directive_nitrates` : transposition francaise de la
directive europeenne 91/676/CEE.

Pour le MVP on a un seul critere (`arbre_decision`) qui couvre les periodes
d'epandage (mesure 1 du PAN 7). Plus tard d'autres criteres viendront
(stockage, equilibre azote, ZAR, mesures 2-8 du PAN, etc.).

La RegulationEvaluator par defaut d'Envergo fait deja la cascade (le critere
le plus restrictif gagne) -- comme on a un seul critere pour l'instant, ca
passera direct.
"""

from envergo.moulinette.regulations import RegulationEvaluator


class DirectiveNitratesEvaluator(RegulationEvaluator):
    """Cascade par defaut. Pas de logique custom pour le MVP."""

    choice_label = "Directive nitrates"
