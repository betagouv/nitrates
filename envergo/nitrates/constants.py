"""Constantes figées par l'arrêté nitrates : types réglementaires,
catégories de fertilisants, statuts ICPE, régions INSEE.

Ces listes ne sont PAS éditables par les juristes via l'admin : elles
sont definies par la réglementation nationale. Un changement = une mise
à jour de code.

Pour les listes éditables (cultures, fertilisants précis, codes de
prescription, notes, événements phénologiques), voir
`envergo/nitrates/models_referentiels.py`.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class TypeFertilisant(models.TextChoices):
    """Types réglementaires PAN (Plan d'Action National nitrates).

    TYPE_I est une valeur SPÉCIALE réservée aux branches d'arbre de
    décision : elle représente le regroupement type_Ia ∪ type_Ib quand
    le PAN ne distingue pas. Aucun Fertilisant en DB ne doit porter
    cette valeur — CheckConstraint en garde.
    """

    TYPE_0 = "type_0", _("Type 0")
    TYPE_IA = "type_Ia", _("Type Ia")
    TYPE_IB = "type_Ib", _("Type Ib")
    TYPE_I = "type_I", _("Type I (Ia ou Ib non distingué — usage arbre uniquement)")
    TYPE_II = "type_II", _("Type II")
    TYPE_III = "type_III", _("Type III")


class OccupationSol(models.TextChoices):
    """Occupation du sol — niveau 1 de l'arbre de décision."""

    CULTURE_PRINCIPALE = "culture_principale", _("Culture principale")
    COUVERT_INTERCULTURES = "couvert_intercultures", _("Couvert végétal d'interculture")
    PRAIRIE = "prairie", _("Prairie")
    SOL_NON_CULTIVE = "sol_non_cultive", _("Sol non cultivé")


class StatutICPE(models.TextChoices):
    """Statut ICPE de l'installation d'élevage / plan d'épandage."""

    NON_CONCERNE = "non_concerne", _("Pas concerné par un plan d'épandage")
    ICPE_A = "icpe_a", _("Soumis à autorisation (ICPE A)")
    ICPE_E = "icpe_e", _("Soumis à enregistrement (ICPE E)")
    ICPE_D = "icpe_d", _("Soumis à déclaration (ICPE D)")


class CategorieFertilisant(models.TextChoices):
    """Catégorie utilisateur de fertilisant (niveau 1 cascade form).

    Figée par l'arrêté nitrates : ces 7 catégories ne changent pas.
    """

    FUMIERS = "fumiers", _("Fumiers")
    LISIERS = "lisiers", _("Lisiers")
    COMPOSTS = "composts", _("Composts")
    DIGESTATS = "digestats", _("Digestats")
    ENGRAIS_MINERAL = "engrais_mineral", _("Engrais minéral")
    BOUES = "boues", _("Boues")
    AUTRE = "autre", _("Autre")


# Régions INSEE métropole — codes figés, dict en code suffit.
REGIONS_FR = {
    "R11": "Île-de-France",
    "R24": "Centre-Val de Loire",
    "R27": "Bourgogne-Franche-Comté",
    "R28": "Normandie",
    "R32": "Hauts-de-France",
    "R44": "Grand Est",
    "R52": "Pays de la Loire",
    "R53": "Bretagne",
    "R75": "Nouvelle-Aquitaine",
    "R76": "Occitanie",
    "R84": "Auvergne-Rhône-Alpes",
    "R93": "Provence-Alpes-Côte d'Azur",
    "R94": "Corse",
}
