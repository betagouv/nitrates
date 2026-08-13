"""Retours utilisateurs du simulateur nitrates (cartes #284, #287 et #285).

Un seul modèle générique `RetourUtilisateur` couvre trois intentions distinctes,
discriminées par le champ `type` :

- **feedback** (#284) : en fin de simulation, « De 0 à 5, cet outil vous a-t-il
  été utile ? » + commentaire libre + email optionnel (devenir alpha-testeur).
- **interet_region** (#287) : au clic sur une zone hors périmètre, capture d'un
  email « prévenez-moi à l'ouverture de ma région » + le code région tenté.
- **bug** (#285) : bouton flottant discret présent sur toutes les pages. L'utilisateur
  signale un bug ou un ressenti ; on capture en plus, dans `contexte`, le maximum
  d'infos techniques (URL, user-agent, logs console, requêtes réseau) pour reproduire.

RGPD (exigence forte des trois cartes) :
- L'email est stocké SEUL, jamais joint aux données de simulation. Le champ
  `contexte` ne contient que des métadonnées ANONYMES (ex : type de résultat),
  aucune donnée localisante ni parcellaire.
- Une case de consentement (`consentement_email`) doit être cochée pour qu'un
  email soit collecté.
- Aucune transmission à des organismes régionaux / externes / de contrôle.
"""

from django.db import models


class RetourUtilisateur(models.Model):
    """Un retour utilisateur : feedback fin de simulation OU intérêt région.

    Modèle append-only (audit) : on n'édite pas les lignes, on les lit en
    admin. Aucune FK vers une simulation (les retours restent anonymes).
    """

    class Type(models.TextChoices):
        FEEDBACK = "feedback", "Feedback fin de simulation"
        INTERET_REGION = "interet_region", "Intérêt région non ouverte"
        BUG = "bug", "Signalement bug / retour (bouton flottant)"

    type = models.CharField(
        max_length=20,
        choices=Type.choices,
        db_index=True,
        help_text="Nature du retour : feedback simulation (#284), intérêt "
        "région (#287) ou signalement bug (#285).",
    )

    # #284 : note d'utilité 0-5 (null pour un intérêt région).
    note = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Note d'utilité de 0 à 5 (feedback uniquement).",
    )
    commentaire = models.TextField(
        blank=True,
        help_text="Commentaire libre de l'utilisateur (feedback).",
    )

    # Email optionnel. Collecté UNIQUEMENT avec consentement explicite.
    email = models.EmailField(
        blank=True,
        help_text="Email optionnel (alpha-testeur / alerte ouverture région). "
        "Stocké seul, jamais associé aux données de simulation.",
    )
    consentement_email = models.BooleanField(
        default=False,
        help_text="La case de consentement RGPD a été cochée pour cet email.",
    )

    # Code région concernée : région tentée (#287) ou région de la simulation
    # notée (#284). Donnée grossière (région), non localisante.
    region_code = models.CharField(
        max_length=2,
        blank=True,
        help_text="Code région INSEE concernée (ex : '44'). Non localisant.",
    )

    # Métadonnées ANONYMES uniquement (jamais lat/lng ni parcelle) : ex type de
    # résultat, page d'origine. Sert à interpréter les retours sans ré-identifier.
    contexte = models.JSONField(
        default=dict,
        blank=True,
        help_text="Métadonnées anonymes (aucune donnée personnelle ni parcellaire).",
    )

    cree_le = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-cree_le",)
        verbose_name = "Retour utilisateur"
        verbose_name_plural = "Retours utilisateurs"
        indexes = [
            models.Index(fields=["type", "-cree_le"]),
        ]

    def __str__(self):
        if self.type == self.Type.FEEDBACK:
            note = self.note if self.note is not None else "?"
            return f"Feedback {note}/5 - {self.cree_le:%Y-%m-%d %H:%M}"
        if self.type == self.Type.BUG:
            apercu = (self.commentaire or "").strip()[:40]
            return f"Bug/retour « {apercu or '(sans texte)'} » - {self.cree_le:%Y-%m-%d %H:%M}"
        return (
            f"Intérêt région {self.region_code or '?'} - {self.cree_le:%Y-%m-%d %H:%M}"
        )

    @property
    def a_email(self) -> bool:
        return bool(self.email)
