"""Construit les GET params du simulateur a partir d'un path admin.

Cas d'usage (killer feature #80) : depuis un noeud N de l'arbre d'edition
en mode brouillon, generer un lien `/simulateur/?draft_tree_id=<pk>&<params>`
qui pre-remplit le simulateur sur le chemin amenant a N. L'utilisateur
voit en direct le comportement du brouillon pour ce sous-arbre.

Path admin = suite d'ids de noeuds, ex:
    ("n_zvn", "q_occupation_sol", "q_culture_principale_type",
     "q_colza_fertilisant", "q_colza_type_0_zone_note_5")

On trouve, pour chaque noeud i du path, la branche qui mene au noeud i+1
(en regardant `branche.noeud.id == path[i+1]`), et on accumule
`{champ_du_noeud_i: valeur_de_la_branche}`.

Limitations :
- les noeuds catalogue sont resolus cote backend (SIG) au moment du
  parcours -- on ne peut pas les pre-remplir via URL. On les saute
  silencieusement.
- les branches `renvoi_vers` ne portent pas de noeud enfant : on s'arrete
  des qu'on en rencontre une sur le chemin (pas de pre-remplissage du
  sous-arbre cible).
"""

from __future__ import annotations

from envergo.nitrates.yaml_admin import editor


def compute_simulator_params(arbre: dict, path: tuple[str, ...]) -> dict:
    """Retourne le dict {champ: valeur} a passer en GET au simulateur pour
    atterrir sur ce noeud (au plus pres).

    `path` = suite d'ids de noeuds depuis la racine (vide ou ["racine"]
    pour la racine elle-meme).

    Cas particuliers :
    - path vide / racine seule : dict vide (le simulateur partira de zero)
    - noeud catalogue intermediaire : on saute (pas de param URL pour
      les champs SIG)
    - branche renvoi_vers : on s'arrete la, l'utilisateur navigue
      manuellement dans le sous-arbre cible
    - branche introuvable (path casse) : on retourne ce qu'on a accumule
      jusque-la, fallback gracieux
    """
    if not arbre:
        return {}
    params: dict = {}
    racine = (arbre.get("arbre") or {}).get("noeud")
    if not isinstance(racine, dict):
        return params

    if not path:
        return params
    if path[0] != racine.get("id"):
        return params  # path ne demarre pas a la racine -> on s'abstient

    current = racine
    # On itere sur les paires (noeud_courant, id_du_noeud_suivant_dans_path)
    for next_id in path[1:]:
        champ = current.get("champ")
        type_noeud = current.get("type_noeud")
        branche = _find_branche_vers(current, next_id)
        if branche is None:
            break  # path casse
        valeur = branche.get("valeur")
        # On enregistre {champ: valeur} sauf pour les noeuds catalogue
        # (resolus cote backend via SIG, pas via URL). Exception : la racine
        # n_zvn dont en_zone_vulnerable est exposable.
        if type_noeud == "formulaire" and champ and valeur is not None:
            params[champ] = _stringify_valeur(valeur)
        elif type_noeud == "catalogue" and champ == "en_zone_vulnerable":
            # Cas special racine ZVN : si l'utilisateur a clique dans la
            # branche true, c'est bien la branche normale du PAN.
            if valeur is True:
                params[champ] = "True"
            elif valeur is False:
                params[champ] = "False"
        # On descend.
        if "noeud" in branche and isinstance(branche["noeud"], dict):
            current = branche["noeud"]
        else:
            # branche feuille (regle / renvoi_vers) -> on s'arrete
            break
    return params


def _find_branche_vers(noeud: dict, target_id: str) -> dict | None:
    """Retourne la branche de `noeud` qui mene vers le noeud d'id `target_id`."""
    for branche in noeud.get("branches") or []:
        if not isinstance(branche, dict):
            continue
        sub = branche.get("noeud")
        if isinstance(sub, dict) and sub.get("id") == target_id:
            return branche
    return None


def _stringify_valeur(valeur) -> str:
    """Convertit la valeur YAML (bool/int/str) en str pour l'URL.

    Le simulateur cote vue (MoulinetteView) lit les GET via
    `request.GET.dict()` qui retourne des str. Le contexte d'evaluation
    est ensuite reconcilie cote evaluator (cf. _contexte_initial).
    """
    if valeur is True:
        return "True"
    if valeur is False:
        return "False"
    return str(valeur)


def build_preview_url(
    tree_pk: int, params: dict, simulator_path: str = "/simulateur/"
) -> str:
    """Construit l'URL complete du simulateur pour previewer un draft.

    `tree_pk` : pk du draft.
    `params` : output de compute_simulator_params(arbre, path).
    Retourne `<simulator_path>?draft_tree_id=<pk>&<param1>=<val1>&...`.
    """
    from urllib.parse import urlencode

    all_params = {"draft_tree_id": str(tree_pk), **params}
    return f"{simulator_path}?{urlencode(all_params)}"


# Re-export pour faciliter l'import.
get_node_at = editor.get_node_at
