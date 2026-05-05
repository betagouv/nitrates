"""Decision : quels noeuds doivent etre ouverts au rendu ?

Regles, dans l'ordre de priorite (premiere qui matche gagne) :

  1. Filtre actif : on ouvre le noeud si l'un de ses **descendants stricts**
     correspond au filtre. Le noeud qui matche lui-meme reste ferme : on
     veut voir son titre dans la liste, pas son contenu interne. Cliquer
     sur le chevron ou ▾▾ permet d'ouvrir au cas par cas.

  2. expand_deep contient un path qui couvre ce noeud (le noeud lui-meme
     ou un de ses ancetres) : ouvert.

  3. expand contient le path exact de ce noeud : ouvert.

  4. Defaut : ouvert si profondeur <= 1 (racine et ses enfants directs),
     ferme sinon. Evite l'effet "spam visuel".

Le path d'un noeud est une chaine slash-separee construite a partir des
ids successifs des noeuds rencontres (les valeurs de branches sont
sautees pour rester court et stable).
"""

from __future__ import annotations

from envergo.nitrates.yaml_admin.tags import matches_filter, subtree_matches


def _strict_descendant_matches(filtre: str, noeud: dict) -> bool:
    """Au moins un descendant strict de noeud (= dans une de ses branches,
    a n'importe quel niveau) matche le filtre. Exclut noeud lui-meme."""
    for branche in noeud.get("branches") or []:
        if not isinstance(branche, dict):
            continue
        if "regle" in branche and isinstance(branche["regle"], dict):
            if matches_filter(filtre, "regle", branche["regle"]):
                return True
        if "renvoi_vers" in branche:
            if matches_filter(filtre, "renvoi_vers", branche):
                return True
        if "noeud" in branche:
            if subtree_matches(filtre, branche["noeud"]):
                return True
    return False


def node_path(ancestors_ids: list[str], node_id: str) -> str:
    """Construit le path stable d'un noeud a partir des ids ancetres."""
    return "/".join([*ancestors_ids, node_id])


def compute_open_paths(
    racine: dict,
    filtre: str = "",
    expand: set[str] | None = None,
    expand_deep: set[str] | None = None,
) -> set[str]:
    """Renvoie l'ensemble des paths de noeuds qui doivent etre ouverts."""
    expand = expand or set()
    expand_deep = expand_deep or set()
    opened: set[str] = set()
    if not racine:
        return opened
    _walk(racine, [], filtre, expand, expand_deep, opened, depth=0)
    return opened


def _walk(
    noeud: dict,
    ancestors_ids: list[str],
    filtre: str,
    expand: set[str],
    expand_deep: set[str],
    opened: set[str],
    depth: int,
) -> None:
    nid = noeud.get("id")
    if not nid:
        return
    path = node_path(ancestors_ids, nid)

    is_open = _decide(noeud, path, ancestors_ids, filtre, expand, expand_deep, depth)
    if is_open:
        opened.add(path)

    for branche in noeud.get("branches") or []:
        if isinstance(branche, dict) and "noeud" in branche:
            _walk(
                branche["noeud"],
                ancestors_ids + [nid],
                filtre,
                expand,
                expand_deep,
                opened,
                depth + 1,
            )


def _decide(
    noeud: dict,
    path: str,
    ancestors_ids: list[str],
    filtre: str,
    expand: set[str],
    expand_deep: set[str],
    depth: int,
) -> bool:
    # 1. Filtre actif l'emporte : on ouvre uniquement si un descendant strict
    # matche. Le noeud qui matche lui-meme reste ferme (on voit son titre,
    # pas son contenu).
    if filtre:
        return _strict_descendant_matches(filtre, noeud)

    # 2. expand_deep : noeud couvert par un path deep.
    if path in expand_deep:
        return True
    for i in range(len(ancestors_ids)):
        ancestor_path = "/".join(ancestors_ids[: i + 1])
        if ancestor_path in expand_deep:
            return True

    # 3. expand exact.
    if path in expand:
        return True

    # 4. Defaut : profondeur <= 1.
    return depth <= 1
