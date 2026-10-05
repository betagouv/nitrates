"""Couleurs d'affichage des zones sur la carte du simulateur.

Jusqu'ici la couleur de chaque bassin ZV était codée en dur dans le JS
(home.js, simulator.js). On la rattache désormais à une clé de zone,
éditable dans l'admin, sans redéploiement.

La clé est le code de bassin DCE (`CdEuBassin`) et non l'id de la Zone :
l'import d'un nouveau millésime recrée ou réécrit les zones, alors que le
code bassin, lui, est stable. Plusieurs codes peuvent partager une même
couleur (ex. Artois-Picardie Escaut FRA et Sambre FRB2, qui forment un
seul bassin pour les utilisateurs).

La clé `*` sert de couleur par défaut pour un type de carte : toute zone
dont le code n'a pas de ligne dédiée la prend.
"""

from django.core.validators import RegexValidator
from django.db import models

from envergo.geodata.models import MAP_TYPES

CLE_DEFAUT = "*"

# Sous-ensemble des MAP_TYPES affichés en couche colorée sur le simulateur.
# Liste locale plutôt que MAP_TYPES entier : une évolution des types côté
# geodata n'a pas à générer de migration ici.
TYPES_CARTE = [
    (MAP_TYPES.zv_nitrates, "Zones vulnérables nitrates"),
    (MAP_TYPES.zone_action_renforcee, "Zones d'action renforcée"),
]

valider_couleur = RegexValidator(
    r"^#[0-9a-fA-F]{6}$", "Couleur hexadécimale attendue, ex. #00b0ff."
)


class CouleurZone(models.Model):
    map_type = models.CharField(
        "Type de carte",
        max_length=50,
        choices=TYPES_CARTE,
        default=MAP_TYPES.zv_nitrates,
    )
    cle = models.CharField(
        "Clé de zone",
        max_length=20,
        help_text=(
            "Code bassin DCE de la zone (ex. FRA, FRB1-FRC). "
            "« * » = couleur par défaut de ce type de carte."
        ),
    )
    libelle = models.CharField(
        "Libellé",
        max_length=100,
        blank=True,
        help_text="Pour l'admin uniquement : le nom affiché vient de la zone.",
    )
    couleur = models.CharField(
        "Couleur", max_length=7, validators=[valider_couleur], help_text="#rrggbb"
    )

    class Meta:
        verbose_name = "Couleur de zone (carte)"
        verbose_name_plural = "Couleurs de zones (carte)"
        ordering = ("map_type", "cle")
        constraints = [
            models.UniqueConstraint(
                fields=("map_type", "cle"), name="couleur_zone_unique_par_cle"
            )
        ]

    def __str__(self):
        return f"{self.cle} {self.couleur}"


def couleurs_par_cle(map_type):
    """{cle: couleur} pour un type de carte, injecté tel quel dans le JS."""
    return dict(
        CouleurZone.objects.filter(map_type=map_type).values_list("cle", "couleur")
    )
