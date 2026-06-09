# Carte #61 — Migration referentiels.yaml → DB

**Statut** : data structure validée v4, pas encore implémentée.
**Date** : 2026-05-22.

## Contexte

Aujourd'hui le simulateur nitrates utilise un fichier `envergo/nitrates/specs/referentiels.yaml` (~1100 lignes) qui mélange listes fermées (types réglementaires, ICPE, régions) et listes ouvertes (cultures précises, fertilisants précis, codes PC, notes…). Le tout est chargé runtime via `yaml_tree.loader.load_referentiels()` (cached LRU) et consommé par :

- la cascade frontend (`cascade.js` lit `/api/referentiels/`)
- le templatetag `calendrier_epandage` (résolution des bornes phénologiques)
- le panneau résultat (résolution `codes_prescription`, `notes`)
- le walker arbre (`mapping_sous_fertilisant_vers_type` pour résoudre type réglementaire avant descente)
- l'admin YAML editor (dropdowns référentiels)

**Objectif refacto** : passer en DB les entités éditables sans recompiler, garder en `choices` Python les listes figées par l'arrêté nitrates.

## Data structure cible — v4

### Choices Python (`envergo/nitrates/constants.py`)

```python
from django.db import models
from django.utils.translation import gettext_lazy as _


class TypeFertilisant(models.TextChoices):
    """Types réglementaires PAN (figés par l'arrêté nitrates)."""
    TYPE_0 = "type_0", _("Type 0")
    TYPE_IA = "type_Ia", _("Type Ia")
    TYPE_IB = "type_Ib", _("Type Ib")
    TYPE_I = "type_I", _("Type I (Ia ou Ib non distingué)")
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
    """Catégorie utilisateur de fertilisant (niveau 1 cascade form).
    Figée : ces 7 valeurs ne changent pas (arrêté nitrates)."""
    FUMIERS = "fumiers", _("Fumiers")
    LISIERS = "lisiers", _("Lisiers")
    COMPOSTS = "composts", _("Composts")
    DIGESTATS = "digestats", _("Digestats")
    ENGRAIS_MINERAL = "engrais_mineral", _("Engrais minéral")
    BOUES = "boues", _("Boues")
    AUTRE = "autre", _("Autre")


# Régions INSEE métropole — codes figés, dict en code suffit
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

### Modèles ORM (`envergo/nitrates/models_referentiels.py`)

```python
from django.db import models
from envergo.nitrates.constants import (
    CategorieFertilisant,
    TypeFertilisant,
)


class CategorieCulture(models.Model):
    """Catégorie de culture affichée au 1er niveau de la cascade
    formulaire (ex 'Culture d'hiver', 'Prairies ou luzerne').

    En table parce que les juristes pourront vouloir réorganiser
    (séparer luzerne de prairie, créer une catégorie 'cultures pérennes
    irriguées', etc.) sans intervention dev.
    """
    identifiant = models.SlugField(max_length=64, unique=True)
    libelle_public = models.CharField(max_length=255)
    ordre_affichage = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("ordre_affichage", "libelle_public")
        verbose_name = "Catégorie de culture"
        verbose_name_plural = "Catégories de culture"

    def __str__(self):
        return self.libelle_public


class Culture(models.Model):
    """Culture du formulaire (ex 'Colza', 'Maïs', 'Luzerne').

    Une Culture est rattachée à une CategorieCulture (niveau 1 cascade).
    Son `identifiant` est la valeur qui apparaît dans le YAML des arbres
    de décision (un nœud formulaire/sous_culture dont la valeur matche
    une Culture.identifiant existante). Le validator d'arbre vérifie
    cette cohérence : si l'arbre YAML référence un identifiant qui
    n'existe pas en DB, c'est une erreur.
    """
    identifiant = models.SlugField(max_length=64, unique=True)
    libelle_public = models.CharField(max_length=255)
    categorie = models.ForeignKey(
        CategorieCulture, on_delete=models.PROTECT, related_name="cultures"
    )

    # Pré-remplissage automatique de questions subsidiaires. Permet
    # d'éviter une question redondante quand le choix d'une Culture
    # implique déjà la réponse. Ex : Culture 'mais' pré-remplit
    # {"culture_irriguee_type": "mais"} → l'arbre n'a plus à poser
    # "quelle culture irriguée ?".
    champs_prefill = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Champs à injecter automatiquement dans le contexte quand "
            "cette culture est choisie. Format : {champ_arbre: valeur}. "
            "Vide par défaut."
        ),
    )

    ordre_affichage = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("categorie__ordre_affichage", "ordre_affichage", "libelle_public")
        verbose_name = "Culture"
        verbose_name_plural = "Cultures"

    def __str__(self):
        return self.libelle_public


class Fertilisant(models.Model):
    """Fertilisant précis affiché au 2e niveau de la cascade formulaire
    (ex 'Boues de papeterie', 'Fientes de volailles').

    Catégorie utilisateur en choices (liste figée). Type réglementaire
    PAN en choices (figé par l'arrêté). Seule la liste des fertilisants
    eux-mêmes est dynamique (juristes peuvent en ajouter).
    """
    identifiant = models.SlugField(max_length=64, unique=True)
    libelle_public = models.CharField(max_length=255)
    categorie = models.CharField(
        max_length=32,
        choices=CategorieFertilisant.choices,
    )
    type_reglementaire = models.CharField(
        max_length=16,
        choices=TypeFertilisant.choices,
        help_text=(
            "Type PAN figé par l'arrêté nitrates. Détermine la branche "
            "type_fertilisant suivie dans l'arbre de décision."
        ),
    )
    ordre_affichage = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("categorie", "ordre_affichage", "libelle_public")
        verbose_name = "Fertilisant"
        verbose_name_plural = "Fertilisants"

    def __str__(self):
        return self.libelle_public


class NoteReglementaire(models.Model):
    """Note de bas de page conditionnelle (note_1 à note_13) qui décrit
    les conditions de déclenchement d'un code de prescription ou d'une
    règle d'arbre.

    Deux usages identifiés :
      1. Note attachée à une PC (FK depuis CodePrescription).
      2. Note géographique (ex note_5 = Sud-Ouest + PACA/Occitanie) qui
         pilote la résolution catalogue dans l'arbre.

    Une seule table avec champs régions/dépts optionnels couvre les
    deux usages.
    """
    identifiant = models.SlugField(max_length=16, unique=True)
    libelle_court = models.CharField(max_length=255)
    condition_declenchement = models.TextField()
    regions_concernees = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Liste de codes région INSEE (ex ['R93', 'R76']). Vide pour "
            "les notes non géographiques."
        ),
    )
    departements_concernes = models.JSONField(
        default=list,
        blank=True,
        help_text="Liste de codes département (ex ['24', '33', '40']).",
    )
    ordre_affichage = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("ordre_affichage", "identifiant")
        verbose_name = "Note réglementaire"
        verbose_name_plural = "Notes réglementaires"

    def __str__(self):
        return f"{self.identifiant} — {self.libelle_court}"


class CodePrescription(models.Model):
    """Code PC (ex pc1, pc15) référencé par les feuilles de l'arbre de
    décision. Texte public + texte juridique brut conservés séparément.
    """
    identifiant = models.SlugField(max_length=16, unique=True)
    mots_cles = models.CharField(max_length=255, blank=True)
    texte_court = models.TextField(
        help_text="Rédaction simplifiée pour affichage utilisateur."
    )
    texte_redaction_initiale = models.TextField(
        blank=True,
        help_text=(
            "Rédaction juridique brute de l'arrêté, affichée en 'voir "
            "détail réglementaire'."
        ),
    )
    toujours_affiche = models.BooleanField(
        default=False,
        help_text=(
            "Si True, ce code est affiché sur toutes les règles "
            "(prescriptions générales)."
        ),
    )
    note_reglementaire = models.ForeignKey(
        NoteReglementaire,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="codes_prescription",
        help_text=(
            "Note de bas de page associée. Optionnel pour l'instant : "
            "à durcir en non-nullable si les juristes confirment qu'une "
            "PC a toujours une note attachée."
        ),
    )
    ordre_affichage = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("ordre_affichage", "identifiant")
        verbose_name = "Code de prescription"
        verbose_name_plural = "Codes de prescription"

    def __str__(self):
        return f"{self.identifiant.upper()} — {self.mots_cles}"


class EvenementPhenologique(models.Model):
    """Événement phénologique utilisé comme borne flottante d'une
    période d'épandage (ex 'brunissement_des_soies' pour le maïs,
    'derniere_coupe_luzerne' pour la luzerne).

    date_calendrier est une date conventionnelle d'affichage uniquement
    (la vraie date dépend du climat et de la parcelle).
    """
    identifiant = models.SlugField(max_length=64, unique=True)
    libelle_public = models.CharField(max_length=255)
    date_calendrier = models.CharField(
        max_length=5,
        help_text=(
            "Date conventionnelle d'affichage au format JJ/MM. "
            "Utilisée pour positionner l'événement sur la barre "
            "calendrier — pas une date métier."
        ),
    )

    class Meta:
        ordering = ("identifiant",)
        verbose_name = "Événement phénologique"
        verbose_name_plural = "Événements phénologiques"

    def __str__(self):
        return self.libelle_public
```

## Récapitulatif

**6 tables** :
- `CategorieCulture` (3 champs)
- `Culture` (FK CategorieCulture, JSONField `champs_prefill`)
- `Fertilisant` (catégorie + type_reglementaire en choices)
- `NoteReglementaire` (regions/depts en JSONField)
- `CodePrescription` (FK NoteReglementaire optionnelle)
- `EvenementPhenologique`

**5 choices figés** :
- `TypeFertilisant` (6 valeurs incluant type_I)
- `OccupationSol` (4)
- `StatutICPE` (4)
- `CategorieFertilisant` (7)
- `REGIONS_FR` dict (13)

## Mapping YAML → DB

| YAML actuel | Cible v4 |
|---|---|
| `types_fertilisants` | `TypeFertilisant` choices (libellés perdus pour les "boues, marcs, composts murs" — à voir si on les remet en glossaire) |
| `occupations_sol` | `OccupationSol` choices |
| `categories_cultures` | `CategorieCulture` table |
| `sous_cultures` | `Culture` table |
| `mapping_sous_culture_vers_branche` | `Culture.champs_prefill` JSON (+ identifiant de la Culture = valeur sur la branche d'arbre directement) |
| `statut_icpe` | `StatutICPE` choices |
| `codes_prescription` | `CodePrescription` table |
| `definitions` | **non migré** (glossaire 3 entrées, restera en `.po` ou template si besoin un jour) |
| `notes` | `NoteReglementaire` table |
| `regions` | `REGIONS_FR` dict |
| `evenements_phenologiques` | `EvenementPhenologique` table |
| `categories_fertilisants` | `CategorieFertilisant` choices |
| `sous_fertilisants` | `Fertilisant` table |
| `mapping_sous_fertilisant_vers_type` | `Fertilisant.type_reglementaire` |

## Hypothèses fortes

1. **L'arbre YAML est validé contre la DB** (pas l'inverse). Si un arbre référence une culture/fertilisant/PC/note inexistante en DB, le validator refuse.
2. **`Culture.identifiant`** est ce qui apparaît comme `valeur:` dans les nœuds `formulaire/sous_culture` de l'arbre. Donc des branches "regroupées" actuelles (`culture_hiver_hors_colza`, `culture_printemps` en tant que branche, etc.) deviennent des Cultures de la DB.
3. **`champs_prefill`** est un mécanisme générique, pas spécifique à `culture_irriguee_type`. Utilisable pour `sous_culture_couvert` aussi.
4. **Plus de `branche_sous_culture_arbre` ni `occupation_sol_arbre`** sur Culture : c'est l'arbre YAML qui doit se conformer à ce que la DB définit.

## Impact prévu

- **Backend** : `load_referentiels()` devient un wrapper qui assemble un dict depuis la DB (back-compat front).
- **Frontend** : `/api/referentiels/` garde la même shape JSON (cascade.js inchangé).
- **Admin** : nouvelles vues Django admin pour les 6 tables.
- **Arbre YAML** : validator étendu (lookup DB pour `valeur:` sur nœuds formulaire culture/fertilisant + références PC/note).
- **Suppression** : `referentiels.yaml` après migration (gardé en fixture de seed).

## Risques connus

- Migration de l'arbre YAML actif + arbre national doit suivre (alignement `valeur:`).
- Référentiels chargés runtime via `lru_cache` → invalidation à gérer (signal `post_save`).
- Performance : 5-6 requêtes DB en plus par chargement page si pas cachées correctement.
