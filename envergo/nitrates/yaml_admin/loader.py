"""Chargement YAML round-trip via ruamel.yaml.

Distinct du loader pyyaml de yaml_tree/ qui sert a la validation et a la
moulinette : ici on garde l'arbre source (avec commentaires, ordre,
ancres) pour pouvoir le re-serialiser tel quel en phase 3bis (editeur).

Pas de cache : les specs sont en volume read-only, pas de hot-reload, et
on prefere relire pour avoir la version courante en cas d'edition externe.
"""

from io import StringIO
from pathlib import Path

from django.conf import settings
from ruamel.yaml import YAML


def _yaml() -> YAML:
    yaml = YAML(typ="rt")  # round-trip
    yaml.preserve_quotes = True
    yaml.width = 4096  # evite le wrap automatique des longues strings
    return yaml


def _specs_dir() -> Path:
    return Path(settings.NITRATES_SPECS_DIR)


def load_arbre_admin(name: str = "arbre_decision_national") -> dict:
    """Charge un arbre via ruamel round-trip. Renvoie un CommentedMap
    qui se manipule comme un dict standard mais conserve commentaires +
    ordre des cles."""
    path = _specs_dir() / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"Fichier YAML introuvable : {path}. "
            f"Verifier NITRATES_SPECS_DIR (actuel : {settings.NITRATES_SPECS_DIR})."
        )
    with path.open(encoding="utf-8") as f:
        return _yaml().load(f)


def load_raw(name: str = "arbre_decision_national") -> str:
    """Renvoie le YAML brut (texte) pour l'affichage cote a cote avec
    coloration syntaxique."""
    path = _specs_dir() / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Fichier YAML introuvable : {path}")
    return path.read_text(encoding="utf-8")


def dump_to_string(tree: dict) -> str:
    """Re-serialise un arbre charge round-trip. Sert au test de
    preservation pour 3bis."""
    buf = StringIO()
    _yaml().dump(tree, buf)
    return buf.getvalue()
