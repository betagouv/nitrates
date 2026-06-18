"""Pilotage géographique de l'ouverture du simulateur (carte #57).

Le simulateur nitrates est déployé région par région. Ce modèle pilote,
par **département**, si le simulateur est ouvert (formulaire affiché) ou
fermé (message « pas encore ouvert »).

Granularité : département (regroupé par région à l'affichage admin). Une
région est « ouverte » au sens où certains de ses départements le sont ;
on peut ouvrir/fermer chaque département indépendamment.

Politique : **fermé par défaut** (allowlist). Un département absent de la
table OU présent avec est_ouvert=False est fermé. Seuls les départements
explicitement `est_ouvert=True` laissent passer vers le formulaire.

Le seed initial (migration data) ouvre uniquement le Grand Est (R44).
"""

from django.db import models


class DepartementOuverture(models.Model):
    """Statut d'ouverture du simulateur pour un département.

    Une ligne par département français (métropole + Corse + DROM). Le
    `region_code` / `region_label` sont dénormalisés pour l'affichage admin
    (regroupement par région) sans jointure.
    """

    code = models.CharField(
        max_length=3,
        unique=True,
        help_text="Code département INSEE (ex: '57', '2A', '971').",
    )
    nom = models.CharField(max_length=100, blank=True)
    region_code = models.CharField(max_length=2, blank=True)
    region_label = models.CharField(max_length=100, blank=True)
    est_ouvert = models.BooleanField(
        default=False,
        help_text=(
            "Si vrai, le simulateur affiche le formulaire pour une parcelle "
            "de ce département. Sinon, message « pas encore ouvert ». "
            "Fermé par défaut (allowlist)."
        ),
    )
    ordre_affichage = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("region_label", "code")
        verbose_name = "Ouverture département"
        verbose_name_plural = "Ouverture départements"

    def __str__(self):
        etat = "ouvert" if self.est_ouvert else "fermé"
        return f"{self.code} {self.nom} ({etat})"


def departement_est_ouvert(code: str | None) -> bool:
    """True si le simulateur est ouvert pour ce département.

    Politique allowlist : fermé par défaut. Un code None / inconnu / non
    configuré / configuré à est_ouvert=False renvoie False. Seul un
    département explicitement ouvert en base renvoie True.
    """
    if not code:
        return False
    return DepartementOuverture.objects.filter(code=code, est_ouvert=True).exists()
