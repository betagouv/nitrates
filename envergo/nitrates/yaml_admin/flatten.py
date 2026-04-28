"""Aplatissement d'un arbre charge en sequence d'entrees rendables.

Le template iterera sur cette sequence sans recursion. Chaque entree
porte la profondeur (pour l'indentation), un chemin stable (pour
generer un id html ancre, ou pour les futurs endpoints d'edition), et
le type d'objet (`noeud`, `branche`, `regle`, `renvoi_vers`).

Cet utilitaire est tolerant aux noeuds non finalises : si un champ
attendu manque, on yield quand meme l'entree avec un drapeau qui sera
rendu visuellement (badge "a_completer").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class TreeEntry:
    """Une ligne a rendre dans le viewer."""

    kind: str  # "noeud" | "branche" | "regle" | "renvoi_vers"
    depth: int
    path: tuple[str, ...]  # suite d'ids/valeurs de branches, stable et unique
    data: Any  # dict du noeud/regle, ou {valeur, libelle, target} pour renvoi
    parent_path: tuple[str, ...] = field(default=())

    @property
    def path_str(self) -> str:
        """Chemin serialise pour les ids HTML et URLs futures."""
        return "/".join(self.path) if self.path else "(racine)"


def iter_entries(arbre: dict) -> Iterator[TreeEntry]:
    """Aplatissement DFS de l'arbre charge.

    `arbre` : structure complete chargee (avec metadata, arbre.noeud,
    plafonnements eventuels). On itere uniquement sur arbre.noeud
    (les plafonnements top-level peuvent etre ajoutes ulterieurement
    si besoin d'affichage dedie).
    """
    racine = (arbre or {}).get("arbre", {}).get("noeud")
    if not racine:
        return
    yield from _walk_noeud(racine, depth=0, path=(), parent_path=())


def _walk_noeud(
    noeud: dict, depth: int, path: tuple[str, ...], parent_path: tuple[str, ...]
) -> Iterator[TreeEntry]:
    nid = noeud.get("id") or "(noeud-sans-id)"
    node_path = path + (nid,)
    yield TreeEntry(
        kind="noeud", depth=depth, path=node_path, data=noeud, parent_path=parent_path
    )
    for branche in noeud.get("branches") or []:
        yield from _walk_branche(branche, depth=depth + 1, parent_path=node_path)


def _walk_branche(
    branche: dict, depth: int, parent_path: tuple[str, ...]
) -> Iterator[TreeEntry]:
    valeur = branche.get("valeur")
    branche_path = parent_path + (f"={valeur!r}",)
    yield TreeEntry(
        kind="branche",
        depth=depth,
        path=branche_path,
        data=branche,
        parent_path=parent_path,
    )
    if "noeud" in branche:
        yield from _walk_noeud(
            branche["noeud"],
            depth=depth + 1,
            path=branche_path,
            parent_path=branche_path,
        )
    elif "regle" in branche:
        regle = branche["regle"]
        rid = regle.get("id") or "(regle-sans-id)"
        yield TreeEntry(
            kind="regle",
            depth=depth + 1,
            path=branche_path + (rid,),
            data=regle,
            parent_path=branche_path,
        )
    elif "renvoi_vers" in branche:
        cible = branche["renvoi_vers"]
        yield TreeEntry(
            kind="renvoi_vers",
            depth=depth + 1,
            path=branche_path + (f">{cible}",),
            data={"cible": cible},
            parent_path=branche_path,
        )
