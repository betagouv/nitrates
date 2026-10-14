"""Historique des contenus éditoriaux : PC et contenus riches.

Chaque écriture d'un CodePrescription ou d'un ContenuRichDSFR (admin,
commande, fixture, migration) laisse une révision : instantané complet de ce
qui est rendu (blocs riches + métadonnées), où (environnement), quand, qui,
par quel canal, et pourquoi (motif libre, ex « copié depuis staging »).

Les champs `texte_court` / `texte_redaction_initiale` des PC ne sont pas
suivis : seul le bloc riche est rendu, ce sont des reliquats.

La capture est faite par `envergo.nitrates.historique` (signaux + contexte).
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class RevisionContenu(models.Model):
    TYPE_PC = "pc"
    TYPE_CONTENU_RICH = "contenu_rich"
    TYPES = [
        (TYPE_PC, "Code de prescription"),
        (TYPE_CONTENU_RICH, "Contenu riche"),
    ]

    ACTION_CREATION = "creation"
    ACTION_MODIFICATION = "modification"
    ACTION_SUPPRESSION = "suppression"
    ACTION_CONSTAT = "constat"
    ACTIONS = [
        (ACTION_CREATION, "Création"),
        (ACTION_MODIFICATION, "Modification"),
        (ACTION_SUPPRESSION, "Suppression"),
        # Écart constaté entre la base et la dernière révision connue : une
        # écriture est passée sans laisser de trace (SQL direct, update()).
        (ACTION_CONSTAT, "Écart constaté (écriture non tracée)"),
    ]

    ORIGINE_ADMIN = "admin"
    ORIGINE_COMMANDE = "commande"
    ORIGINE_FIXTURE = "fixture"
    ORIGINE_MIGRATION = "migration"
    ORIGINE_CODE = "code"
    ORIGINES = [
        (ORIGINE_ADMIN, "Admin"),
        (ORIGINE_COMMANDE, "Commande"),
        (ORIGINE_FIXTURE, "Chargement de fixture"),
        (ORIGINE_MIGRATION, "Migration"),
        (ORIGINE_CODE, "Code / shell"),
    ]

    type_objet = models.CharField(max_length=16, choices=TYPES)
    # Identifiant métier (identifiant du PC, clé du contenu riche) : survit à
    # la suppression de l'objet et se compare d'un environnement à l'autre.
    identifiant = models.CharField(max_length=64, db_index=True)
    action = models.CharField(max_length=16, choices=ACTIONS)
    champs_modifies = models.JSONField(default=list, blank=True)
    # État APRÈS l'écriture (pour une suppression : dernier état connu).
    instantane = models.JSONField()
    environnement = models.CharField(max_length=32, blank=True)
    origine = models.CharField(max_length=16, choices=ORIGINES)
    # Commande, fichier de fixture… : ce qui a écrit, quand ce n'est pas une
    # personne dans l'admin.
    source = models.CharField(max_length=255, blank=True)
    motif = models.TextField(blank=True)
    auteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["type_objet", "identifiant", "-created_at"])]
        verbose_name = "Révision de contenu"
        verbose_name_plural = "Historique des contenus (PC et contenus riches)"

    def __str__(self):
        quand = timezone.localtime(self.created_at)
        return (
            f"{self.identifiant} — {self.get_action_display()} ({quand:%d/%m/%Y %H:%M})"
        )

    def precedente(self):
        return (
            RevisionContenu.objects.filter(
                type_objet=self.type_objet,
                identifiant=self.identifiant,
            )
            .filter(
                models.Q(created_at__lt=self.created_at)
                | models.Q(created_at=self.created_at, pk__lt=self.pk)
            )
            .order_by("-created_at", "-pk")
            .first()
        )
