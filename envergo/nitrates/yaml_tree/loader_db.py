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

from django.db.models import Q
from ruamel.yaml import YAML

from envergo.nitrates.models import DecisionTree


def select_active_tree(catalog: dict) -> dict:
    """Selectionne le contenu de l'arbre actif le plus specifique pour ce point.

    Data-driven (pas de cascade if/elif) : chaque DecisionTree actif declare
    une zone d'activation (national / region / couche SIG) et un poids. On
    construit dynamiquement le predicat d'activation a partir du catalog et on
    retient le candidat active de poids MAX.

    Resolution metier : ZAR (poids max) > PAR region > PAN (filet, matche
    partout). Le PAN est toujours candidat -> il y a toujours un resultat tant
    qu'un arbre national actif existe.

    Leve `DecisionTree.DoesNotExist` si aucun arbre applicable (PAN manquant).
    """
    region_code = catalog.get("region_code") or ""
    zar_zone_id = catalog.get("zar_zone_id")

    actifs = DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE)

    # Predicat d'activation construit a la volee : on n'ajoute la branche
    # region/zar que si le contexte fournit l'info correspondante. Ajouter un
    # scope futur (dept, bassin) = une clause Q de plus, zero if metier.
    activation_q = Q(scope=DecisionTree.SCOPE_NATIONAL)  # matche toujours
    if region_code:
        activation_q |= Q(scope=DecisionTree.SCOPE_REGION, region_code=region_code)
    if zar_zone_id is not None:
        # Filtrage par PK de zone (indexe) -- meme pattern perf que
        # MoulinetteNitrates.get_criteria (evite un ST_Intersects exact).
        activation_q |= Q(
            scope=DecisionTree.SCOPE_ZAR,
            activation_map__zones__id=zar_zone_id,
        )

    tree = actifs.filter(activation_q).order_by("-weight", "-activated_at").first()
    if tree is None:
        raise DecisionTree.DoesNotExist(
            "Aucun arbre actif applicable (PAN manquant ?)."
        )
    return tree.contenu


def active_national_tree_qs():
    """Queryset des arbres PAN actifs (scope=national).

    Pour les sites admin/form qui font une requete ORM directe (queryset, pas
    `contenu`). La structure du formulaire se base toujours sur le PAN.
    """
    return DecisionTree.objects.filter(
        status=DecisionTree.STATUS_ACTIVE, scope=DecisionTree.SCOPE_NATIONAL
    )


def load_active_tree() -> dict:
    """Renvoie le contenu JSON de l'arbre PAN actif (scope=national).

    Source de verite du FORMULAIRE et des seeds : la structure des questions
    se base toujours sur le PAN. La selection PAN/PAR/ZAR pour l'EVALUATION
    passe par `select_active_tree`.

    Leve `DecisionTree.DoesNotExist` si aucun PAN actif (cas anormal :
    migration ratee, prod sans donnees importees).
    """
    return DecisionTree.objects.get(
        status=DecisionTree.STATUS_ACTIVE, scope=DecisionTree.SCOPE_NATIONAL
    ).contenu


def load_tree_by_id(tree_pk: int) -> dict:
    """Renvoie le contenu JSON d'un tree par son pk. Pour le mode preview
    d'un brouillon : le simulateur charge un draft specifique au lieu de
    l'actif. Leve `DecisionTree.DoesNotExist` si l'id n'existe pas.

    Securite : pas de check d'autorisation ici, c'est a l'appelant de
    valider que l'utilisateur a le droit de voir ce tree.
    """
    return DecisionTree.objects.get(pk=tree_pk).contenu


def load_active_tree_raw() -> str:
    """Renvoie le YAML brut (round-trip ruamel) de l'arbre PAN actif.

    Utilise par le viewer admin pour la coloration syntaxique. Vide si
    `contenu_yaml_brut` n'a pas ete renseigne (import minimal).
    """
    return DecisionTree.objects.get(
        status=DecisionTree.STATUS_ACTIVE, scope=DecisionTree.SCOPE_NATIONAL
    ).contenu_yaml_brut


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
