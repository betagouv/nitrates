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


class ContenuRichDSFR(models.Model):
    """Une zone de contenu riche, adressée par `cle`.

    `blocs` est l'unique source : une liste de blocs typés (cf.
    `compile_dsfr`). Pas de champ HTML : le rendu est recompilé.
    """

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

    class Meta:
        ordering = ("cle",)
        verbose_name = "Contenu riche DSFR"
        verbose_name_plural = "Contenus riches DSFR"

    def __str__(self):
        return f"{self.cle} ({self.libelle_admin})"

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
