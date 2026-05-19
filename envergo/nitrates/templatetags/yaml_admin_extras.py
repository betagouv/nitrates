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
    "noeud_catalogue": "📋 Catalogue (calcul / SIG / référentiel)",
    "regle": "⚖️ Règle (interdiction, plafond, calculatrice…)",
    "renvoi_vers": "↪️ Renvoi vers une règle existante",
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


@register.simple_tag
def preview_url(arbre, path_str, tree_pk):
    """Construit l'URL preview du simulateur pour un noeud du draft.

    `arbre` : dict de l'arbre (root key "arbre").
    `path_str` : path slash-joined (ex: "n_zvn/q_occupation_sol/q_colza").
    `tree_pk` : pk du draft.

    Retourne `/simulateur/?draft_tree_id=<pk>&<param1>=<val1>...`
    Le simulateur cote vue (MoulinetteView) accepte ce param si l'user a
    les droits (cf. can_preview_tree).
    """
    from envergo.nitrates.yaml_admin.preview import (
        build_preview_url,
        compute_simulator_params,
    )

    if not path_str:
        path: tuple = ()
    else:
        path = tuple(p for p in path_str.split("/") if p)
    params = compute_simulator_params(arbre, path)
    return build_preview_url(tree_pk, params)
