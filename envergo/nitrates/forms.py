"""Formulaires de la moulinette nitrates.

Le formulaire principal demande lat/lng + les reponses cascade UX :
  - occupation_sol -> sous_culture (via cascade JS sur l'arbre)
  - categorie_fertilisant -> sous_fertilisant -> type_fertilisant (via
    cascade JS sur referentiels.yaml ; mapping_sous_fertilisant_vers_type
    resolu cote client)

Seul lat/lng est strictement requis ; les autres champs sont optionnels
au niveau du formulaire car le parcours d'arbre peut s'arreter avant
d'avoir besoin de tout (cas hors ZV, cas court-circuit sol non cultive,
etc.).

`categorie_fertilisant` et `sous_fertilisant` sont conserves cote
serveur pour la tracabilite (URL partageable, debug juriste). Le
backend ne fait QUE consommer `type_fertilisant` qui est ce que l'arbre
attend ; cf. mapping resolu cote front.

Les questions complementaires (effluent_peu_charge, fertirrigation,
culture_irriguee, plan_epandage, fertilisant_iaa, ...) sont aussi des
query params, mais lus directement par l'evaluator depuis form_kwargs.
On a vire le pattern `additional_forms` Envergo pour rester sur
l'unique GET partageable.
"""

from django import forms


class MoulinetteFormNitrates(forms.Form):
    """Formulaire principal nitrates : point + reponses cascade.

    Tous les champs hors lat/lng sont des CharField libres (pas de
    choices) : on s'appuie sur le referentiel YAML cote front pour
    limiter les valeurs possibles. Le serveur valide structurellement
    l'arbre via le parcours -- une valeur invalide leve ParcoursError
    au niveau de l'evaluator."""

    lng = forms.FloatField(min_value=-180, max_value=180)
    lat = forms.FloatField(min_value=-90, max_value=90)

    # Cascade culture en 3 niveaux : categorie_culture (UI) ->
    # sous_culture_form (UI, libelle metier) -> occupation_sol +
    # sous_culture (resolus cote front via mapping_sous_culture_vers_branche
    # du referentiel, ce sont les valeurs effectivement matchees par
    # l'arbre).
    categorie_culture = forms.CharField(required=False)
    sous_culture_form = forms.CharField(required=False)
    occupation_sol = forms.CharField(required=False)
    sous_culture = forms.CharField(required=False)

    # Cascade fertilisant : categorie_fertilisant -> sous_fertilisant ;
    # le front resout le mapping sous_fertilisant -> type_fertilisant et
    # nous l'envoie via type_fertilisant.
    categorie_fertilisant = forms.CharField(required=False)
    sous_fertilisant = forms.CharField(required=False)
    type_fertilisant = forms.CharField(required=False)

    # NB : les questions complementaires (effluent_peu_charge, fertirrigation,
    # culture_irriguee, plan_epandage, fertilisant_iaa, ...) ne sont pas
    # declarees ici. L'evaluator les lit directement depuis
    # form_kwargs["data"] (request.GET brut) parce que la liste exacte des
    # champs subsidiaires depend de l'arbre YAML, qui evolue. Cf.
    # ArbreDecisionEvaluator._contexte_initial().
