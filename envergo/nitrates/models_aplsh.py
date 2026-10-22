"""Référentiels APLSH régionaux (POC calculette APLSH).

Un `ReferentielAPLSH` par région : les méta-paramètres (plafond par
défaut, bornes de saison, source réglementaire) + les tableaux de valeurs
sous forme TEXTE pipe-séparé, éditables tels quels dans l'admin et parsés
/ validés à la sauvegarde (`clean()`), notamment contre la nomenclature
`Fertilisant` — impossible d'enregistrer une ligne dont le fertilisant
n'existe pas dans notre référentiel. La version parsée est cachée en JSON
pour le runtime (pas de re-parse à chaque requête).

Sources transcrites (voir ~/Data/betagouv/specs/APLSH/) :
  - Grand Est : arrêté GREN modificatif n° 2025/612 du 10/12/2025
  - Hauts-de-France : arrêté GREN du 22/07/2025, annexe n° 14
"""

from django.core.exceptions import ValidationError
from django.db import models

from envergo.nitrates.aplsh import (
    ErreurTableauAPLSH,
    parser_jour_mois,
    parser_tableau_generique,
    parser_tableau_produits,
)
from envergo.nitrates.models_referentiels import REGION_CODE_CHOICES, Fertilisant


class ReferentielAPLSH(models.Model):
    """Paramètres et valeurs APLSH d'une région (déclinaison GREN)."""

    region_code = models.CharField(
        max_length=3,
        choices=REGION_CODE_CHOICES,
        unique=True,
        verbose_name="Région",
    )
    intitule = models.CharField(
        max_length=255,
        verbose_name="Intitulé",
        help_text="Ex : « GREN Grand Est — arrêté modificatif du 10/12/2025 ».",
    )
    source = models.CharField(
        max_length=500,
        blank=True,
        help_text="Référence / URL de l'arrêté GREN source.",
    )
    actif = models.BooleanField(
        default=True,
        help_text="Référentiel utilisé par la calculette pour cette région.",
    )
    plafond_defaut_kg_n_ha = models.FloatField(
        default=70,
        verbose_name="Plafond APLSH par défaut (kg N/ha)",
        help_text="Plafond général de la mesure 1 du PAN (70 kg N/ha).",
    )
    fin_apports_ete = models.CharField(
        max_length=5,
        default="15/09",
        verbose_name="Fin des apports d'été (JJ/MM)",
        help_text=(
            "Dernier jour de la période « apports d'été » pour le tableau "
            "produits (GE : 15/09, HdF : 31/08). Au-delà : coefficients "
            "d'automne."
        ),
    )
    fin_apports_ete_generique = models.CharField(
        max_length=5,
        blank=True,
        verbose_name="Fin des apports d'été — grille générique (JJ/MM)",
        help_text=(
            "Borne propre à la grille générique si différente (GE : 30/09). "
            "Vide = même borne que le tableau produits."
        ),
    )
    tableau_produits = models.TextField(
        verbose_name="Tableau produits",
        help_text=(
            "Une ligne par produit : fertilisant | variante | unite | "
            "n_total | p_ete | p_automne. `fertilisant` = identifiant d'un Fertilisant "
            "existant ; `variante` = précision régionale (vide si 1-1) ; "
            "`unite` = t ou m3 (vide si inconnu) ; `n_total` en kg N par "
            "unité (vide si non fourni par le GREN) ; "
            "coefficients en 0,40 ou 40%. Lignes # = commentaires."
        ),
    )
    tableau_generique = models.TextField(
        blank=True,
        verbose_name="Grille générique C/N × Nmin/Ntot",
        help_text=(
            "Optionnelle (produits hors liste, caractérisés par analyse). "
            "Colonnes : cn_max | nmin_ntot_max | p_ete | p_automne, tranches "
            "par bornes max croissantes, borne vide = pas de limite."
        ),
    )
    notes = models.TextField(
        blank=True,
        help_text="Notes internes (choix de mapping, points à confirmer…).",
    )
    tableau_produits_parse = models.JSONField(editable=False, default=list)
    tableau_generique_parse = models.JSONField(editable=False, default=list)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Référentiel APLSH"
        verbose_name_plural = "Référentiels APLSH"
        ordering = ("region_code",)

    def __str__(self):
        return self.intitule or f"Référentiel APLSH {self.region_code}"

    def clean(self):
        erreurs = {}
        for champ in ("fin_apports_ete", "fin_apports_ete_generique"):
            valeur = getattr(self, champ)
            if valeur:
                try:
                    parser_jour_mois(valeur)
                except ErreurTableauAPLSH as e:
                    erreurs[champ] = str(e)
        identifiants = set(Fertilisant.objects.values_list("identifiant", flat=True))
        try:
            self.tableau_produits_parse = parser_tableau_produits(
                self.tableau_produits or "", identifiants
            )
        except ErreurTableauAPLSH as e:
            erreurs["tableau_produits"] = str(e)
        try:
            self.tableau_generique_parse = parser_tableau_generique(
                self.tableau_generique or ""
            )
        except ErreurTableauAPLSH as e:
            erreurs["tableau_generique"] = str(e)
        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        # Garantit le cache JSON même hors admin (scripts, shell).
        self.full_clean()
        super().save(*args, **kwargs)

    # ─── Accès runtime ────────────────────────────────────────────────────

    def produits(self):
        """Lignes produits enrichies du libellé Fertilisant, triées."""
        libelles = dict(
            Fertilisant.objects.values_list("identifiant", "libelle_public")
        )
        lignes = []
        for i, ligne in enumerate(self.tableau_produits_parse):
            libelle = libelles.get(ligne["fertilisant"], ligne["fertilisant"])
            affichage = (
                f"{libelle} — {ligne['variante']}" if ligne["variante"] else libelle
            )
            lignes.append({**ligne, "index": i, "libelle": affichage})
        return sorted(lignes, key=lambda x: x["libelle"].lower())
