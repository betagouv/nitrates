from django.apps import AppConfig


class NitratesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "envergo.nitrates"

    def ready(self):
        # Invalidation du cache de load_referentiels() des qu'un modele
        # referentiel est cree / modifie / supprime (seed, edition admin).
        # Sans ca, le cache process-local servirait des donnees perimees
        # apres une edition. cf. loader.invalider_cache_referentiels.
        from django.db.models.signals import post_delete, post_save

        from envergo.nitrates.models_referentiels import (
            BrancheCulturale,
            CodePrescription,
            Culture,
            EvenementPhenologique,
            Fertilisant,
            GroupeCultureUI,
            NoteReglementaire,
        )
        from envergo.nitrates.yaml_tree.loader import invalider_cache_referentiels

        modeles_referentiel = (
            GroupeCultureUI,
            BrancheCulturale,
            Culture,
            Fertilisant,
            NoteReglementaire,
            CodePrescription,
            EvenementPhenologique,
        )
        for modele in modeles_referentiel:
            post_save.connect(
                invalider_cache_referentiels,
                sender=modele,
                dispatch_uid=f"invalider_ref_{modele.__name__}_save",
            )
            post_delete.connect(
                invalider_cache_referentiels,
                sender=modele,
                dispatch_uid=f"invalider_ref_{modele.__name__}_delete",
            )

        # Meme mecanisme pour les contenus riches editables (carte #131) :
        # invalider le cache des qu'un ContenuRichDSFR est edite dans l'admin.
        from envergo.nitrates.contenu_rich.loader import invalider_cache_contenu_rich
        from envergo.nitrates.models_contenu_rich import ContenuRichDSFR

        post_save.connect(
            invalider_cache_contenu_rich,
            sender=ContenuRichDSFR,
            dispatch_uid="invalider_contenu_rich_save",
        )
        post_delete.connect(
            invalider_cache_contenu_rich,
            sender=ContenuRichDSFR,
            dispatch_uid="invalider_contenu_rich_delete",
        )
