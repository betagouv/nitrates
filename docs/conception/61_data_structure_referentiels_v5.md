# Carte #61 — Migration referentiels.yaml → DB — v5

**Statut** : data structure v5, post-audit 3 agents (form, YAML, parcours).
**Date** : 2026-05-22.

## Deltas v4 → v5

1. **Nouveau modèle `BrancheCulturale`** (1-N depuis `Culture`). Couvre culture principale ET couverts d'interculture (pas de modèle `SousCultureCouvert` séparé).
2. **`Culture.occupation_sol`** ajouté (choices `OccupationSol`).
3. **`Culture.branche_culturale`** FK vers `BrancheCulturale` (remplace l'idée `branche_sous_culture` CharField).
4. **`Fertilisant.description`** TextField blank (préserver les notes Miro).
5. **`CategorieCulture.champs_prefill`** JSONField (pour `sol_non_cultive` → `occupation_sol=sol_non_cultive`).
6. **`Fertilisant.type_reglementaire`** : CheckConstraint pour interdire `type_I` (réservé aux branches d'arbre, jamais à un fertilisant réel).
7. **`EvenementPhenologique.date_calendrier`** : RegexValidator `^\d{2}/\d{2}$`.
8. **Plus de façade `load_referentiels()`** : les modèles sont consommés directement, avec cache au niveau ORM (helpers métier + signal d'invalidation).
9. **`zone_note_5` DB-driven** : suppression du hardcode `_REGIONS_NOTE_5` dans `zonage_note_5.py`.
10. **Doublon `brunissement_soies`** : un seul slug retenu (`brunissement_des_soies`).

Non modifié :
- `StatutICPE` reste 4 valeurs (les regroupements `icpe_e_ou_d` du YAML sont exprimés via la grammaire d'arbre `valeurs: [a, b]`, pas via la DB).
- `TypeFertilisant` reste 6 valeurs (les 5 PAN + `type_I`). Le validator d'arbre accepte `effluent_peu_charge` comme valeur de routage sur `formulaire/type_fertilisant` au-delà des types (whitelist étendue).
- Composants calculatrice (`fenetre_epandage`, `luzerne_post_coupe`) restent en code Python.

## Choices Python (`envergo/nitrates/constants.py`)

```python
from django.db import models
from django.utils.translation import gettext_lazy as _


class TypeFertilisant(models.TextChoices):
    """Types réglementaires PAN (figés par l'arrêté nitrates).

    TYPE_I est une valeur SPÉCIALE réservée aux branches d'arbre :
    elle représente le regroupement type_Ia ∪ type_Ib. Aucun
    Fertilisant ne doit porter cette valeur — CheckConstraint DB
    en garde.
    """
    TYPE_0 = "type_0", _("Type 0")
    TYPE_IA = "type_Ia", _("Type Ia")
    TYPE_IB = "type_Ib", _("Type Ib")
    TYPE_I = "type_I", _("Type I (Ia ou Ib non distingué — usage arbre uniquement)")
    TYPE_II = "type_II", _("Type II")
    TYPE_III = "type_III", _("Type III")


class OccupationSol(models.TextChoices):
    CULTURE_PRINCIPALE = "culture_principale", _("Culture principale")
    COUVERT_INTERCULTURES = "couvert_intercultures", _("Couvert végétal d'interculture")
    PRAIRIE = "prairie", _("Prairie")
    SOL_NON_CULTIVE = "sol_non_cultive", _("Sol non cultivé")


class StatutICPE(models.TextChoices):
    NON_CONCERNE = "non_concerne", _("Pas concerné par un plan d'épandage")
    ICPE_A = "icpe_a", _("Soumis à autorisation (ICPE A)")
    ICPE_E = "icpe_e", _("Soumis à enregistrement (ICPE E)")
    ICPE_D = "icpe_d", _("Soumis à déclaration (ICPE D)")


class CategorieFertilisant(models.TextChoices):
    """Catégorie utilisateur de fertilisant (niveau 1 cascade form)."""
    FUMIERS = "fumiers", _("Fumiers")
    LISIERS = "lisiers", _("Lisiers")
    COMPOSTS = "composts", _("Composts")
    DIGESTATS = "digestats", _("Digestats")
    ENGRAIS_MINERAL = "engrais_mineral", _("Engrais minéral")
    BOUES = "boues", _("Boues")
    AUTRE = "autre", _("Autre")


# Régions INSEE métropole — codes figés
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
```

## Modèles ORM (`envergo/nitrates/models_referentiels.py`)

```python
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
    formulaire (ex 'Culture d'hiver', 'Prairies ou luzerne')."""

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
    """Branche de l'arbre de décision côté `formulaire/sous_culture`.

    Une BrancheCulturale est référencée par les arbres YAML comme
    `valeur:` sur les nœuds `formulaire/sous_culture`. Plusieurs
    `Culture` utilisateur peuvent mapper vers la même BrancheCulturale
    (ex maïs + culture de printemps autre que maïs + prairie temporaire
    printemps → branche `culture_printemps`).

    C'est la SEULE source de vérité pour la liste des branches
    autorisées dans les arbres. Le validator refuse une `valeur:`
    inconnue.
    """

    identifiant = models.SlugField(max_length=64, unique=True)
    libelle_court = models.CharField(
        max_length=255,
        help_text="Libellé interne pour les juristes (pas affiché user).",
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

    Une Culture rattachée à :
      - CategorieCulture (niveau 1 cascade form)
      - BrancheCulturale (niveau routage arbre YAML)
      - OccupationSol (niveau 1 arbre YAML)

    `identifiant` est consommé par cascade.js pour reconstruire la
    cascade. La résolution Culture → branche d'arbre se fait via
    `branche_culturale.identifiant` + `occupation_sol`.
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
        help_text="Branche niveau 1 arbre YAML.",
    )
    champs_prefill = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Champs à injecter dans le contexte. Ex pour Culture maïs : "
            '{"culture_irriguee_type": "mais"}.'
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
    (ex 'Boues de papeterie', 'Fientes de volailles')."""

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
            "type_fertilisant suivie dans l'arbre. type_I interdit "
            "(réservé routage arbre)."
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
      1. Note attachée à une PC.
      2. Note géographique (ex note_5 = PACA/Occitanie + 5 dépts) qui
         pilote la résolution catalogue dans l'arbre.
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
    """Code PC (ex pc1, pc15) référencé par les feuilles d'arbre."""

    identifiant = models.SlugField(max_length=16, unique=True)
    mots_cles = models.CharField(max_length=255, blank=True)
    texte_court = models.TextField(
        help_text="Rédaction simplifiée pour affichage utilisateur."
    )
    texte_redaction_initiale = models.TextField(
        blank=True,
        help_text="Rédaction juridique brute de l'arrêté.",
    )
    toujours_affiche = models.BooleanField(default=False)
    note_reglementaire = models.ForeignKey(
        NoteReglementaire,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="codes_prescription",
    )
    ordre_affichage = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("ordre_affichage", "identifiant")
        verbose_name = "Code de prescription"
        verbose_name_plural = "Codes de prescription"

    def __str__(self):
        return f"{self.identifiant.upper()} — {self.mots_cles}"


# ─── Événements phénologiques ────────────────────────────────────────────────


JJMM_VALIDATOR = RegexValidator(
    regex=r"^\d{2}/\d{2}$",
    message="Format attendu : JJ/MM (ex 15/08).",
)


class EvenementPhenologique(models.Model):
    """Événement phénologique borne flottante (ex 'brunissement_des_soies')."""

    identifiant = models.SlugField(max_length=64, unique=True)
    libelle_public = models.CharField(max_length=255)
    date_calendrier = models.CharField(
        max_length=5,
        validators=[JJMM_VALIDATOR],
        help_text=(
            "Date conventionnelle d'affichage JJ/MM. Positionne "
            "l'événement sur la barre calendrier — pas une date métier."
        ),
    )

    class Meta:
        ordering = ("identifiant",)
        verbose_name = "Événement phénologique"
        verbose_name_plural = "Événements phénologiques"

    def __str__(self):
        return self.libelle_public
```

## Récap v5

**Tables (7)** :
- `CategorieCulture`
- `BrancheCulturale` (nouveau — résout le mapping form → arbre)
- `Culture` (FK CategorieCulture + FK BrancheCulturale + occupation_sol)
- `Fertilisant` (CheckConstraint type_I interdit)
- `NoteReglementaire`
- `CodePrescription`
- `EvenementPhenologique` (RegexValidator JJ/MM)

**Choices figés** :
- `TypeFertilisant` (6 valeurs)
- `OccupationSol` (4)
- `StatutICPE` (4)
- `CategorieFertilisant` (7)
- `REGIONS_FR` dict (13)

## Architecture cache (consommation des modèles)

Pas de façade `load_referentiels()`. À la place :
- Helpers métier (`Fertilisant.objects.par_categorie()`, `BrancheCulturale.objects.values_list("identifiant", flat=True)`, etc.).
- Cache module-level via `lru_cache` sur les helpers les plus chauds (templatetag, validator, view simulateur).
- Signal `post_save` / `post_delete` sur les 7 modèles → invalidation cache (helper `clear_referentiels_cache()`).
- Préchargement optionnel via `AppConfig.ready()` pour les workers gunicorn.

## Validator d'arbre étendu

Le validator vérifie désormais :
- `formulaire/occupation_sol.valeur ∈ OccupationSol.values`
- `formulaire/sous_culture.valeur ∈ BrancheCulturale.identifiant`
- `formulaire/type_fertilisant.valeur ∈ TypeFertilisant.values ∪ {"effluent_peu_charge"}` (whitelist étendue documentée)
- `formulaire/plan_epandage.valeur ∈ StatutICPE.values ∪ {valeurs regroupées via grammaire}`
- `regle.code_prescription ∈ CodePrescription.identifiant`
- `regle.note ∈ NoteReglementaire.identifiant`

## Composants calculatrice

Restent **en code Python** (whitelist). Pas de table. Le YAML continue de référencer `composant: luzerne_post_coupe` + dict `parametres`.

## Notes ouvertes (non bloquantes MVP2)

- Doublon `brunissement_soies` / `brunissement_des_soies` : choisir `brunissement_des_soies` au seed, mettre à jour l'arbre.
- Préchargement DB au boot vs lazy au 1er hit : à benchmarker.
- Suppression de `_REGIONS_NOTE_5` hardcodée dans `zonage_note_5.py` : doit utiliser DB.
