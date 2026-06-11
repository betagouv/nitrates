"""Enumeration des feuilles atteignables d'un arbre de decision.

Helper extrait de tests/test_arbre_couverture.py pour pouvoir etre
utilise hors-test (commandes management, vues admin de validation).

Deux APIs :
  - `enumerer_feuilles_culture_principale(arbre)` -> `[(label, contexte, regle_id), ...]`
    (signature historique, conservee pour les tests existants)
  - `enumerer_feuilles_culture_principale_v2(arbre)` -> liste de dicts riches
    {label, contexte, regle_id, chemin_ids, branche_valeur, type_fertilisant,
    condition, zonage} pour la mini-app de validation.
"""


def enumerer_feuilles_culture_principale(arbre: dict) -> list[tuple]:
    """Signature historique. Cf. v2 pour le format enrichi."""
    return [
        (f["label"], f["contexte"], f["regle_id"])
        for f in enumerer_feuilles_culture_principale_v2(arbre)
    ]


def enumerer_feuilles_culture_principale_v2(arbre: dict) -> list[dict]:
    """Pour chaque feuille atteignable sous culture_principale, retourne un
    dict :
        {
            "label": str,                # chemin metier lisible
            "contexte": dict,            # contexte minimal cascade pour atteindre
            "regle_id": str | None,      # id final, None si renvoi_vers non resolu
            "chemin_ids": list[str],     # path d'ids YAML des noeuds + feuille
            "branche_valeur": str,       # slug branche (ex "colza", "luzerne")
            "type_fertilisant": str,     # slug type (ex "type_0", "type_III")
            "condition": str | None,     # slug condition complementaire (ex "icpe_a")
            "zonage": str | None,        # slug zonage SIG (ex "zone_note_5=True")
        }

    Ouvre les noeuds catalogue avec un Cartesian product True/False sur
    chaque champ de catalogue rencontre, ce qui couvre par construction
    toutes les branches catalogue.
    """
    racine = arbre.get("arbre", {}).get("noeud")
    if not racine:
        return []

    contexte_base = {"en_zone_vulnerable": True}
    chemin_init: list[str] = []
    if racine.get("type_noeud") == "catalogue" and racine.get("id") == "n_zvn":
        chemin_init.append(racine["id"])
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

    chemin_init.append(sous["id"])
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

    cas: list[dict] = []
    contexte_init = {**contexte_base, "occupation_sol": "culture_principale"}
    _walk(branche_cp["noeud"], contexte_init, [], chemin_init, cas)
    return cas


def enumerer_feuilles_couvert_v2(arbre: dict) -> list[dict]:
    """Pour chaque feuille atteignable sous `couvert_intercultures`, meme
    format de dict que `enumerer_feuilles_culture_principale_v2`.

    Difference cle : la branche couvert utilise massivement `renvoi_vers`
    (les feuilles `cie_*` reutilisent les sous-arbres ICPE des `cine_*`,
    et la courte CINE renvoie vers la longue avant-31/12). On resout ces
    renvois en suivant l'id pointe, qui peut etre soit un noeud (on
    continue le parcours), soit une regle (feuille directe).

    Sert au seed `BrancheValidation` couvert (sprint 2). Symetrique de
    l'enumeration culture principale, garde le meme `chemin_ids` comme
    cle naturelle stable.
    """
    racine = arbre.get("arbre", {}).get("noeud")
    if not racine:
        return []

    index = _index_par_id(arbre)
    contexte_base = {"en_zone_vulnerable": True}
    chemin_init: list[str] = []
    if racine.get("type_noeud") == "catalogue" and racine.get("id") == "n_zvn":
        chemin_init.append(racine["id"])
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

    chemin_init.append(sous["id"])
    branche_couvert = next(
        (
            b
            for b in sous.get("branches", [])
            if b.get("valeur") == "couvert_intercultures"
        ),
        None,
    )
    if not branche_couvert or "noeud" not in branche_couvert:
        return []

    cas: list[dict] = []
    contexte_init = {**contexte_base, "occupation_sol": "couvert_intercultures"}
    _walk(branche_couvert["noeud"], contexte_init, [], chemin_init, cas, index)
    return cas


def _index_par_id(arbre: dict) -> dict:
    """Indexe tous les noeuds/regles porteurs d'un `id` pour resoudre les
    `renvoi_vers`."""
    index: dict[str, dict] = {}

    def _idx(obj):
        if isinstance(obj, dict):
            oid = obj.get("id")
            if oid and ("branches" in obj or "type" in obj):
                index[oid] = obj
            for v in obj.values():
                _idx(v)
        elif isinstance(obj, list):
            for it in obj:
                _idx(it)

    _idx(arbre)
    return index


def _walk(
    noeud: dict,
    contexte: dict,
    path_label: list,
    chemin_ids: list,
    cas: list,
    index: dict | None = None,
    profondeur: int = 0,
) -> None:
    """Descend recursivement et enrichit `cas`. Pour les catalogues
    internes, on explore toutes les valeurs presentes dans les branches."""
    type_noeud = noeud.get("type_noeud")
    champ = noeud.get("champ")
    noeud_id = noeud.get("id", "")

    nouveau_chemin = chemin_ids + ([noeud_id] if noeud_id else [])

    # Garde-fou contre une eventuelle boucle de renvoi_vers (l'arbre couvert
    # croise les sous-arbres ; en theorie acyclique mais on borne).
    if profondeur > 60:
        return

    if type_noeud == "catalogue":
        valeurs_branches = [b.get("valeur") for b in noeud.get("branches", [])]
        for valeur in valeurs_branches:
            sous_contexte = dict(contexte)
            sous_contexte[champ] = valeur
            sous_label = path_label + [f"{champ}={valeur}"]
            branche = next(
                b for b in noeud.get("branches", []) if b.get("valeur") == valeur
            )
            _explore_branche(
                branche,
                sous_contexte,
                sous_label,
                nouveau_chemin,
                cas,
                index,
                profondeur,
            )
        return

    if type_noeud == "catalogue_parametre":
        # On explore TOUTES les branches (couverture exhaustive de la mini-app
        # de validation), comme un catalogue. Le routage runtime se fait par
        # expression (cf. #128) mais pour l'enumeration on materialise chaque
        # issue possible. La `valeur` de tracabilite est posee dans le contexte
        # quand elle existe ; le label retombe sur l'expression sinon.
        for i, branche in enumerate(noeud.get("branches", [])):
            sous_contexte = dict(contexte)
            if "valeur" in branche:
                sous_contexte[champ] = branche["valeur"]
                etiquette = f"{champ}={branche['valeur']}"
            else:
                etiquette = f"{champ}~expr#{i + 1}"
            sous_label = path_label + [etiquette]
            _explore_branche(
                branche,
                sous_contexte,
                sous_label,
                nouveau_chemin,
                cas,
                index,
                profondeur,
            )
        return

    if type_noeud == "formulaire":
        for branche in noeud.get("branches", []):
            valeur = branche.get("valeur")
            sous_contexte = dict(contexte)
            sous_contexte[champ] = valeur
            sous_label = path_label + [f"{champ}={valeur}"]
            _explore_branche(
                branche,
                sous_contexte,
                sous_label,
                nouveau_chemin,
                cas,
                index,
                profondeur,
            )


def _explore_branche(
    branche: dict,
    contexte: dict,
    label: list,
    chemin_ids: list,
    cas: list,
    index: dict | None = None,
    profondeur: int = 0,
) -> None:
    if "noeud" in branche:
        _walk(branche["noeud"], contexte, label, chemin_ids, cas, index, profondeur + 1)
    elif "renvoi_vers" in branche and index is not None:
        # Resolution du renvoi : on continue le parcours dans la cible si
        # c'est un noeud, sinon on materialise la regle pointee comme
        # feuille. (Sans `index`, on conserve l'ancien comportement :
        # renvoi non resolu enregistre tel quel -- cf. culture principale.)
        cible_id = branche["renvoi_vers"]
        cible = index.get(cible_id)
        # Inclut la valeur de la branche dans le chemin pour ne pas
        # fusionner deux branches distinctes qui pointent vers la meme
        # regle partagee (ex : type_0/I/II d'un couvert courte qui
        # renvoient tous vers `r_cie_courte_types_0_I_II`). Chacun reste
        # une feuille reviewable a part entiere.
        valeur_branche = branche.get("valeur")
        segment_renvoi = f"renvoi_vers:{cible_id}"
        if valeur_branche is not None:
            segment_renvoi = f"{valeur_branche}->renvoi_vers:{cible_id}"
        chemin_renvoi = chemin_ids + [segment_renvoi]
        label_renvoi = label + [f"-> {cible_id}"]
        if cible is None:
            _ajouter_renvoi_non_resolu(branche, contexte, label, chemin_ids, cas)
        elif "branches" in cible:
            _walk(
                cible, contexte, label_renvoi, chemin_renvoi, cas, index, profondeur + 1
            )
        else:
            cas.append(
                {
                    "label": " / ".join(label_renvoi),
                    "contexte": contexte,
                    "regle_id": cible.get("id"),
                    "chemin_ids": chemin_renvoi + [cible.get("id")],
                    "branche_valeur": _extract(contexte, "sous_culture"),
                    "type_fertilisant": _extract(contexte, "type_fertilisant"),
                    "condition": _extract_condition(contexte),
                    "zonage": _extract_zonage(contexte),
                }
            )
    elif "regle" in branche:
        regle_id = branche["regle"]["id"]
        cas.append(
            {
                "label": " / ".join(label),
                "contexte": contexte,
                "regle_id": regle_id,
                "chemin_ids": chemin_ids + [regle_id],
                "branche_valeur": _extract(contexte, "sous_culture"),
                "type_fertilisant": _extract(contexte, "type_fertilisant"),
                "condition": _extract_condition(contexte),
                "zonage": _extract_zonage(contexte),
            }
        )
    elif "renvoi_vers" in branche:
        _ajouter_renvoi_non_resolu(branche, contexte, label, chemin_ids, cas)


def _ajouter_renvoi_non_resolu(branche, contexte, label, chemin_ids, cas):
    """Enregistre un renvoi_vers non resolu comme feuille (regle_id=None).

    Comportement historique de l'enumeration culture principale : on ne
    suit pas le renvoi, on garde une trace. Le couvert, lui, passe un
    `index` a `_explore_branche` pour resoudre le renvoi en vraie feuille.
    """
    cible = branche["renvoi_vers"]
    cas.append(
        {
            "label": " / ".join(label) + f" -> {cible}",
            "contexte": contexte,
            "regle_id": None,
            "chemin_ids": chemin_ids + [f"renvoi_vers:{cible}"],
            "branche_valeur": _extract(contexte, "sous_culture"),
            "type_fertilisant": _extract(contexte, "type_fertilisant"),
            "condition": _extract_condition(contexte),
            "zonage": _extract_zonage(contexte),
        }
    )


_CHAMPS_CONDITION = (
    "plan_epandage",
    "fertilisant_iaa",
    "effluent_peu_charge",
    "culture_irriguee",
    "culture_irriguee_type",
    "fertirrigation",
)
_CHAMPS_ZONAGE = (
    "zone_note_5",
    "zonage_prairie_III_montagne",
    "zone_montagne_d113_14",
    "zone_montagne_classification",
)


def _extract(contexte: dict, cle: str) -> str | None:
    val = contexte.get(cle)
    if val is None:
        return None
    return str(val)


def _extract_condition(contexte: dict) -> str | None:
    """Concatene les conditions complementaires presentes dans le contexte
    (champs autres que cascade principale + zonage)."""
    parts = []
    for c in _CHAMPS_CONDITION:
        if c in contexte:
            parts.append(f"{c}={contexte[c]}")
    return " / ".join(parts) if parts else None


def _extract_zonage(contexte: dict) -> str | None:
    """Concatene les champs zonage SIG presents dans le contexte."""
    parts = []
    for c in _CHAMPS_ZONAGE:
        if c in contexte:
            parts.append(f"{c}={contexte[c]}")
    return " / ".join(parts) if parts else None
