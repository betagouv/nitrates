"""Constate les écritures non tracées des PC et contenus riches.

Compare l'état en base de chaque CodePrescription / ContenuRichDSFR à sa
dernière révision d'historique et consigne une révision « constat » quand
ils diffèrent : c'est la trace des écritures qui contournent les signaux
(`QuerySet.update()`, SQL direct, restauration de sauvegarde). Au premier
passage sur une base sans historique, pose l'état initial de chaque objet.

Jouée par le post_deploy : l'écart est daté au plus tard du déploiement.

Usage :
    python manage.py constater_historique_contenus
    python manage.py constater_historique_contenus --motif "update ciblé du 09/09"
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from envergo.nitrates import historique
from envergo.nitrates.models import CodePrescription, ContenuRichDSFR, RevisionContenu


class Command(BaseCommand):
    help = "Consigne dans l'historique les écarts base / dernière révision (PC, contenus riches)"

    def add_arguments(self, parser):
        parser.add_argument("--motif", default="")

    def handle(self, *args, **options):
        motif_constat = options["motif"] or (
            "Écart constaté entre la base et la dernière révision : écriture "
            "passée sans trace (update, SQL direct, restauration)."
        )
        initiaux = constats = suppressions = 0
        presents = {
            RevisionContenu.TYPE_PC: set(),
            RevisionContenu.TYPE_CONTENU_RICH: set(),
        }

        for objet in [*CodePrescription.objects.all(), *ContenuRichDSFR.objects.all()]:
            type_obj = historique.type_objet(objet)
            ident = historique.identifiant_metier(objet)
            presents[type_obj].add(ident)
            derniere = historique.derniere_revision(type_obj, ident)
            if (
                derniere is None
                or derniere.action == RevisionContenu.ACTION_SUPPRESSION
            ):
                action = RevisionContenu.ACTION_CREATION
                motif = options["motif"] or "État initial (ouverture de l'historique)."
            else:
                action = RevisionContenu.ACTION_CONSTAT
                motif = motif_constat
            with historique.contexte_revision(
                origine=RevisionContenu.ORIGINE_COMMANDE,
                source="constater_historique_contenus",
                motif=motif,
            ) as ctx:
                if historique.enregistrer(objet, ctx=ctx, action=action):
                    if action == RevisionContenu.ACTION_CREATION:
                        initiaux += 1
                    else:
                        constats += 1

        # Objets disparus sans trace de suppression.
        for type_obj, idents in presents.items():
            connus = (
                RevisionContenu.objects.filter(type_objet=type_obj)
                .values_list("identifiant", flat=True)
                .distinct()
            )
            for ident in set(connus) - idents:
                derniere = historique.derniere_revision(type_obj, ident)
                if derniere.action == RevisionContenu.ACTION_SUPPRESSION:
                    continue
                RevisionContenu.objects.create(
                    type_objet=type_obj,
                    identifiant=ident,
                    action=RevisionContenu.ACTION_SUPPRESSION,
                    champs_modifies=[],
                    instantane=derniere.instantane,
                    environnement=getattr(settings, "ENV_NAME", ""),
                    origine=RevisionContenu.ORIGINE_COMMANDE,
                    source="constater_historique_contenus",
                    motif=motif_constat,
                )
                suppressions += 1

        self.stdout.write(
            f"Historique : {initiaux} état(s) initial(aux), {constats} écart(s) "
            f"constaté(s), {suppressions} suppression(s) constatée(s)."
        )
