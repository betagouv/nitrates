"""Référentiels métier nitrates en base.

Migré depuis `envergo/nitrates/specs/referentiels.yaml` (cf. carte #61).
Les juristes peuvent éditer ces tables via l'admin Django sans
intervention dev :

  - CategorieCulture / Culture / BrancheCulturale : cascade form +
    routage vers les branches de l'arbre de décision.
  - Fertilisant : sous-fertilisants utilisateur, mappés vers les types
    réglementaires PAN.
  - CodePrescription + NoteReglementaire : libellés affichés en
    résultat de simulation, avec rédaction publique + brute.
  - EvenementPhenologique : bornes flottantes (brunissement_des_soies,
    derniere_coupe_luzerne, etc.).

Les listes figées par l'arrêté nitrates (types PAN, statut ICPE,
régions, catégories fertilisants) sont dans `constants.py` comme
choices Python.
"""

from django.core.validators import RegexValidator
from django.db import models

from envergo.nitrates.constants import (
    CategorieFertilisant,
    OccupationSol,
    TypeFertilisant,
)

# ─── Cultures ────────────────────────────────────────────────────────────────


class CategorieCulture(models.Model):
    """Catégorie de culture affichée au 1er niveau de la cascade
    formulaire (ex 'Culture d'hiver', 'Prairies ou luzerne').

    En table parce que les juristes peuvent vouloir réorganiser
    (séparer luzerne de prairie, créer 'cultures pérennes irriguées'...).
    """

    identifiant = models.SlugField(max_length=64, unique=True)
    libelle_public = models.CharField(max_length=255)
    champs_prefill = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Champs à injecter dans le contexte quand cette catégorie "
            "est choisie SANS sous-culture (cas 'Sol non cultivé')."
        ),
    )
    ordre_affichage = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("ordre_affichage", "libelle_public")
        verbose_name = "Catégorie de culture"
        verbose_name_plural = "Catégories de culture"

    def __str__(self):
        return self.libelle_public


class BrancheCulturale(models.Model):
    """Branche de l'arbre de décision sur le nœud formulaire/sous_culture.

    Une `BrancheCulturale` est référencée par les arbres YAML comme
    `valeur:` sur les nœuds `formulaire/sous_culture` (ex `colza`,
    `culture_printemps`, `cie_avant_3112`). Plusieurs `Culture`
    utilisateur peuvent mapper vers la même `BrancheCulturale` (ex maïs
    + culture de printemps autre que maïs + prairie temporaire printemps
    → branche `culture_printemps`).

    C'est la SEULE source de vérité pour la liste des branches
    autorisées dans les arbres : le validator refuse une `valeur:`
    inconnue.
    """

    identifiant = models.SlugField(max_length=64, unique=True)
    libelle_court = models.CharField(
        max_length=255,
        help_text="Libellé interne pour les juristes (non affiché user).",
    )
    description = models.TextField(blank=True)
    ordre_affichage = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("ordre_affichage", "identifiant")
        verbose_name = "Branche culturale (arbre)"
        verbose_name_plural = "Branches culturales (arbre)"

    def __str__(self):
        return self.identifiant


class Culture(models.Model):
    """Culture utilisateur du formulaire (ex 'Colza', 'Maïs', 'Luzerne').

    Une Culture est rattachée à :
      - `CategorieCulture` (niveau 1 cascade form)
      - `BrancheCulturale` (niveau routage arbre YAML)
      - `occupation_sol` (niveau 1 arbre YAML)

    `identifiant` est consommé par cascade.js pour reconstruire la
    cascade côté front. La résolution Culture → branche d'arbre se
    fait via `branche_culturale.identifiant` + `occupation_sol`.
    """

    identifiant = models.SlugField(max_length=64, unique=True)
    libelle_public = models.CharField(max_length=255)
    categorie = models.ForeignKey(
        CategorieCulture, on_delete=models.PROTECT, related_name="cultures"
    )
    branche_culturale = models.ForeignKey(
        BrancheCulturale, on_delete=models.PROTECT, related_name="cultures"
    )
    occupation_sol = models.CharField(
        max_length=32,
        choices=OccupationSol.choices,
        help_text="Branche niveau 1 de l'arbre YAML.",
    )
    champs_prefill = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Champs à injecter dans le contexte quand cette culture est "
            'choisie. Ex pour Maïs : {"culture_irriguee_type": "mais"}.'
        ),
    )
    ordre_affichage = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("categorie__ordre_affichage", "ordre_affichage", "libelle_public")
        verbose_name = "Culture"
        verbose_name_plural = "Cultures"

    def __str__(self):
        return self.libelle_public


# ─── Fertilisants ────────────────────────────────────────────────────────────


class Fertilisant(models.Model):
    """Fertilisant précis affiché au 2e niveau de la cascade formulaire
    (ex 'Boues de papeterie', 'Fientes de volailles').

    Catégorie utilisateur en choices (figées arrêté). Type réglementaire
    PAN en choices (figés arrêté). Seule la liste des fertilisants
    précis est dynamique (les juristes peuvent en ajouter).

    Contrainte DB : `type_reglementaire != "type_I"` (cette valeur est
    réservée aux branches d'arbre de décision qui regroupent Ia ∪ Ib,
    elle ne doit pas apparaître sur un Fertilisant réel sinon le
    fallback `type_Ia → type_I` est compromis).
    """

    identifiant = models.SlugField(max_length=64, unique=True)
    libelle_public = models.CharField(max_length=255)
    description = models.TextField(
        blank=True,
        help_text="Note interne (post-it Miro, contexte juriste, etc.).",
    )
    categorie = models.CharField(
        max_length=32,
        choices=CategorieFertilisant.choices,
    )
    type_reglementaire = models.CharField(
        max_length=16,
        choices=TypeFertilisant.choices,
        help_text=(
            "Type PAN figé par l'arrêté. Détermine la branche "
            "type_fertilisant suivie dans l'arbre de décision. "
            "type_I interdit (réservé routage arbre)."
        ),
    )
    ordre_affichage = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("categorie", "ordre_affichage", "libelle_public")
        verbose_name = "Fertilisant"
        verbose_name_plural = "Fertilisants"
        constraints = [
            models.CheckConstraint(
                check=~models.Q(type_reglementaire="type_I"),
                name="fertilisant_type_I_interdit",
                violation_error_message=(
                    "Le type 'type_I' est réservé aux branches d'arbre "
                    "regroupées (Ia ∪ Ib). Choisissez type_Ia ou type_Ib."
                ),
            )
        ]

    def __str__(self):
        return self.libelle_public


# ─── Codes prescription + notes ──────────────────────────────────────────────


class NoteReglementaire(models.Model):
    """Note de bas de page conditionnelle (note_1 à note_13).

    Deux usages :
      1. Note attachée à une PC (FK depuis `CodePrescription`).
      2. Note géographique (ex note_5 = régions PACA/Occitanie + 5 dépts)
         qui pilote la résolution catalogue dans l'arbre.

    Les champs `regions_concernees` / `departements_concernes` peuvent
    rester vides pour les notes non géographiques.
    """

    identifiant = models.SlugField(max_length=16, unique=True)
    libelle_court = models.CharField(max_length=255)
    condition_declenchement = models.TextField()
    regions_concernees = models.JSONField(
        default=list,
        blank=True,
        help_text="Codes région INSEE (ex ['R93', 'R76']).",
    )
    departements_concernes = models.JSONField(
        default=list,
        blank=True,
        help_text="Codes département (ex ['24', '33', '40']).",
    )
    ordre_affichage = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("ordre_affichage", "identifiant")
        verbose_name = "Note réglementaire"
        verbose_name_plural = "Notes réglementaires"

    def __str__(self):
        return f"{self.identifiant} — {self.libelle_court}"


class CodePrescription(models.Model):
    """Code de prescription PC (pc1 à pc16) référencé par les feuilles
    de l'arbre de décision."""

    identifiant = models.SlugField(max_length=16, unique=True)
    mots_cles = models.CharField(max_length=255, blank=True)
    texte_court = models.TextField(
        help_text="Rédaction simplifiée pour affichage utilisateur."
    )
    texte_redaction_initiale = models.TextField(
        blank=True,
        help_text="Rédaction juridique brute de l'arrêté.",
    )
    toujours_affiche = models.BooleanField(
        default=False,
        help_text=(
            "Si True, ce code est affiché sur toutes les règles "
            "(prescriptions générales d'interdiction permanente)."
        ),
    )
    note_reglementaire = models.ForeignKey(
        NoteReglementaire,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="codes_prescription",
        help_text=(
            "Note de bas de page associée. Optionnel : à durcir en "
            "non-nullable si les juristes confirment qu'une PC a "
            "toujours une note attachée."
        ),
    )
    ordre_affichage = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("ordre_affichage", "identifiant")
        verbose_name = "Code de prescription"
        verbose_name_plural = "Codes de prescription"

    def __str__(self):
        return f"{self.identifiant.upper()} — {self.mots_cles}"


# ─── Événements phénologiques ────────────────────────────────────────────────


_JJMM_VALIDATOR = RegexValidator(
    regex=r"^\d{2}/\d{2}$",
    message="Format attendu : JJ/MM (ex 15/08).",
)


class EvenementPhenologique(models.Model):
    """Événement phénologique utilisé comme borne flottante d'une
    période d'épandage (ex 'brunissement_des_soies' pour le maïs,
    'derniere_coupe_luzerne' pour la luzerne).

    `date_calendrier` est une date conventionnelle d'affichage
    uniquement — la vraie date dépend du climat et de la parcelle.
    Elle sert à positionner l'événement sur la barre du calendrier
    d'épandage.
    """

    identifiant = models.SlugField(max_length=64, unique=True)
    libelle_public = models.CharField(max_length=255)
    date_calendrier = models.CharField(
        max_length=5,
        validators=[_JJMM_VALIDATOR],
        help_text=(
            "Date conventionnelle d'affichage au format JJ/MM "
            "(ex 15/08). Pas une date métier."
        ),
    )

    class Meta:
        ordering = ("identifiant",)
        verbose_name = "Événement phénologique"
        verbose_name_plural = "Événements phénologiques"

    def __str__(self):
        return self.libelle_public
