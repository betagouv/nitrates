"""Chargement des YAML depuis NITRATES_SPECS_DIR.

Cache lru pour eviter de relire le fichier a chaque appel. En dev avec
runserver_plus, le reload du serveur invalide le cache au reload du module.
Pour invalider manuellement : `load_arbre.cache_clear()`.
"""

from functools import lru_cache
from pathlib import Path

import yaml
from django.conf import settings


def _specs_dir() -> Path:
    return Path(settings.NITRATES_SPECS_DIR)


def _load_yaml(filename: str) -> dict:
    path = _specs_dir() / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Fichier YAML introuvable : {path}. "
            f"Verifier NITRATES_SPECS_DIR (actuel : {settings.NITRATES_SPECS_DIR})."
        )
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=8)
def load_arbre(name: str = "arbre_decision_national") -> dict:
    """Charge un arbre de decision (national ou PAR).

    name peut etre :
      - "arbre_decision_national" (defaut)
      - "arbre_decision_par_R44" pour une region
      - n'importe quel autre nom de fichier YAML present dans specs/
    """
    return _load_yaml(f"{name}.yaml")


@lru_cache(maxsize=1)
def load_referentiels() -> dict:
    """Charge referentiels.yaml. Listes fermees : types_fertilisants, cultures,
    codes_prescription, notes, evenements_phenologiques, regions, etc.
    """
    return _load_yaml("referentiels.yaml")
