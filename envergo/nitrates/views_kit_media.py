"""Page « Kit média » du pied de page (#293).

Le kit (zip livré par la design, version validée du 14/10/2026) est servi en
fichier statique : pas de S3, il suit le code. La liste « Ce que contient le
kit » décrit ce zip, d'où un template codé plutôt qu'un contenu éditable en
admin : changer de kit = changer le zip ET le texte dans le même commit.
"""

import os

from django.contrib.staticfiles import finders
from django.views.generic import TemplateView

KIT_MEDIA_STATIC = "nitrates/kit-media/kit-communication-nitratinfo.zip"


def taille_kit_media():
    """Taille du zip en octets, None si le fichier est introuvable."""
    chemin = finders.find(KIT_MEDIA_STATIC)
    return os.path.getsize(chemin) if chemin else None


def taille_lisible(octets):
    """« 1,6 Mo », « 850 Ko » : unités du DSFR (filesizeformat donne « Mio »)."""
    if octets >= 1_000_000:
        return f"{octets / 1_000_000:.1f} Mo".replace(".", ",")
    return f"{max(1, round(octets / 1000))} Ko"


class KitMediaView(TemplateView):
    template_name = "nitrates/kit_media.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        taille = taille_kit_media()
        context.update(
            {
                "titre": "Kit média",
                "kit_static": KIT_MEDIA_STATIC,
                "kit_nom_fichier": os.path.basename(KIT_MEDIA_STATIC),
                "kit_taille": taille_lisible(taille) if taille else None,
            }
        )
        return context
