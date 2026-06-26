"""Chargement caché des contenus riches (carte #131).

Même pattern que `load_referentiels()` : un cache process-local invalidé par
signal post_save / post_delete sur le modèle (cf. apps.py). Peu d'objets, on
cache tout le mapping {cle: blocs} en une fois.
"""

from functools import lru_cache


@lru_cache(maxsize=1)
def _load_contenus_caches() -> dict:
    """Mapping {cle: liste_de_blocs} de tous les ContenuRichDSFR.

    Import du modèle dans la fonction pour éviter les imports circulaires au
    chargement de l'app (le modèle importe Django, pas l'inverse)."""
    from envergo.nitrates.models import ContenuRichDSFR

    return {c.cle: c.liste_blocs for c in ContenuRichDSFR.objects.all()}


def load_blocs(cle: str) -> list:
    """Renvoie la liste de blocs du contenu `cle`, ou [] si absent.

    Ne lève jamais : un contenu manquant (pas encore seedé) rend une zone
    vide plutôt qu'une 500 sur le panneau public."""
    return _load_contenus_caches().get(cle, []) or []


def invalider_cache_contenu_rich(*args, **kwargs) -> None:
    """Vide le cache. Receiver de signal (signature *args/**kwargs) branché
    sur post_save / post_delete de ContenuRichDSFR dans apps.py."""
    _load_contenus_caches.cache_clear()
