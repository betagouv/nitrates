"""Enumeration des feuilles atteignables d'un arbre de decision.

Pour chaque feuille (regle finale), on retourne le contexte minimal qui y
mene + le label metier lisible + l'id de la regle (ou la cible du
renvoi_vers).

Helper extrait de tests/test_arbre_couverture.py pour pouvoir etre
utilise hors-test (commandes management, vues admin de validation).
"""


def enumerer_feuilles_culture_principale(arbre: dict) -> list[tuple]:
    """Pour chaque feuille atteignable sous culture_principale, retourne
    `(label, contexte, regle_id_attendue)`.

    Ouvre les noeuds catalogue avec un Cartesian product True/False sur
    chaque champ de catalogue rencontre, ce qui couvre par construction
    toutes les branches catalogue. Renvoi_vers est resolu vers l'id cible.

    Si la racine n'est pas n_zvn (cas dev / test minimal), on tente de
    descendre quand meme jusqu'a un noeud champ=occupation_sol.
    """
    racine = arbre.get("arbre", {}).get("noeud")
    if not racine:
        return []

    contexte_base = {"en_zone_vulnerable": True}
    if racine.get("type_noeud") == "catalogue" and racine.get("id") == "n_zvn":
        branche_oui = next(
            (b for b in racine.get("branches", []) if b.get("valeur") is True),
            None,
        )
        if not branche_oui or "noeud" not in branche_oui:
            return []
        sous = branche_oui["noeud"]
    else:
        sous = racine

    if sous.get("champ") != "occupation_sol":
        return []

    branche_cp = next(
        (
            b
            for b in sous.get("branches", [])
            if b.get("valeur") == "culture_principale"
        ),
        None,
    )
    if not branche_cp or "noeud" not in branche_cp:
        return []

    cas: list[tuple] = []
    contexte_init = {**contexte_base, "occupation_sol": "culture_principale"}
    _walk(branche_cp["noeud"], contexte_init, [], cas)
    return cas


def _walk(noeud: dict, contexte: dict, path_label: list, cas: list) -> None:
    """Descend recursivement et enrichit `cas` avec
    `(label, contexte, regle_id)` pour chaque feuille atteignable. Pour
    les catalogues internes, on explore True puis False."""
    type_noeud = noeud.get("type_noeud")
    champ = noeud.get("champ")

    if type_noeud == "catalogue":
        valeurs_branches = [b.get("valeur") for b in noeud.get("branches", [])]
        for valeur in valeurs_branches:
            sous_contexte = dict(contexte)
            sous_contexte[champ] = valeur
            sous_label = path_label + [f"{champ}={valeur}"]
            branche = next(
                b for b in noeud.get("branches", []) if b.get("valeur") == valeur
            )
            _explore_branche(branche, sous_contexte, sous_label, cas)
        return

    if type_noeud == "formulaire":
        for branche in noeud.get("branches", []):
            valeur = branche.get("valeur")
            sous_contexte = dict(contexte)
            sous_contexte[champ] = valeur
            sous_label = path_label + [f"{champ}={valeur}"]
            _explore_branche(branche, sous_contexte, sous_label, cas)


def _explore_branche(branche: dict, contexte: dict, label: list, cas: list) -> None:
    if "noeud" in branche:
        _walk(branche["noeud"], contexte, label, cas)
    elif "regle" in branche:
        cas.append((" / ".join(label), contexte, branche["regle"]["id"]))
    elif "renvoi_vers" in branche:
        cas.append(
            (" / ".join(label) + f" -> {branche['renvoi_vers']}", contexte, None)
        )
