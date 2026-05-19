"""Construit les GET params du simulateur a partir d'un path admin.

Cas d'usage (killer feature #80) : depuis un noeud N de l'arbre d'edition
en mode brouillon, generer un lien `/simulateur/?draft_tree_id=<pk>&<params>`
qui pre-remplit le simulateur sur le chemin amenant a N. L'utilisateur
voit en direct le comportement du brouillon pour ce sous-arbre.

Path admin = suite d'ids de noeuds, ex:
    ("n_zvn", "q_occupation_sol", "q_culture_principale_type",
     "q_colza_fertilisant", "q_colza_type_0_zone_note_5")

Deux types de params a injecter :

1. Champs formulaire (occupation_sol, sous_culture, type_fertilisant, etc.) :
   on les lit directement du chemin (branche.valeur).

2. Lat/lng + code_insee : necessaires pour que la moulinette puisse
   resoudre les noeuds catalogue SIG (zone_note_5, zone_montagne, etc.).
   On detecte les catalogues SIG sur le chemin et leur valeur attendue,
   puis on choisit un point de reference pre-calibre qui satisfait ces
   contraintes (ex: si le path passe par `branche true` de
   `n_*_zone_note_5`, on prend un point en Occitanie).
"""

from __future__ import annotations

from envergo.nitrates.yaml_admin import editor

# Points de reference pre-calibres. Pour chaque "profil" SIG (en_zone_vulnerable,
# zone_note_5, zone_montagne_*) on a un point qui resout dans la bonne zone.
# Source : tests pytest + tests e2e (REIMS_LAT/LNG, INSEE_TOULOUSE_31, etc.).
# Centre approximatif des villes : Reims (Marne, ZV hors note_5), Toulouse
# (Haute-Garonne, ZV + note_5), Bordeaux (Gironde, ZV + note_5), un point
# en zone montagne (D113-14).
_POINTS = {
    "reims_zv": {
        "lat": "49.2583",
        "lng": "4.0345",
        "code_insee": "51454",  # Reims, Marne, ZV oui, note_5 non, montagne non
    },
    "toulouse_zv_note5": {
        "lat": "43.6047",
        "lng": "1.4442",
        "code_insee": "31555",  # Toulouse, Haute-Garonne, ZV oui, note_5 oui (Occitanie)
    },
    "bordeaux_zv_note5": {
        "lat": "44.8378",
        "lng": "-0.5792",
        "code_insee": "33063",  # Bordeaux, Gironde, ZV oui, note_5 oui
    },
    "hors_zv": {
        # Quelque part en mer (hors France) : pas en ZV.
        "lat": "30.0",
        "lng": "-30.0",
        "code_insee": "",
    },
}

# Fallback par defaut : ZV oui, hors note_5.
_DEFAULT_POINT = _POINTS["reims_zv"]


def compute_simulator_params(arbre: dict, path: tuple[str, ...]) -> dict:
    """Retourne le dict {champ: valeur} a passer en GET au simulateur pour
    atterrir sur ce noeud (au plus pres).

    Inclut lat/lng/code_insee choisis selon les catalogues SIG sur le chemin.

    Cas particuliers :
    - path vide / racine seule : on retourne juste un point ZV par defaut
      pour que le simulateur ait quelque chose a parcourir
    - path casse au milieu : on retourne ce qu'on a accumule jusque-la
    - branche feuille (regle/renvoi_vers) sur le chemin : on s'arrete
    """
    params: dict = {}
    if not arbre:
        return params
    racine = (arbre.get("arbre") or {}).get("noeud")
    if not isinstance(racine, dict):
        return params

    # On collecte d'abord les contraintes SIG (champ_catalogue -> valeur_attendue)
    # en plus des params formulaire, en parcourant le chemin une seule fois.
    sig_constraints: dict = {}
    if path and path[0] == racine.get("id"):
        current = racine
        for next_id in path[1:]:
            champ = current.get("champ")
            type_noeud = current.get("type_noeud")
            branche = _find_branche_vers(current, next_id)
            if branche is None:
                break
            valeur = branche.get("valeur")
            if type_noeud == "formulaire" and champ and valeur is not None:
                params[champ] = _stringify_valeur(valeur)
            elif type_noeud == "catalogue" and champ:
                # On note la contrainte SIG. Cas particulier en_zone_vulnerable :
                # on l'expose AUSSI comme param URL (le moteur lit ce champ
                # depuis le contexte sans toucher au SIG si on lui donne).
                if champ == "en_zone_vulnerable" and valeur is not None:
                    params[champ] = _stringify_valeur(valeur)
                sig_constraints[champ] = valeur
            # On descend.
            sub = branche.get("noeud")
            if isinstance(sub, dict):
                current = sub
            else:
                break
        # Le noeud final atteint compte aussi pour les contraintes SIG :
        # si le path s'arrete sur un catalogue note_5/montagne sans descendre
        # dans une branche, on veut quand meme injecter la contrainte pour
        # que _select_point choisisse le bon point.
        if isinstance(current, dict) and current.get("type_noeud") == "catalogue":
            final_champ = current.get("champ")
            if final_champ and final_champ not in sig_constraints:
                sig_constraints[final_champ] = None

    # Choix d'un point de reference qui satisfait les contraintes SIG.
    point = _select_point(sig_constraints)
    # On expose toujours lat/lng/code_insee (le simulateur en a besoin pour
    # initialiser la carte et resoudre les catalogues internes).
    for k, v in point.items():
        if v:  # n'ecrase pas avec une str vide
            params.setdefault(k, v)

    return params


def _select_point(sig_constraints: dict) -> dict:
    """Choisit un point de reference qui satisfait les contraintes SIG du
    chemin. Heuristique simple :
      - en_zone_vulnerable=False explicite -> point hors ZV
      - note_5=False explicite -> Reims (Marne, hors note_5)
      - sinon si le chemin traverse un catalogue zone_note_5 (peu importe
        la valeur choisie sur le path) -> Toulouse (note_5=True, plus
        restrictif et plus interessant a previsualiser)
      - sinon Reims (defaut ZV hors note_5)
    """
    # Hors ZV explicite
    if sig_constraints.get("en_zone_vulnerable") is False:
        return _POINTS["hors_zv"]
    # Note 5 traversee : par defaut on veut tester le cas le plus restrictif
    # (note_5=True). L'utilisateur peut toujours editer lat/lng/code_insee
    # dans le formulaire du simulateur pour tester l'autre cas.
    if any("note_5" in str(c) for c in sig_constraints.keys()):
        # Si la contrainte explicite est note_5=False, on prend Reims
        if any("note_5" in str(k) and v is False for k, v in sig_constraints.items()):
            return _POINTS["reims_zv"]
        return _POINTS["toulouse_zv_note5"]
    # Hors note_5 : Reims (defaut)
    return _DEFAULT_POINT


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
    tree_pk, params: dict, simulator_path: str = "/simulateur/"
) -> str:
    """Construit l'URL complete du simulateur pour previewer un tree.

    `tree_pk` : pk du draft a previsualiser, ou None pour previsualiser
        l'arbre actif (pas de param draft_tree_id ajoute dans ce cas).
    `params` : output de compute_simulator_params(arbre, path).
    Retourne `<simulator_path>?[draft_tree_id=<pk>&]<param1>=<val1>&...`.
    """
    from urllib.parse import urlencode

    all_params = {}
    if tree_pk is not None:
        all_params["draft_tree_id"] = str(tree_pk)
    all_params.update(params)
    return f"{simulator_path}?{urlencode(all_params)}"


# Re-export pour faciliter l'import.
get_node_at = editor.get_node_at
