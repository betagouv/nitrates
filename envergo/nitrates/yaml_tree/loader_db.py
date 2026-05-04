"""Loader DB de l'arbre de decision actif.

Source de verite runtime apres la migration de l'arbre YAML vers la table
`nitrates_decisiontree`. Le loader fichier (`loader.py`) reste utilise
pour la commande d'import et pour les tests qui valident le brouillon
disque.

Pas de cache au niveau du loader : la DB est rapide, et il faudra
invalider quand un nouveau tree est active. Le cache HTTP reste sur les
vues (`cache_page`).
"""

from io import StringIO

from ruamel.yaml import YAML

from envergo.nitrates.models import DecisionTree


def load_active_tree() -> dict:
    """Renvoie le contenu JSON de l'arbre actif.

    Leve `DecisionTree.DoesNotExist` si aucun tree n'est actif (cas
    anormal : migration ratee, prod sans donnees importees).
    """
    return DecisionTree.objects.get(status=DecisionTree.STATUS_ACTIVE).contenu


def load_active_tree_raw() -> str:
    """Renvoie le YAML brut (round-trip ruamel) de l'arbre actif.

    Utilise par le viewer admin pour la coloration syntaxique. Vide si
    `contenu_yaml_brut` n'a pas ete renseigne (import minimal).
    """
    return DecisionTree.objects.get(status=DecisionTree.STATUS_ACTIVE).contenu_yaml_brut


def load_active_tree_admin():
    """Parse `contenu_yaml_brut` via ruamel et retourne un CommentedMap.

    Pour le viewer admin : on a besoin d'un dict ordonne avec
    commentaires preserves (rendu identique au fichier source).
    """
    raw = load_active_tree_raw()
    return _parse_yaml_rt(raw)


def load_tree_admin(tree: DecisionTree):
    """Variante de `load_active_tree_admin` pour un tree arbitraire (n'importe
    quel statut). Utilise par le viewer multi-arbres (?tree_id=...)."""
    return _parse_yaml_rt(tree.contenu_yaml_brut)


def load_tree_raw(tree: DecisionTree) -> str:
    """YAML brut d'un tree arbitraire."""
    return tree.contenu_yaml_brut


def _parse_yaml_rt(raw: str):
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096
    return yaml.load(StringIO(raw))
