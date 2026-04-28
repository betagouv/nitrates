"""Formulaires de la moulinette nitrates.

Le formulaire principal demande lat/lng + les 4 reponses cascade
(occupation_sol, sous_culture, type_fertilisant, sous_fertilisant).
Seul lat/lng est strictement requis ; les autres champs sont optionnels
au niveau du formulaire car le parcours d'arbre peut s'arreter avant
d'avoir besoin de tout (cas hors ZV, cas court-circuit sol non cultive,
etc.). Les questions subsidiaires sont gerees au niveau du critere via
le pattern Envergo `additional_forms`.
"""

from django import forms


class MoulinetteFormNitrates(forms.Form):
    """Formulaire principal nitrates : point + reponses cascade.

    Les 4 reponses cascade sont des CharField libres (pas de choices) :
    on s'appuie sur le referentiel YAML cote front pour limiter les
    valeurs possibles. Le serveur valide structurellement l'arbre via
    le parcours -- une valeur invalide leve ParcoursError au niveau
    de l'evaluator."""

    lng = forms.FloatField(min_value=-180, max_value=180)
    lat = forms.FloatField(min_value=-90, max_value=90)

    occupation_sol = forms.CharField(required=False)
    sous_culture = forms.CharField(required=False)
    type_fertilisant = forms.CharField(required=False)
    sous_fertilisant = forms.CharField(required=False)
