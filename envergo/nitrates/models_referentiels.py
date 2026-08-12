"""Référentiels métier nitrates en base.

Migré depuis un YAML historique en base (cf. carte #61). Depuis #226, le
seed initial provient de la fixture `fixtures/initial_referentiels.json`
(commande `seed_referentiels`), plus d'aucun YAML de référentiels.
Les juristes peuvent éditer ces tables via l'admin Django sans
intervention dev :

  - GroupeCultureUI / Culture / BrancheCulturale : cascade form +
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

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q

from envergo.nitrates.constants import (
    SCOPE_CHOICES,
    SCOPE_NATIONAL,
    CategorieFertilisant,
    OccupationSol,
    TypeFertilisant,
)
from envergo.nitrates.regions import REGIONS

# Choices lisibles pour le code region INSEE des declinaisons de PC (meme
# convention que DecisionTree.region_code et catalog["region_code"] : code
# sans prefixe R, ex "44"). Le libelle n'est que du confort admin.
REGION_CODE_CHOICES = [
    (code, f"{label} ({code})") for code, label in sorted(REGIONS.items())
]

# ─── Support clefs naturelles (seed fixture idempotent, #226) ─────────────────
#
# Tous les modèles référentiel ont un `identifiant` unique. On l'expose comme
# clef naturelle pour que la fixture de seed (dumpdata --natural-primary,
# chargée par `seed_referentiels`) fasse un upsert SUR L'IDENTIFIANT plutôt que
# sur la PK auto-incrémentée. Sans ça, un re-seed sur une base dont les PK ont
# divergé (ex après suppression/réinsertion d'une ligne en admin) collisionne
# sur la contrainte unique `identifiant`.


class _IdentifiantNaturalKeyManager(models.Manager):
    def get_by_natural_key(self, identifiant):
        return self.get(identifiant=identifiant)


class _NaturalKeyByIdentifiant(models.Model):
    """Mixin abstrait : clef naturelle = (identifiant,)."""

    objects = _IdentifiantNaturalKeyManager()

    class Meta:
        abstract = True

    def natural_key(self):
        return (self.identifiant,)


# ─── Cultures ────────────────────────────────────────────────────────────────


class GroupeCultureUI(_NaturalKeyByIdentifiant):
    """Groupe de cultures affiché au 1er niveau de la cascade formulaire
    (ex 'Culture d'hiver', 'Prairies ou luzerne').

    Sert UNIQUEMENT à structurer la cascade du formulaire front (1er
    select 'catégorie de culture'). Aucune logique métier ne s'appuie
    dessus -- l'arbre de décision branche sur BrancheCulturale +
    OccupationSol via la table Culture (qui sert de mapper UI <-> arbre).

    En table parce que les juristes peuvent vouloir réorganiser ces
    groupes (séparer luzerne de prairie, créer 'cultures pérennes
    irriguées', etc.) sans intervention dev.
    """

    identifiant = models.SlugField(max_length=64, unique=True)
    libelle_public = models.CharField(max_length=255)
    champs_prefill = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Champs à injecter dans le contexte quand ce groupe est "
            "choisi SANS sous-culture (cas 'Sol non cultivé')."
        ),
    )
    ordre_affichage = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("ordre_affichage", "libelle_public")
        verbose_name = "Groupe de culture (UI cascade)"
        verbose_name_plural = "Groupes de culture (UI cascade)"

    def __str__(self):
        return self.libelle_public


class BrancheCulturale(_NaturalKeyByIdentifiant):
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


class Culture(_NaturalKeyByIdentifiant):
    """Culture utilisateur du formulaire (ex 'Colza', 'Maïs', 'Luzerne').

    Une Culture est rattachée à :
      - `GroupeCultureUI` (niveau 1 cascade form, regroupement UX)
      - `BrancheCulturale` (niveau routage arbre YAML)
      - `occupation_sol` (niveau 1 arbre YAML)

    `identifiant` est consommé par cascade.js pour reconstruire la
    cascade côté front. La résolution Culture → branche d'arbre se
    fait via `branche_culturale.identifiant` + `occupation_sol`.
    """

    identifiant = models.SlugField(max_length=64, unique=True)
    libelle_public = models.CharField(max_length=255)
    categorie = models.ForeignKey(
        GroupeCultureUI, on_delete=models.PROTECT, related_name="cultures"
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
        ordering = (
            "categorie__ordre_affichage",
            "ordre_affichage",
            "libelle_public",
        )
        verbose_name = "Culture"
        verbose_name_plural = "Cultures"

    def __str__(self):
        return self.libelle_public


# ─── Fertilisants ────────────────────────────────────────────────────────────


class Fertilisant(_NaturalKeyByIdentifiant):
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
    champs_prefill = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Champs à injecter dans le contexte de parcours quand ce "
            "fertilisant est choisi, pour auto-résoudre des questions "
            "complémentaires de l'arbre (ex effluent_peu_charge / "
            "effluent_peu_charge_elevage). Mêmes clés que les `champ` des "
            "nœuds `complement`. La question n'est alors pas posée mais "
            "inférée. Vide = aucune inférence."
        ),
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


class NoteReglementaire(_NaturalKeyByIdentifiant):
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


class CodePrescription(_NaturalKeyByIdentifiant):
    """Code de prescription PC référencé par les feuilles de l'arbre de
    décision.

    Depuis #147, la table porte aussi les DÉCLINAISONS géographiques et les
    FUSIONS rédigées par les juristes, sélectionnées par le moteur (cf.
    `yaml_tree/prescriptions.py`) :

      - une feuille d'arbre ne référence que des codes de BASE (pc1, pc12…) ;
      - la déclinaison affichée (ex pc12_zar_ge) est résolue selon la géo de
        la parcelle (zar > region > national, fallback base), même modèle que
        la sélection d'arbres — et indépendamment de l'arbre qui a matché :
        une feuille PAN atteinte par fallback de cascade en Grand Est doit
        afficher la version Grand Est de la PC ;
      - quand tous les composants d'une fusion (ex pc1_pc12 = pc1 + pc12)
        sont présents sur une feuille, la fusion remplace ses composants,
        puis est déclinée géographiquement comme les autres.
    """

    identifiant = models.SlugField(max_length=32, unique=True)
    mots_cles = models.CharField(max_length=255, blank=True)
    texte_court = models.TextField(
        help_text="Rédaction simplifiée pour affichage utilisateur."
    )
    texte_redaction_initiale = models.TextField(
        blank=True,
        help_text="Rédaction juridique brute de l'arrêté.",
    )
    # Contenu riche éditable (carte #136). Source unique du rendu DSFR du PC
    # quand non vide : compilé en HTML au rendu (cf. compile_dsfr), édité via
    # l'éditeur WYSIWYG dans l'admin. Les champs texte ci-dessus restent en
    # place (fallback tant que `blocs` est vide ; pas de casse pour les autres
    # consommateurs de la table).
    blocs = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Contenu riche (format {schema, blocs:[...]}). Édité via l'éditeur, "
            "jamais à la main. Si vide, on retombe sur texte_court."
        ),
    )
    toujours_affiche = models.BooleanField(
        default=False,
        help_text=(
            "Si True, ce code est affiché sur toutes les règles "
            "(prescriptions générales d'interdiction permanente)."
        ),
    )
    plafond = models.BooleanField(
        default=False,
        help_text=(
            "Si True, ce « code » est en réalité une RÈGLE DE PLAFOND (abus de "
            "langage : PC12 à PC16 ne sont pas de vraies prescriptions "
            "conditionnées). Conséquences d'affichage : le plafond est rendu "
            "inline sous le calendrier (pas dans le drawer des conditions) ; et "
            "si TOUTES les prescriptions d'une règle sont des plafonds, ses "
            "périodes « autorisation sous condition » sont peintes en VERT "
            "(autorisé) au lieu d'orange — le plafond s'appliquant de toute "
            "façon en période autorisée."
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
    # ─── Zone d'application (sélection scope + région, #147) ──────────────
    scope = models.CharField(
        "Périmètre",
        max_length=16,
        choices=SCOPE_CHOICES,
        default=SCOPE_NATIONAL,
        help_text=(
            "Territoire où cette rédaction s'applique. Le moteur choisit, "
            "parmi une PC de base et ses déclinaisons, celle du périmètre "
            "le plus spécifique activé pour la parcelle (ZAR > PAR > PAN)."
        ),
    )
    region_code = models.CharField(
        "Région",
        max_length=3,
        blank=True,
        default="",
        choices=REGION_CODE_CHOICES,
        help_text="Requis pour un périmètre régional (PAR) ou ZAR.",
    )
    variante_de = models.ForeignKey(
        "self",
        verbose_name="Déclinaison de",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="variantes",
        limit_choices_to={"variante_de__isnull": True},
        help_text=(
            "PC de base dont cette ligne est la déclinaison géographique "
            "(ex pc12_zar_ge → pc12). Vide pour une PC de base."
        ),
    )
    composants_fusion = models.ManyToManyField(
        "self",
        verbose_name="Fusion des PC",
        symmetrical=False,
        blank=True,
        related_name="fusions",
        help_text=(
            "PC de base que cette rédaction fusionne (ex pc1_pc12 = pc1 + "
            "pc12). Quand une feuille d'arbre liste tous les composants, la "
            "fusion s'affiche à leur place. Vide pour une PC simple."
        ),
    )
    ordre_affichage = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("ordre_affichage", "identifiant")
        verbose_name = "Code de prescription"
        verbose_name_plural = "Codes de prescription"
        constraints = [
            # Cohérence scope / région : une PC nationale n'a pas de région,
            # une déclinaison PAR ou ZAR en a forcément une.
            models.CheckConstraint(
                check=(
                    Q(scope=SCOPE_NATIONAL, region_code="")
                    | (~Q(scope=SCOPE_NATIONAL) & ~Q(region_code=""))
                ),
                name="codeprescription_scope_region_coherents",
                violation_error_message=(
                    "Une PC nationale ne porte pas de région ; une PC "
                    "régionale ou ZAR doit en porter une."
                ),
            ),
            # Une seule déclinaison d'une PC de base par zone d'application.
            models.UniqueConstraint(
                fields=["variante_de", "scope", "region_code"],
                condition=Q(variante_de__isnull=False),
                name="codeprescription_unique_variante_par_zone",
                violation_error_message=(
                    "Cette PC de base a déjà une déclinaison pour cette "
                    "zone d'application."
                ),
            ),
        ]

    def clean(self):
        """Cohérence déclarative de la zone d'application (#147).

        Appelé par full_clean()/forms admin. Les garanties d'unicité et la
        cohérence scope/région sont aussi tenues par les contraintes DB.
        La cohérence des composants de fusion (M2M) est validée côté form
        admin (pas accessible ici avant save).
        """
        super().clean()
        if self.scope == SCOPE_NATIONAL:
            if self.region_code:
                raise ValidationError(
                    "Une PC nationale (PAN) ne doit pas porter de code région."
                )
        elif not self.region_code:
            raise ValidationError(
                "Une PC régionale (PAR) ou ZAR doit porter un code région."
            )
        if self.variante_de_id is not None:
            if self.variante_de_id == self.pk:
                raise ValidationError("Une PC ne peut pas être sa propre déclinaison.")
            if self.scope == SCOPE_NATIONAL:
                raise ValidationError(
                    "Une déclinaison porte un périmètre régional ou ZAR "
                    "(la version nationale EST la PC de base)."
                )
            if self.variante_de.variante_de_id is not None:
                raise ValidationError(
                    "Une déclinaison doit pointer une PC de base (pas de "
                    "chaîne de déclinaisons)."
                )

    def __str__(self):
        return f"{self.identifiant.upper()} — {self.mots_cles}"


# ─── Événements phénologiques ────────────────────────────────────────────────


_JJMM_VALIDATOR = RegexValidator(
    regex=r"^\d{2}/\d{2}$",
    message="Format attendu : JJ/MM (ex 15/08).",
)


class EvenementPhenologique(_NaturalKeyByIdentifiant):
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
