"""Chargement caché du glossaire (carte #110).

Même pattern que `loader.py` (contenus riches) : cache process-local invalidé
par signaux post_save / post_delete sur ContenuRichDSFR (cf. apps.py). Peu de
définitions (~20), on construit tout d'un coup :

- `load_definitions()` : les définitions ordonnées (page Aide & définitions,
  panneau flottant du simulateur) ;
- `load_index_termes()` : l'index (variante → cle) TRIÉ par longueur de
  variante décroissante — le tri vit ici, une fois, pour que le matching
  "longest-first" du filtre |glossaire et du JS soit gratuit à chaque rendu.
"""

from functools import lru_cache


@lru_cache(maxsize=1)
def _load_glossaire_cache() -> dict:
    """{"definitions": [ContenuRichDSFR...], "index_termes": [(variante, cle)...]}.

    Import du modèle dans la fonction pour éviter les imports circulaires au
    chargement de l'app (cf. loader.py)."""
    from envergo.nitrates.models_contenu_rich import TYPE_DEFINITION, ContenuRichDSFR

    definitions = list(ContenuRichDSFR.objects.filter(type_contenu=TYPE_DEFINITION))
    index = []
    for d in definitions:
        # Le titre public matche toujours ; les termes déclencheurs ajoutent
        # les variantes (« C/N » et « rapport C/N »...). Dédoublonnage
        # insensible à la casse pour ne pas gonfler l'alternation regex.
        vus = set()
        for variante in [d.titre_public, *d.liste_termes]:
            v = (variante or "").strip()
            if v and v.lower() not in vus:
                vus.add(v.lower())
                index.append((v, d.cle))
    # Longest-first : « interculture longue » doit matcher avant
    # « interculture », quel que soit l'ordre de saisie dans l'admin/YAML.
    index.sort(key=lambda t: len(t[0]), reverse=True)
    return {"definitions": definitions, "index_termes": index}


def load_definitions() -> list:
    """Les ContenuRichDSFR de type definition, ordonnés par cle (Meta)."""
    return _load_glossaire_cache()["definitions"]


def load_index_termes() -> list:
    """[(variante, cle)...] trié par longueur de variante décroissante."""
    return _load_glossaire_cache()["index_termes"]


def invalider_cache_glossaire(*args, **kwargs) -> None:
    """Vide le cache. Receiver de signal (signature *args/**kwargs) branché
    sur post_save / post_delete de ContenuRichDSFR dans apps.py."""
    _load_glossaire_cache.cache_clear()
