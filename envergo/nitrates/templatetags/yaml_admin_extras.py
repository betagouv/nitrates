"""Filtres et tags template pour le viewer YAML admin (phase 2bis)."""

from django import template
from django.utils.html import escape

from envergo.nitrates.yaml_admin.tags import get_tags
from envergo.nitrates.yaml_admin.tags import regime_tag as _regime_tag

register = template.Library()


@register.filter
def tags_for(data, kind):
    if not isinstance(data, dict):
        return []
    return get_tags(kind, data)


@register.filter
def regime_tag(regime):
    """Tag visuel pour un `regime` de periode (interdiction, autorisation...)."""
    return _regime_tag(regime)


@register.filter(name="split")
def split_filter(value, sep=","):
    """Filtre simple pour splitter une chaine dans un template."""
    if not value:
        return []
    return str(value).split(sep)


@register.simple_tag
def join_path(ancestors_str, node_id):
    """Concatene un parent_path string avec un id pour produire le path
    courant. ancestors_str peut etre vide (racine)."""
    if ancestors_str:
        return f"{ancestors_str}/{node_id}"
    return node_id


@register.simple_tag
def is_open(open_paths, path):
    """True si ce path est dans le set des noeuds ouverts."""
    if open_paths is None:
        return False
    return path in open_paths


@register.simple_tag
def fold_link(querystring_base, expand_paths, expand_deep_paths, path, deep=False):
    """Construit l'URL pour ouvrir/refermer un noeud.

    deep=False : ajoute le path dans expand
    deep=True  : ajoute le path dans expand_deep (recursif)

    Conserve l'etat existant des autres noeuds (toggle implicite : si
    le path est deja dans la liste cible, on l'enleve, sinon on l'ajoute)."""
    expand = list(expand_paths or [])
    expand_deep = list(expand_deep_paths or [])

    if deep:
        if path in expand_deep:
            expand_deep = [p for p in expand_deep if p != path]
        else:
            expand_deep.append(path)
    else:
        if path in expand:
            expand = [p for p in expand if p != path]
        else:
            expand.append(path)

    parts = []
    if querystring_base:
        parts.append(querystring_base)
    parts += [f"expand={escape(p)}" for p in expand]
    parts += [f"expand_deep={escape(p)}" for p in expand_deep]
    return "?" + "&".join(parts) if parts else "?"


_KIND_LABELS = {
    "noeud_formulaire_culture": "🌱 Question — culture",
    "noeud_formulaire_sous_culture": "🌿 Question — sous-culture",
    "noeud_formulaire_type_fertilisant": "💧 Question — type de fertilisant",
    "noeud_formulaire_complement": "➕ Question — complément",
    "noeud_catalogue": "📋 Catalogue (SIG / référentiel / calcul / expression)",
    "regle": "⚖️ Règle (interdiction, plafond, calculatrice…)",
    "renvoi_vers": "↪️ Renvoi vers une règle existante",
    "renvoi_arbre": "🔀 Renvoi vers un autre arbre (région / national)",
    "feuille_vide": "∅ Feuille vide (réponse sans règle — PAR/ZAR)",
}


@register.filter
def kind_label(kind):
    """Libelle humain pour un kind d'enfant autorise."""
    return _KIND_LABELS.get(kind, kind)


@register.simple_tag
def reset_link(querystring_base):
    """Lien qui efface tous les expand/expand_deep mais garde vue + filtre."""
    if querystring_base:
        return "?" + querystring_base
    return "?"


def _activation_point(tree_pk):
    """Point reel dans la couche SIG d'activation de l'arbre `tree_pk` (ex ZAR),
    pour que la preview tombe DANS la zone. None si l'arbre n'a pas de couche
    (PAN/PAR region) -> la preview retombe sur le resolveur SIG par defaut."""
    from envergo.nitrates.models import DecisionTree
    from envergo.nitrates.yaml_admin.preview import point_for_activation_map

    try:
        tree = DecisionTree.objects.select_related("activation_map").get(pk=tree_pk)
    except (DecisionTree.DoesNotExist, ValueError, TypeError):
        return None
    return point_for_activation_map(tree.activation_map)


@register.simple_tag
def preview_url_regle(arbre, parent_path_str, valeur, tree_pk, tree_status="draft"):
    """Construit l'URL preview pour une règle (feuille) d'une branche.

    Une règle est dans une branche d'un nœud parent. On calcule les params
    via le path parent + on injecte {champ_du_parent: valeur} pour que le
    simulateur descende jusqu'à la branche correspondante.
    """
    from envergo.nitrates.yaml_admin import editor
    from envergo.nitrates.yaml_admin.preview import (
        build_preview_url,
        compute_simulator_params,
    )

    if not parent_path_str:
        parent_path: tuple = ()
    else:
        parent_path = tuple(p for p in parent_path_str.split("/") if p)
    # Champ du parent + valeur de la branche : permet au simulateur de
    # descendre jusqu'à la regle ciblee. On passe la combinaison comme
    # leaf_branch a compute_simulator_params pour qu'elle soit aussi prise
    # en compte par le resolveur SIG / cascade form (typiquement quand la
    # branche feuille est sur un catalogue note_5/montagne).
    parent = editor.get_node_at(arbre, parent_path)
    leaf_branch = None
    if isinstance(parent, dict):
        champ = parent.get("champ")
        if champ and valeur is not None:
            leaf_branch = (champ, _coerce_valeur_for_constraint(valeur))
    params = compute_simulator_params(
        arbre,
        parent_path,
        leaf_branch=leaf_branch,
        point_override=_activation_point(tree_pk),
    )
    use_draft_id = tree_status != "active"
    return build_preview_url(tree_pk if use_draft_id else None, params)


def _coerce_valeur_for_constraint(v):
    """Garde le typage natif (bool/str) pour matcher les comparaisons des
    resolveurs SIG (qui utilisent `is True`, `== "montagne_note_6"`, etc.).
    Sert pour leaf_branch ; pour les params URL on continue d'utiliser
    `_stringify_valeur_for_url`."""
    return v


def _stringify_valeur_for_url(v):
    if v is True:
        return "True"
    if v is False:
        return "False"
    return str(v)


@register.simple_tag
def preview_url(arbre, path_str, tree_pk, tree_status="draft"):
    """Construit l'URL preview du simulateur pour un noeud.

    `arbre` : dict de l'arbre (root key "arbre").
    `path_str` : path slash-joined (ex: "n_zvn/q_occupation_sol/q_colza").
    `tree_pk` : pk du tree.
    `tree_status` : "draft" / "active" / "archive". Si "active" on n'ajoute
       pas `draft_tree_id` (le simulateur charge deja l'actif par defaut).

    Retourne `/simulateur/?[draft_tree_id=<pk>&]<param1>=<val1>...`
    """
    from envergo.nitrates.yaml_admin.preview import (
        build_preview_url,
        compute_simulator_params,
    )

    if not path_str:
        path: tuple = ()
    else:
        path = tuple(p for p in path_str.split("/") if p)
    params = compute_simulator_params(
        arbre, path, point_override=_activation_point(tree_pk)
    )
    # Si on previsualise un draft (statut != active), on injecte draft_tree_id.
    # Sur l'arbre actif, l'URL n'a pas besoin de ce param (le simulateur le
    # charge par defaut) -- ca evite une URL avec un id qui pointe sur l'actif.
    use_draft_id = tree_status != "active"
    return build_preview_url(tree_pk if use_draft_id else None, params)


@register.simple_tag(takes_context=True)
def admin_url_for_resultat(context, chemin, draft_tree_id=None, tree_pk=None):
    """Lien retour depuis le simulateur (panneau debug "Chemin parcouru")
    vers l'admin YAML, ciblé sur le dernier nœud du chemin de résolution.

    Symétrique du bouton ↗ depuis l'admin vers le simulateur.

    - Si `draft_tree_id` est fourni, on cible ce tree (perm verifiee via
      can_preview_tree).
    - Sinon si `tree_pk` est fourni (= l'arbre qui a EMIS la regle dans la
      cascade, PAN/PAR/ZAR), on cible CET arbre.
    - Sinon, fallback sur le PAN national.
    - Visible uniquement pour staff (= acces admin YAML).
    Retourne "" si l'utilisateur ne peut pas / n'a rien a voir.
    """
    user = getattr(context.get("request"), "user", None)
    if not user or not getattr(user, "is_staff", False):
        return ""
    if not chemin:
        return ""

    from django.utils import timezone

    from envergo.nitrates.models import DecisionTree
    from envergo.nitrates.permissions import can_preview_tree

    tree = None
    is_draft = False
    if draft_tree_id:
        try:
            tree = DecisionTree.objects.filter(pk=int(draft_tree_id)).first()
        except (TypeError, ValueError):
            tree = None
        if tree is None or not can_preview_tree(user, tree):
            return ""
        is_draft = tree.status == DecisionTree.STATUS_DRAFT
    elif tree_pk:
        # Arbre qui a reellement emis la regle (cascade PAN/PAR/ZAR).
        try:
            tree = DecisionTree.objects.filter(pk=int(tree_pk)).first()
        except (TypeError, ValueError):
            tree = None
        if tree is None:
            return ""
        is_draft = tree.status == DecisionTree.STATUS_DRAFT
    else:
        tree = DecisionTree.objects.filter(
            status=DecisionTree.STATUS_ACTIVE, scope=DecisionTree.SCOPE_NATIONAL
        ).first()
        if tree is None:
            return ""

    # `chemin` = liste d'ids du parcours (ex: ["n_zvn", "q_occupation_sol",
    # "n_zone_note_5", "r_truc"]). Le dernier est la feuille resolue.
    # On construit la liste des paths cumulatifs pour les params expand=,
    # ce qui depliera la cascade jusqu'a la feuille.
    parts = [str(p) for p in chemin if p]
    cumul: list[str] = []
    prefix = ""
    for p in parts:
        prefix = f"{prefix}/{p}" if prefix else p
        cumul.append(prefix)

    # Choix du mode :
    # - actif : toujours lecture (l'edition se fait via un draft)
    # - draft + le user detient deja un lock valide : edition (cas nominal,
    #   on continue le travail en cours sans creer un nouveau draft fantome)
    # - draft + verrouille par un autre OU sans lock : lecture (laisse l'user
    #   decider d'acquerir le lock depuis l'admin)
    mode = "lecture"
    if is_draft and tree.locked_by_id == user.pk and tree.locked_at is not None:
        if tree.locked_at >= timezone.now() - DecisionTree.LOCK_TIMEOUT:
            mode = "edition"

    from urllib.parse import urlencode

    qs = [("tree_id", str(tree.pk)), ("mode", mode)]
    for path in cumul:
        qs.append(("expand", path))
    # Fragment d'ancre : conforme au _noeud.html (id="node-{{ path|slugify }}").
    last_path = cumul[-1] if cumul else ""
    fragment = ""
    if last_path:
        from django.utils.text import slugify

        fragment = "#node-" + slugify(last_path)
    return f"/admin/nitrates/arbre-decision/?{urlencode(qs)}{fragment}"
