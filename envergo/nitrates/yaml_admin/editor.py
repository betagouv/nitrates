"""Service de mutation d'un draft YAML.

Toutes les operations passent par ce module :
  - update_node()  : modifie un noeud / regle / branche existant en place
  - add_branch()   : ajoute une branche a un noeud parent
  - update_branch_content() : remplit le contenu d'une branche (noeud / regle / renvoi)
  - delete_at()    : supprime un noeud / regle / branche

Chaque mutation :
  1. Valide localement (yaml_admin/grammar.py) avant de toucher au tree.
  2. Si KO : retourne un EditResult(ok=False, errors=[...]) sans modifier le tree.
  3. Si OK : enregistre une revision (DecisionTreeRevision.record), applique
     la mutation au dict, re-genere le YAML brut via ruamel round-trip,
     sauvegarde le tree. Le tout dans une transaction.

Pas de HTTP / Django views ici : ce module ne connait que des dicts et
le modele DecisionTree. Les endpoints htmx (etape 5c) appellent ces
fonctions et traduisent les EditResult en HTML.

Addressing :
  - `path` (suite d'ids de noeuds) pour reperer un noeud.
  - Pour reperer une branche d'un noeud : (parent_path, valeur) ; la valeur
    est unique parmi les branches d'un meme noeud.
  - Pour reperer une regle : path = parent_path + (valeur de la branche,)
    (la regle est dans la branche, pas un objet a part).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO

from django.db import transaction
from ruamel.yaml import YAML

from envergo.nitrates.models import DecisionTree, DecisionTreeRevision
from envergo.nitrates.yaml_admin.grammar import (
    FieldError,
    ValidationResult,
    get_allowed_child_kinds,
    validate_node_local,
)


@dataclass
class EditResult:
    """Resultat d'une operation de mutation."""

    ok: bool
    errors: list[FieldError] = field(default_factory=list)
    # Description courte pour la timeline / undo
    summary: str = ""

    @classmethod
    def success(cls, summary: str = "") -> "EditResult":
        return cls(ok=True, summary=summary)

    @classmethod
    def fail(cls, errors: list[FieldError]) -> "EditResult":
        return cls(ok=False, errors=errors)

    @classmethod
    def from_validation(cls, result: ValidationResult) -> "EditResult":
        return cls(ok=result.ok, errors=result.errors)


# ─── Lookups (lecture, pas de mutation) ────────────────────────────────────


def get_node_at(arbre: dict, path: tuple[str, ...]) -> dict | None:
    """Retourne le noeud (formulaire ou catalogue) au chemin donne, ou
    None s'il n'existe pas. `path` est une suite d'ids ; vide = racine."""
    racine = (arbre or {}).get("arbre", {}).get("noeud")
    if not racine:
        return None
    if not path:
        return racine
    if racine.get("id") != path[0]:
        return None
    current = racine
    for nid in path[1:]:
        found = None
        for branche in current.get("branches") or []:
            if isinstance(branche, dict) and isinstance(branche.get("noeud"), dict):
                if branche["noeud"].get("id") == nid:
                    found = branche["noeud"]
                    break
        if found is None:
            return None
        current = found
    return current


def get_branche_at(arbre: dict, parent_path: tuple[str, ...], valeur) -> dict | None:
    """Retourne la branche d'un noeud parent identifiee par sa valeur."""
    parent = get_node_at(arbre, parent_path)
    if parent is None:
        return None
    for branche in parent.get("branches") or []:
        if isinstance(branche, dict) and branche.get("valeur") == valeur:
            return branche
    return None


# ─── Mutations ──────────────────────────────────────────────────────────────


def update_node(
    tree: DecisionTree,
    path: tuple[str, ...],
    new_data: dict,
    user,
) -> EditResult:
    """Modifie un noeud existant (formulaire ou catalogue) en remplacant
    ses champs scalaires par ceux de `new_data`. Les `branches` ne sont
    pas touchees (utiliser add_branch / update_branch_content).
    """
    node = get_node_at(tree.contenu, path)
    if node is None:
        return EditResult.fail(
            [FieldError("", f"Noeud introuvable : {'/'.join(path)}.")]
        )
    kind = _kind_from_node(node)
    if kind is None:
        return EditResult.fail(
            [FieldError("", "Le noeud cible n'a pas de type_noeud reconnu.")]
        )
    # Merge logique : on accepte les champs scalaires, jamais branches.
    # Convention : une valeur vide ("") dans new_data signifie "retirer
    # cette cle du noeud" (sinon une cle optionnelle ne pourrait jamais
    # etre supprimee apres edition).
    merged = dict(node)
    for k, v in new_data.items():
        if k == "branches":
            continue
        if v == "" and k in merged:
            del merged[k]
        else:
            merged[k] = v
    res = validate_node_local(merged, kind, arbre=tree.contenu, own_path=path)
    if not res.ok:
        return EditResult.from_validation(res)
    return _commit_mutation(
        tree=tree,
        user=user,
        action=DecisionTreeRevision.ACTION_EDIT,
        target_path="/".join(path),
        description=f"Édition du nœud {node.get('id', '')}",
        mutate=lambda contenu: _apply_node_update(contenu, path, merged),
        summary=f"Nœud {node.get('id', '')} mis à jour",
    )


def update_regle(
    tree: DecisionTree,
    parent_path: tuple[str, ...],
    branche_valeur,
    new_data: dict,
    user,
) -> EditResult:
    """Modifie la regle attachee a une branche identifiee par
    (parent_path, branche_valeur)."""
    branche = get_branche_at(tree.contenu, parent_path, branche_valeur)
    if branche is None or "regle" not in branche:
        return EditResult.fail([FieldError("", "Règle introuvable à cet emplacement.")])
    current_regle = branche["regle"]
    merged = dict(current_regle)
    # Convention update_regle : new_data[key] = None signale "supprime cette
    # cle" (l'utilisateur a vide le champ via le form). Sinon update standard.
    for k, v in new_data.items():
        if v is None:
            merged.pop(k, None)
        else:
            merged[k] = v
    # a_completer : si False, on retire la cle plutot que de stocker
    # `a_completer: false` dans le YAML (bruit visuel).
    if merged.get("a_completer") is False:
        merged.pop("a_completer", None)
    # Pour l'unicite d'id on exclut le path "logique" de la regle. On
    # passe son propre id en own_path pour que l'arbre l'ignore.
    own_pseudo_path = parent_path + (current_regle.get("id", ""),)
    res = validate_node_local(
        merged, "regle", arbre=tree.contenu, own_path=own_pseudo_path
    )
    if not res.ok:
        return EditResult.from_validation(res)
    return _commit_mutation(
        tree=tree,
        user=user,
        action=DecisionTreeRevision.ACTION_EDIT,
        target_path=f"{'/'.join(parent_path)}#{branche_valeur}",
        description=f"Édition de la règle {current_regle.get('id', '')}",
        mutate=lambda contenu: _apply_regle_update(
            contenu, parent_path, branche_valeur, merged
        ),
        summary=f"Règle {current_regle.get('id', '')} mise à jour",
    )


def add_branch(
    tree: DecisionTree,
    parent_path: tuple[str, ...],
    branche_data: dict,
    user,
) -> EditResult:
    """Ajoute une branche a la liste de branches d'un noeud parent.
    `branche_data` doit au minimum porter `valeur`. Le contenu (noeud /
    regle / renvoi_vers) peut etre vide a ce stade : on cree juste le
    squelette de branche."""
    parent = get_node_at(tree.contenu, parent_path)
    if parent is None:
        return EditResult.fail([FieldError("", "Nœud parent introuvable.")])
    res = validate_node_local(branche_data, "branche")
    if not res.ok:
        return EditResult.from_validation(res)
    # Refus si une branche avec la meme valeur existe deja.
    valeur = branche_data.get("valeur")
    for b in parent.get("branches") or []:
        if isinstance(b, dict) and b.get("valeur") == valeur:
            return EditResult.fail(
                [
                    FieldError(
                        "valeur",
                        f"Une branche avec la valeur {valeur!r} existe deja "
                        f"sous ce noeud.",
                    )
                ]
            )
    return _commit_mutation(
        tree=tree,
        user=user,
        action=DecisionTreeRevision.ACTION_ADD,
        target_path="/".join(parent_path),
        description=f"Ajout de la branche {valeur!r} à {parent.get('id', '')}",
        mutate=lambda contenu: _apply_add_branch(contenu, parent_path, branche_data),
        summary=f"Branche {valeur!r} ajoutée",
    )


def update_branch_content(
    tree: DecisionTree,
    parent_path: tuple[str, ...],
    branche_valeur,
    content_kind: str,
    content_data: dict,
    user,
) -> EditResult:
    """Insere ou remplace le contenu d'une branche (noeud, regle ou
    renvoi_vers). `content_kind` est l'un des 7 kinds renvoyes par
    `get_allowed_child_kinds()` du parent + cas particuliers regle /
    renvoi.

    Si la branche a deja un contenu, il est remplace (apres validation
    du nouveau contenu). C'est l'operation typique pour "passer de
    branche vide a branche avec son nœud" en mode draft.
    """
    branche = get_branche_at(tree.contenu, parent_path, branche_valeur)
    if branche is None:
        return EditResult.fail([FieldError("", "Branche introuvable.")])

    # On valide :
    # 1. Le content_kind est autorise pour ce parent (niveau 2)
    allowed = get_allowed_child_kinds(tree.contenu, parent_path)
    if content_kind not in allowed:
        return EditResult.fail(
            [
                FieldError(
                    "",
                    f"Le type {content_kind!r} n'est pas autorise comme enfant "
                    f"de {('/'.join(parent_path)) or '(racine)'} "
                    f"(autorises : {', '.join(allowed) or 'aucun'}).",
                )
            ]
        )
    # 2. Le contenu lui-meme est valide (niveau 1)
    grammar_kind = _grammar_kind_from_content_kind(content_kind)
    res = validate_node_local(content_data, grammar_kind, arbre=tree.contenu)
    if not res.ok:
        return EditResult.from_validation(res)

    # On determine la cle de stockage dans la branche selon le content_kind.
    storage_key = _storage_key_from_content_kind(content_kind)

    return _commit_mutation(
        tree=tree,
        user=user,
        action=DecisionTreeRevision.ACTION_ADD,
        target_path=f"{'/'.join(parent_path)}#{branche_valeur}",
        description=f"Insertion d'un {content_kind} dans la branche {branche_valeur!r}",
        mutate=lambda contenu: _apply_set_branch_content(
            contenu, parent_path, branche_valeur, storage_key, content_data
        ),
        summary=f"{content_kind} ajouté dans la branche {branche_valeur!r}",
    )


def delete_branch(
    tree: DecisionTree,
    parent_path: tuple[str, ...],
    branche_valeur,
    user,
) -> EditResult:
    """Supprime une branche entiere d'un noeud parent (et tout son contenu)."""
    branche = get_branche_at(tree.contenu, parent_path, branche_valeur)
    if branche is None:
        return EditResult.fail([FieldError("", "Branche introuvable.")])
    return _commit_mutation(
        tree=tree,
        user=user,
        action=DecisionTreeRevision.ACTION_DELETE,
        target_path=f"{'/'.join(parent_path)}#{branche_valeur}",
        description=f"Suppression de la branche {branche_valeur!r}",
        mutate=lambda contenu: _apply_delete_branch(
            contenu, parent_path, branche_valeur
        ),
        summary=f"Branche {branche_valeur!r} supprimée",
    )


def reorder_branches(
    tree: DecisionTree,
    parent_path: tuple[str, ...],
    ordered_valeurs: list,
    user,
) -> EditResult:
    """Permute les `branches` d'un noeud parent selon l'ordre fourni.

    `ordered_valeurs` : liste des valeurs de branches (str/bool/int) dans
    le nouvel ordre desire. Doit etre un re-arrangement exact des valeurs
    existantes -- ni ajout, ni suppression. Permet de garder la mutation
    chirurgicale : on touche QUE l'ordre de la liste, pas le contenu des
    branches (donc pas de risque d'effacer un sous-arbre).

    Le contenu (noeud / regle / renvoi_vers) suit chaque branche puisqu'on
    re-ordonne les objets entiers.
    """
    parent = get_node_at(tree.contenu, parent_path)
    if parent is None:
        return EditResult.fail([FieldError("", "Nœud parent introuvable.")])

    branches = list(parent.get("branches") or [])
    if not branches:
        return EditResult.fail([FieldError("", "Aucune branche à réordonner.")])

    # Verification : les valeurs fournies doivent etre exactement les
    # memes que celles des branches existantes (set comparison).
    existing_valeurs = [b.get("valeur") for b in branches if isinstance(b, dict)]
    if sorted(map(str, existing_valeurs)) != sorted(map(str, ordered_valeurs)):
        return EditResult.fail(
            [
                FieldError(
                    "",
                    "Liste d'ordre invalide : doit etre un re-arrangement "
                    "exact des branches existantes (sans ajout ni suppression).",
                )
            ]
        )

    return _commit_mutation(
        tree=tree,
        user=user,
        action=DecisionTreeRevision.ACTION_EDIT,
        target_path="/".join(parent_path),
        description=f"Réordonnancement des branches de {parent.get('id', '')}",
        mutate=lambda contenu: _apply_reorder_branches(
            contenu, parent_path, ordered_valeurs
        ),
        summary=f"Branches de {parent.get('id', '')} réordonnées",
    )


def delete_node(
    tree: DecisionTree,
    path: tuple[str, ...],
    user,
) -> EditResult:
    """Supprime un noeud entier (et tout son sous-arbre).

    Note : on ne supprime pas la racine via cette fonction (verifier
    cote appelant).
    """
    if len(path) < 2:
        return EditResult.fail(
            [FieldError("", "On ne peut pas supprimer la racine de l'arbre.")]
        )
    node = get_node_at(tree.contenu, path)
    if node is None:
        return EditResult.fail([FieldError("", "Nœud introuvable.")])
    return _commit_mutation(
        tree=tree,
        user=user,
        action=DecisionTreeRevision.ACTION_DELETE,
        target_path="/".join(path),
        description=f"Suppression du nœud {node.get('id', '')}",
        mutate=lambda contenu: _apply_delete_node(contenu, path),
        summary=f"Nœud {node.get('id', '')} supprimé",
    )


# ─── Commit pipeline ───────────────────────────────────────────────────────


def _commit_mutation(
    tree: DecisionTree,
    user,
    action: str,
    target_path: str,
    description: str,
    mutate,
    summary: str,
) -> EditResult:
    """Pattern d'application d'une mutation :
       1. Enregistrer une revision avec snapshot d'avant
       2. Muter le contenu
       3. Re-generer le YAML brut
       4. Sauvegarder le tree
    Tout en transaction atomique : si quelque chose plante, rollback.
    """
    with transaction.atomic():
        DecisionTreeRevision.record(
            tree,
            action=action,
            user=user,
            target_path=target_path,
            description=description,
        )
        mutate(tree.contenu)
        tree.contenu_yaml_brut = _dump_yaml(tree.contenu)
        tree.save(update_fields=["contenu", "contenu_yaml_brut", "updated_at"])
    return EditResult.success(summary=summary)


def _dump_yaml(contenu: dict) -> str:
    """Re-serialise un dict en YAML round-trip ruamel. Si le dict est
    deja un CommentedMap (issu d'un load round-trip), les commentaires
    sont preserves. Sinon (dict pur Python), on dump basique."""
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096
    buf = StringIO()
    yaml.dump(contenu, buf)
    return buf.getvalue()


# ─── Mutators (pure dict ops) ──────────────────────────────────────────────


def _apply_node_update(contenu: dict, path: tuple[str, ...], merged: dict) -> None:
    node = get_node_at(contenu, path)
    if node is None:
        return
    # On preserve les branches existantes (pas dans merged).
    branches = node.get("branches")
    node.clear()
    node.update(merged)
    if branches is not None:
        node["branches"] = branches


def _apply_regle_update(
    contenu: dict,
    parent_path: tuple[str, ...],
    branche_valeur,
    merged: dict,
) -> None:
    branche = get_branche_at(contenu, parent_path, branche_valeur)
    if branche is None:
        return
    branche["regle"] = merged


def _apply_add_branch(
    contenu: dict, parent_path: tuple[str, ...], branche_data: dict
) -> None:
    parent = get_node_at(contenu, parent_path)
    if parent is None:
        return
    parent.setdefault("branches", []).append(dict(branche_data))


def _apply_set_branch_content(
    contenu: dict,
    parent_path: tuple[str, ...],
    branche_valeur,
    storage_key: str,
    content_data: dict,
) -> None:
    branche = get_branche_at(contenu, parent_path, branche_valeur)
    if branche is None:
        return
    # On efface les autres clefs de contenu pour respecter "exactement un de".
    for key in ("noeud", "regle", "renvoi_vers"):
        if key != storage_key and key in branche:
            del branche[key]
    branche[storage_key] = content_data


def _apply_delete_branch(
    contenu: dict, parent_path: tuple[str, ...], branche_valeur
) -> None:
    parent = get_node_at(contenu, parent_path)
    if parent is None:
        return
    parent["branches"] = [
        b
        for b in (parent.get("branches") or [])
        if not (isinstance(b, dict) and b.get("valeur") == branche_valeur)
    ]


def _apply_reorder_branches(
    contenu: dict, parent_path: tuple[str, ...], ordered_valeurs: list
) -> None:
    parent = get_node_at(contenu, parent_path)
    if parent is None:
        return
    branches = list(parent.get("branches") or [])
    # Index les branches par valeur (str pour matcher les query params).
    by_valeur = {}
    for b in branches:
        if isinstance(b, dict):
            by_valeur[str(b.get("valeur"))] = b
    new_branches = []
    for v in ordered_valeurs:
        b = by_valeur.get(str(v))
        if b is not None:
            new_branches.append(b)
    # Garde-fou : si on a perdu des branches (cas impossible vu la
    # verification dans reorder_branches), on remet tout en queue.
    if len(new_branches) != len(branches):
        seen_ids = {id(b) for b in new_branches}
        for b in branches:
            if id(b) not in seen_ids:
                new_branches.append(b)
    parent["branches"] = new_branches


def _apply_delete_node(contenu: dict, path: tuple[str, ...]) -> None:
    """Supprime un noeud descendant. On enleve la branche qui le porte
    (la branche entiere disparait : un noeud ne peut pas etre detache
    de sa branche parente)."""
    parent_path = path[:-1]
    parent = get_node_at(contenu, parent_path)
    if parent is None:
        return
    target_id = path[-1]
    parent["branches"] = [
        b
        for b in (parent.get("branches") or [])
        if not (
            isinstance(b, dict)
            and isinstance(b.get("noeud"), dict)
            and b["noeud"].get("id") == target_id
        )
    ]


# ─── Helpers de mapping ─────────────────────────────────────────────────────


def _kind_from_node(node: dict) -> str | None:
    tn = node.get("type_noeud")
    if tn == "formulaire":
        return "noeud_formulaire"
    if tn == "catalogue":
        return "noeud_catalogue"
    return None


# Mapping content_kind (renvoye par get_allowed_child_kinds) -> kind grammar
# (utilise par validate_node_local).
_GRAMMAR_KIND = {
    "noeud_formulaire_culture": "noeud_formulaire",
    "noeud_formulaire_sous_culture": "noeud_formulaire",
    "noeud_formulaire_type_fertilisant": "noeud_formulaire",
    "noeud_formulaire_complement": "noeud_formulaire",
    "noeud_catalogue": "noeud_catalogue",
    "regle": "regle",
    "renvoi_vers": "renvoi_vers",
}


def _grammar_kind_from_content_kind(content_kind: str) -> str:
    return _GRAMMAR_KIND.get(content_kind, content_kind)


# Mapping content_kind -> cle dans la branche (noeud / regle / renvoi_vers).
def _storage_key_from_content_kind(content_kind: str) -> str:
    if content_kind.startswith("noeud_"):
        return "noeud"
    if content_kind == "regle":
        return "regle"
    if content_kind == "renvoi_vers":
        return "renvoi_vers"
    raise ValueError(f"content_kind inconnu : {content_kind}")
