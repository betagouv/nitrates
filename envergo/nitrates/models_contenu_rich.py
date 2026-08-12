"""Contenu riche éditable en base (carte #131).

Objet DB *générique* adressé par clé : une « zone de contenu » du site =
**un** objet `ContenuRichDSFR`. Le juriste édite un rendu WYSIWYG dans
l'admin ; sous le capot on ne stocke QUE du JSON (`blocs`), jamais de HTML.
Le HTML DSFR est recompilé au rendu par `compile_dsfr` (cf.
`contenu_rich/compilateur.py`) — source unique = le JSON, pas de
désynchronisation source/rendu, et le JSON pourra être exposé tel quel par
une future API.

Premier usage : `resultat.regles_permanentes` (les prescriptions générales
d'interdiction permanente du panneau résultat). Les notes PC réutiliseront
le même objet/mécanisme plus tard — d'où le nommage générique (pas un champ
ajouté sur NoteReglementaire / CodePrescription).
"""

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

# Version du schéma `blocs` (cf. compilateur). On la stocke pour pouvoir
# migrer le JSON plus tard sans casser les contenus existants.
SCHEMA_VERSION = 1

# Clé en notation pointée (ex. "resultat.regles_permanentes"). On n'utilise
# PAS SlugField : il interdit le point. Minuscules, chiffres, ._- autorisés.
_cle_validator = RegexValidator(
    r"^[a-z0-9]+([._-][a-z0-9]+)*$",
    "Clé invalide : minuscules, chiffres et . _ - uniquement "
    '(ex. "resultat.regles_permanentes").',
)


# Types de contenu (carte #110). Un contenu `definition` alimente le
# glossaire : page « Aide & définitions » + termes cliquables du simulateur.
TYPE_GENERAL = "general"
TYPE_DEFINITION = "definition"
TYPES_CONTENU = (
    (TYPE_GENERAL, "Général"),
    (TYPE_DEFINITION, "Définition"),
)

# Sections de la page « Aide & définitions » (design Coralie, carte #110).
# L'ordre du tuple EST l'ordre d'affichage des sections sur la page.
CATEGORIES_DEFINITION = (
    ("fertilisants-effluents", "Fertilisants et effluents"),
    ("azote-bilans", "Azote et bilans"),
    ("pratique-documents", "Pratique et documents"),
    ("reglementation-zonage", "Réglementation et zonage"),
)


class _CleNaturalKeyManager(models.Manager):
    """Clef naturelle = (cle,) — pour dumpdata/loaddata portable entre DB.

    Comme les referentiels (cf. models_referentiels._NaturalKeyByIdentifiant),
    on expose `cle` comme clef naturelle pour que le GitOps des donnees
    (dump/seed entre environnements dev/staging/prod, cf. carte #50) resolve
    l'objet par sa cle stable et non par sa PK auto-incrementee (non portable
    d'une base a l'autre).
    """

    def get_by_natural_key(self, cle):
        return self.get(cle=cle)


class ContenuRichDSFR(models.Model):
    """Une zone de contenu riche, adressée par `cle`.

    `blocs` est l'unique source : une liste de blocs typés (cf.
    `compile_dsfr`). Pas de champ HTML : le rendu est recompilé.
    """

    objects = _CleNaturalKeyManager()

    def natural_key(self):
        return (self.cle,)

    cle = models.CharField(
        max_length=64,
        unique=True,
        validators=[_cle_validator],
        help_text=(
            "Identifiant stable référencé par le template "
            '(ex. "resultat.regles_permanentes"). Les points sont autorisés.'
        ),
    )
    libelle_admin = models.CharField(
        max_length=255,
        help_text="Nom lisible dans l'admin (jamais affiché côté public).",
    )
    blocs = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Source unique du contenu, au format {schema, blocs:[...]}. "
            "Édité via l'éditeur WYSIWYG, jamais à la main."
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)

    # ── Champs glossaire (carte #110) ─────────────────────────────────────
    # Seuls les contenus `type_contenu="definition"` les utilisent ; les
    # contenus `general` existants ne changent pas (défauts rétro-compatibles).
    type_contenu = models.CharField(
        max_length=16,
        choices=TYPES_CONTENU,
        default=TYPE_GENERAL,
        db_index=True,
        verbose_name="type de contenu",
        help_text=(
            "« Définition » = terme du glossaire, affiché sur la page "
            "Aide & définitions et cliquable dans le simulateur."
        ),
    )
    titre_public = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="titre public",
        help_text=(
            "Le terme tel qu'affiché aux usagers (ex. « Azote efficace »). "
            "Obligatoire pour une définition."
        ),
    )
    categorie = models.CharField(
        max_length=32,
        choices=CATEGORIES_DEFINITION,
        blank=True,
        verbose_name="catégorie",
        help_text="Section de la page Aide & définitions où ranger la définition.",
    )
    termes_declencheurs = models.JSONField(
        default=list,
        blank=True,
        verbose_name="termes déclencheurs",
        help_text=(
            "Variantes textuelles qui rendent le terme cliquable dans le "
            "simulateur (ex. « C/N », « rapport C/N »). Une liste de chaînes ; "
            "éditée dans l'admin en « une variante par ligne »."
        ),
    )

    class Meta:
        ordering = ("cle",)
        verbose_name = "Contenu riche DSFR"
        verbose_name_plural = "Contenus riches DSFR"

    def __str__(self):
        return f"{self.cle} ({self.libelle_admin})"

    def clean(self):
        super().clean()
        if self.type_contenu == TYPE_DEFINITION and not self.titre_public:
            raise ValidationError(
                {"titre_public": "Une définition doit avoir un titre public."}
            )

    @property
    def ancre(self) -> str:
        """Id d'ancre stable sur la page Aide & définitions.

        Dérivé de la clé (pas un champ de plus) : « definition.azote-efficace »
        → « azote-efficace ». Les points restants deviennent des tirets pour
        rester un id HTML/fragment valide et lisible."""
        return self.cle.split(".", 1)[-1].replace(".", "-")

    @property
    def liste_termes(self) -> list:
        """Termes déclencheurs, robuste à la forme stockée (liste attendue)."""
        t = self.termes_declencheurs
        if isinstance(t, list):
            return [str(v) for v in t if str(v).strip()]
        return []

    @property
    def liste_blocs(self) -> list:
        """Liste des blocs, robuste à la forme stockée.

        `blocs` peut être soit notre enveloppe {"schema": N, "blocs": [...]},
        soit directement une liste (tolérance), soit un dict vide (default).
        Renvoie toujours une liste (vide si rien)."""
        b = self.blocs
        if isinstance(b, dict):
            return b.get("blocs", []) or []
        if isinstance(b, list):
            return b
        return []
