"""Construit les GET params du simulateur a partir d'un path admin.

Cas d'usage (killer feature #80) : depuis un noeud N de l'arbre d'edition
en mode brouillon, generer un lien `/simulateur/?draft_tree_id=<pk>&<params>`
qui pre-remplit le simulateur sur le chemin amenant a N. L'utilisateur
voit en direct le comportement du brouillon pour ce sous-arbre.

Path admin = suite d'ids de noeuds, ex:
    ("n_zvn", "q_occupation_sol", "q_culture_principale_type",
     "q_colza_fertilisant", "q_colza_type_0_zone_note_5")

Trois types de params a injecter :

1. Champs formulaire arbre (occupation_sol, sous_culture, type_fertilisant,
   etc.) : lus directement du chemin (branche.valeur).

2. Lat/lng + code_insee : choisis selon les contraintes SIG du chemin via
   un mini-resolveur (cf. _SIG_RESOLVERS) : Beine-Nauroy si ZV simple,
   Saint-Jean-de-Verges si on traverse une zone montagne note 7,
   Saint-Ondras si note 6, Toulouse si note 5, point en mer si hors ZV.

3. Cascade form (categorie_culture, sous_culture_form, categorie_fertilisant,
   sous_fertilisant) : reconstruite par mapping inverse depuis
   referentiels.yaml pour que le formulaire de gauche du simulateur
   reflete les valeurs choisies. Sans ces champs, le simulateur evalue
   correctement mais l'UI reste vierge.

NOTE — DETTE TECHNIQUE : la reconstruction de la cascade form lit
referentiels.yaml. Quand on migrera ce mapping en DB (table dediee), il
faudra refactor _cascade_form_params.
"""

from __future__ import annotations

from envergo.nitrates.yaml_admin import editor

# ─── Points de reference SIG ────────────────────────────────────────────────
# Pour chaque profil SIG (en_zone_vulnerable, note_5, montagne note_6/7) on
# a un point reel verifie qui resout dans la bonne zone. Sources :
# - tests pytest (test_zonage_montagne.py, test_branche_*.py)
# - validations en direct par Max sur staging
#
# On expose lat/lng/code_insee pour que la moulinette puisse resoudre les
# noeuds catalogue SIG (ZV, note_5, montagne D113-14).

_POINTS = {
    "hors_zv": {
        # Quelque part en mer (hors France) : pas en ZV.
        "lat": "30.0",
        "lng": "-30.0",
        "code_insee": "",
    },
    "reims_zv": {
        # Beine-Nauroy (51046), Marne, Grand Est : ZV oui, note_5 non, montagne non.
        "lat": "49.22298",
        "lng": "4.21806",
        "code_insee": "51046",
    },
    "toulouse_note5": {
        # Toulouse (31555), Haute-Garonne, Occitanie : ZV oui, note_5 oui,
        # montagne non.
        "lat": "43.6047",
        "lng": "1.4442",
        "code_insee": "31555",
    },
    "ariege_note7": {
        # Saint-Jean-de-Verges (09264), Ariege, Occitanie : ZV oui, note_5 oui,
        # montagne D113-14 oui, classification = montagne_note_7.
        "lat": "42.99511",
        "lng": "1.64589",
        "code_insee": "09264",
    },
    "isere_note6": {
        # Saint-Ondras (38434), Isere, Auvergne-Rhone-Alpes : ZV oui, note_5
        # non, montagne D113-14 oui, classification = montagne_note_6.
        "lat": "45.52367",
        "lng": "5.56183",
        "code_insee": "38434",
    },
    # ─── Points Grand Est (PAR / ZAR / Zones Est) ────────────────────────────
    # Verifies via le catalog de la moulinette (cf. preview : ZV, region 44,
    # en_zar, est_zone_grand_est_1/2). Les zones Est se resolvent par
    # code_insee -> le code_insee est INDISPENSABLE dans l'URL preview.
    "par_grand_est": {
        # Beine-Nauroy (51046), Marne : ZV oui, region 44 (Grand Est), pas ZAR.
        # Point PAR generique (region Grand Est, hors couche ZAR).
        "lat": "49.22298",
        "lng": "4.21806",
        "code_insee": "51046",
    },
    "zar_grand_est": {
        # AAC Baussieres (08), centroide d'une zone de la couche ZAR
        # zar_par7_grand_est : ZV oui, region 44, en_zar oui.
        "lat": "49.544282",
        "lng": "4.248692",
        "code_insee": "",
    },
    "zone_grand_est_1": {
        # Mirecourt (88304), Vosges : ZV oui, region 44, Zone Est 1 oui
        # (mais / prairies>6mois / luzerne), Zone Est 2 non.
        "lat": "48.3017",
        "lng": "6.1306",
        "code_insee": "88304",
    },
    "zone_grand_est_2": {
        # Beine-Nauroy (51046), Marne : ZV oui, region 44, Zone Est 2 oui
        # (vigne, dept 51), Zone Est 1 non.
        "lat": "49.22298",
        "lng": "4.21806",
        "code_insee": "51046",
    },
    # ─── Points PAR par region (metropole) ───────────────────────────────────
    # Un PAR regional s'active par region (ZV + region), et son point de preview
    # doit tomber DANS la region de l'arbre (accuracy demandee). Points generes
    # par scripts/generate_region_points.py : commune reelle en ZV, centre
    # officiel geo.api.gouv.fr, profil (ZV, region) verifie via le catalog
    # moulinette. Grand Est garde son point historique (par_grand_est, 51046).
    # Regions sans point ici (76 Occitanie, 93 PACA) : couvertes plus tard quand
    # un PAR y sera actif -- elles retombent alors sur le fallback (None -> chemin).
    "par_region_11": {
        # Achères-la-Forêt (77001), Ile-de-France : ZV, hors ZAR.
        "lat": "48.347600",
        "lng": "2.565300",
        "code_insee": "77001",
    },
    "par_region_24": {
        # Achères (18001), Centre-Val de Loire : ZV, hors ZAR.
        "lat": "47.282800",
        "lng": "2.460100",
        "code_insee": "18001",
    },
    "par_region_27": {
        # Agencourt (21001), Bourgogne-Franche-Comte : ZV, hors ZAR.
        "lat": "47.125600",
        "lng": "4.988300",
        "code_insee": "21001",
    },
    "par_region_28": {
        # Les Trois Lacs (27676), Normandie : ZV, hors ZAR.
        "lat": "49.213400",
        "lng": "1.332600",
        "code_insee": "27676",
    },
    "par_region_32": {
        # Abbécourt (02001), Hauts-de-France : ZV, hors ZAR.
        "lat": "49.599700",
        "lng": "3.182400",
        "code_insee": "02001",
    },
    "par_region_53": {
        # Allineuc (22001), Bretagne : ZV, hors ZAR.
        "lat": "48.314700",
        "lng": "-2.869300",
        "code_insee": "22001",
    },
    "par_region_75": {
        # Les Adjots (16002), Nouvelle-Aquitaine : ZV, hors ZAR.
        "lat": "46.078100",
        "lng": "0.202800",
        "code_insee": "16002",
    },
    "par_region_84": {
        # Ambérieux-en-Dombes (01005), Auvergne-Rhone-Alpes : ZV, hors ZAR.
        "lat": "45.999200",
        "lng": "4.911900",
        "code_insee": "01005",
    },
}

# Mapping region_code -> cle _POINTS pour les PAR (scope region). Forward
# compatible : ajouter une region = une ligne ici + son point dans _POINTS
# (via scripts/generate_region_points.py). Grand Est (44) garde son point
# historique ; Hauts-de-France (32) est le prochain objectif operationnel.
_POINT_PAR_REGION = {
    "11": "par_region_11",  # Ile-de-France
    "24": "par_region_24",  # Centre-Val de Loire
    "27": "par_region_27",  # Bourgogne-Franche-Comte
    "28": "par_region_28",  # Normandie
    "32": "par_region_32",  # Hauts-de-France
    "44": "par_grand_est",  # Grand Est (point historique 51046)
    "53": "par_region_53",  # Bretagne
    "75": "par_region_75",  # Nouvelle-Aquitaine
    "84": "par_region_84",  # Auvergne-Rhone-Alpes
}

# Idem pour les ZAR (scope zar). Aujourd'hui seul le ZAR Grand Est existe ;
# ce mapping est le point d'extension quand un ZAR d'une autre region sera
# modelise (il faudra alors ajouter sa couche + son point ici). Tant qu'une
# region n'a pas de point ZAR dedie, on retombe sur le ZAR Grand Est (aucun
# autre ZAR n'existe -> pas de regression).
_POINT_ZAR_REGION = {
    "44": "zar_grand_est",
}
_POINT_ZAR_DEFAUT = "zar_grand_est"


# ─── Resolveur SIG ──────────────────────────────────────────────────────────
# Liste de (predicat sur sig_constraints, nom_point) iteree dans l'ordre.
# Premier match gagne. Permet d'ajouter de nouveaux profils sans toucher
# au code de selection.
#
# `sig_constraints` est un dict :
#   - champ -> valeur de branche choisie sur le chemin (True/False ou slug)
#   - champ present sans valeur (None) si le path s'arrete sur le noeud
#     catalogue sans descendre dans une branche (= "traverse mais pas choisi")


# Sentinel : clef presente dans sig_constraints avec valeur None signifie
# "le path a traverse ce catalogue sans descendre dans une branche". On
# l'interprete comme "branche par defaut" (le plus contraignant). Une cle
# avec valeur False signifie au contraire que l'utilisateur a explicitement
# choisi la branche negative et il faut un point qui NE remplit pas la
# contrainte (ex: pas en zone 5 -> Reims).
def _is_true_or_traversed(constraints, champ):
    v = constraints.get(champ, "__missing__")
    return v is True or v is None  # None = traverse sans branche choisie


def _any_branch_value_ends_with(constraints, suffix):
    """True si une des valeurs de sig_constraints (str) finit par `suffix`.
    Permet de matcher note_6 / montagne_note_6 / etc. sans hardcoder le
    nom exact du champ catalogue (zonage_prairie_III, zonage_montagne_regional,
    zone_montagne_classification...)."""
    for v in constraints.values():
        if isinstance(v, str) and v.endswith(suffix):
            return True
    return False


def _traverse_true_ou_defaut(constraints, champ):
    """True si le chemin traverse le catalogue `champ` en le validant.

    Ces catalogues SIG booleens (en_zar, zone_grand_est_1/2) representent une
    CONDITION geographique : on previsualise le cas ou elle est remplie sauf si
    la branche explicitement negative (False) a ete choisie. La branche positive
    peut porter True OU un slug (id du sous-noeud) selon la modelisation -> on
    accepte tout sauf False et l'absence."""
    if champ not in constraints:
        return False
    return constraints[champ] is not False


_SIG_RESOLVERS = [
    # 1. Hors ZV explicite (branche False de n_zvn)
    (lambda c: c.get("en_zone_vulnerable") is False, "hors_zv"),
    # Zones Est Grand Est : un catalogue zone_grand_est_1 / _2 traverse impose
    # un point (avec code_insee !) dans la bonne zone -- prioritaire car ces
    # zones sont aussi en ZV / region 44 (les resolveurs generiques matcheraient
    # sinon un point ZV quelconque hors zone Est).
    (lambda c: _traverse_true_ou_defaut(c, "zone_grand_est_1"), "zone_grand_est_1"),
    (lambda c: _traverse_true_ou_defaut(c, "zone_grand_est_2"), "zone_grand_est_2"),
    # En ZAR (couche zar_par7_grand_est) traverse / choisi.
    (lambda c: _traverse_true_ou_defaut(c, "en_zar"), "zar_grand_est"),
    # 2. Une branche traversee porte une valeur en *note_7 (ex: montagne_note_7,
    #    note_7) : peu importe le nom du catalogue (zonage_prairie_III,
    #    zonage_montagne_regional...).
    (lambda c: _any_branch_value_ends_with(c, "note_7"), "ariege_note7"),
    # 3. Une branche traversee porte une valeur en *note_6
    (lambda c: _any_branch_value_ends_with(c, "note_6"), "isere_note6"),
    # 4. Montagne D113-14 traverse (True ou sans branche choisie) -> defaut note 7
    (
        lambda c: _is_true_or_traversed(c, "zone_montagne_d113_14"),
        "ariege_note7",
    ),
    # 4b. Catalogue zonage* traverse sans branche choisie -> defaut note 7
    (
        lambda c: any(v is None and k.startswith("zonage_") for k, v in c.items()),
        "ariege_note7",
    ),
    # 5. Note 5 explicite ou traverse
    (lambda c: _is_true_or_traversed(c, "zone_note_5"), "toulouse_note5"),
    # 6. Fallback ZV oui sans contraintes (inclut les branches False de note_5,
    #    montagne_d113_14, etc. -> on retombe sur un point ZV simple type Reims)
    (lambda c: True, "reims_zv"),
]


def compute_simulator_params(
    arbre: dict,
    path: tuple[str, ...],
    leaf_branch: tuple[str, object] | None = None,
    point_override: dict | None = None,
) -> dict:
    """Retourne le dict {champ: valeur} a passer en GET au simulateur pour
    atterrir sur ce noeud (au plus pres).

    Inclut :
    - champs arbre (occupation_sol, type_fertilisant, etc.) du chemin
    - lat/lng/code_insee choisis selon contraintes SIG
    - cascade form (categorie_culture, sous_culture_form, ...) pour que
      l'UI du simulateur reflete les valeurs

    `leaf_branch` (optionnel) : `(champ, valeur)` representant le choix de
    branche fait sur le DERNIER noeud du path (utile pour previewer une
    regle feuille : path s'arrete au parent, mais on veut quand meme
    enregistrer la valeur de branche pour le resolveur SIG / cascade form).

    Cas particuliers :
    - path vide / racine seule : point ZV par defaut, pas de cascade
    - path casse au milieu : on retourne ce qu'on a accumule jusque-la
    - branche feuille (regle/renvoi_vers) sur le chemin : on s'arrete
    """
    params: dict = {}
    if not arbre:
        return params
    racine = (arbre.get("arbre") or {}).get("noeud")
    if not isinstance(racine, dict):
        return params

    # On parcourt le chemin en accumulant les params arbre + sig_constraints.
    sig_constraints: dict = {}
    # Expressions de branche traversees sous un catalogue_parametre (#128).
    # On les resout en fin de parcours : il faut un sous_fertilisant qui
    # satisfait l'expression pour que la preview tombe sur le bon cas.
    expressions_a_satisfaire: list[str] = []
    if path and path[0] == racine.get("id"):
        current = racine
        for next_id in path[1:]:
            champ = current.get("champ")
            type_noeud = current.get("type_noeud")
            branche = _find_branche_vers(current, next_id)
            if branche is None:
                break
            valeur = branche.get("valeur")
            if type_noeud == "catalogue_parametre":
                # Branche resolue par expression : on memorise l'expression
                # pour deriver ensuite un sous_fertilisant qui la satisfait.
                # La `valeur` (tracabilite) est aussi exposee sous son champ.
                expr = branche.get("expression")
                if expr:
                    expressions_a_satisfaire.append(expr)
                if champ and valeur is not None and champ not in params:
                    params[champ] = _stringify_valeur(valeur)
            elif type_noeud == "formulaire" and champ and valeur is not None:
                params[champ] = _stringify_valeur(valeur)
            elif type_noeud == "catalogue" and champ:
                # en_zone_vulnerable est aussi exposable en param URL.
                if champ == "en_zone_vulnerable" and valeur is not None:
                    params[champ] = _stringify_valeur(valeur)
                sig_constraints[champ] = valeur
            # On descend.
            sub = branche.get("noeud")
            if isinstance(sub, dict):
                current = sub
            else:
                break
        # Le noeud final atteint compte aussi : si on s'arrete sur un
        # catalogue note_5/montagne sans descendre, on note la contrainte
        # pour que le resolveur SIG choisisse le bon point.
        if isinstance(current, dict) and current.get("type_noeud") == "catalogue":
            final_champ = current.get("champ")
            if final_champ and final_champ not in sig_constraints:
                # Si on a une leaf_branch explicite sur ce dernier noeud,
                # on l'enregistre comme valeur de contrainte ; sinon None
                # = "traverse sans choisir" (interprete comme defaut).
                if leaf_branch and leaf_branch[0] == final_champ:
                    sig_constraints[final_champ] = leaf_branch[1]
                    if final_champ == "en_zone_vulnerable":
                        params[final_champ] = _stringify_valeur(leaf_branch[1])
                else:
                    sig_constraints[final_champ] = None
        # Cas formulaire feuille : si leaf_branch concerne le champ du
        # dernier noeud formulaire (regle dans une branche), on le rajoute
        # dans params arbre.
        elif isinstance(current, dict) and current.get("type_noeud") == "formulaire":
            final_champ = current.get("champ")
            if (
                leaf_branch
                and leaf_branch[0] == final_champ
                and leaf_branch[1] is not None
                and final_champ not in params
            ):
                params[final_champ] = _stringify_valeur(leaf_branch[1])
        # Cas catalogue_parametre feuille (#128) : le path s'arrete sur le
        # noeud, leaf_branch designe la branche choisie. On recupere son
        # expression pour deriver le sous_fertilisant qui la satisfait.
        elif (
            isinstance(current, dict)
            and current.get("type_noeud") == "catalogue_parametre"
        ):
            final_champ = current.get("champ")
            branche_choisie = None
            if leaf_branch and leaf_branch[0] == final_champ:
                for b in current.get("branches") or []:
                    if isinstance(b, dict) and b.get("valeur") == leaf_branch[1]:
                        branche_choisie = b
                        break
                if final_champ and leaf_branch[1] is not None:
                    params.setdefault(final_champ, _stringify_valeur(leaf_branch[1]))
            # Sans leaf_branch, on prend la 1re branche (cas "traverse sans
            # choisir" -> on montre au moins un cas valide du catalogue).
            if branche_choisie is None:
                branches = current.get("branches") or []
                branche_choisie = branches[0] if branches else None
            if isinstance(branche_choisie, dict) and branche_choisie.get("expression"):
                expressions_a_satisfaire.append(branche_choisie["expression"])

    # Choix d'un point de reference, par ordre de priorite :
    #   1. Le CHEMIN porte une contrainte SIG specifique (ZGE1/2, ZAR, note_5/6/7,
    #      hors_zv) -> ce point prime (il faut tomber dans CETTE zone, avec son
    #      code_insee quand la zone se resout par commune comme les Zones Est).
    #   2. Sinon, le point par defaut du SCOPE de l'arbre (`point_override` :
    #      ZAR -> point ZAR, region 44 -> point PAR) pour que l'arbre s'active.
    #   3. Sinon, fallback ZV national (Reims).
    point_chemin, specifique = _select_point_specifique(sig_constraints)
    if specifique:
        point = point_chemin
    elif point_override:
        point = point_override
    else:
        point = point_chemin  # fallback ZV
    for k, v in point.items():
        if v:
            params.setdefault(k, v)

    # Cascade form (categorie_culture, sous_culture_form, categorie_fertilisant,
    # sous_fertilisant) : reconstruite depuis referentiels.yaml.
    # On passe l'ensemble des params arbre comme `flags` candidats pour
    # disambiguer entre plusieurs sous_culture_form qui partagent
    # (occupation_sol, sous_culture) -- cf. les 4 variantes du couvert
    # d'interculture longue, qui se distinguent par sous_culture_couvert.
    cascade = _cascade_form_params(
        params.get("occupation_sol"),
        params.get("sous_culture"),
        params.get("type_fertilisant"),
        flags=params,
    )
    for k, v in cascade.items():
        if v:
            params.setdefault(k, v)

    # Catalogue parametre (#128) : si le chemin a traverse des branches
    # resolues par expression, le sous_fertilisant derive par defaut ci-dessus
    # (premier mappant vers le type) ne satisfait probablement PAS l'expression
    # (ex `'effluent_peu_charge' in sous_fertilisant`). On cherche un
    # sous_fertilisant qui rend toutes les expressions vraies, et on l'impose
    # (avec sa categorie) pour que la fleche preview tombe sur le bon cas.
    if expressions_a_satisfaire:
        sf = _sous_fertilisant_satisfaisant(
            expressions_a_satisfaire, params, params.get("type_fertilisant")
        )
        if sf:
            params["sous_fertilisant"] = sf
            cat = _find_categorie_fertilisant(sf)
            if cat:
                params["categorie_fertilisant"] = cat

        # Meme probleme quand un catalogue_parametre discrimine sur
        # `sous_culture_form` (ex PAR HdF : un noeud intercale entre la culture
        # et le type_fertilisant, `sous_culture_form == 'cultures_perennes_vignes'`).
        # La cascade form a pu poser le 1er sous_culture_form du groupe (florales)
        # qui ne satisfait PAS l'expression -> la fleche preview atterrissait sur
        # la mauvaise culture (voire ParcoursError). On derive le sous_culture_form
        # qui satisfait l'expression et on l'impose. N'affecte QUE l'URL de preview
        # admin (compute_simulator_params n'est pas utilise par le parcours runtime).
        scf = _sous_culture_form_satisfaisant(expressions_a_satisfaire, params)
        if scf:
            params["sous_culture_form"] = scf

    return params


def _sous_culture_form_satisfaisant(expressions: list[str], params: dict) -> str | None:
    """Retourne un slug `sous_culture_form` qui rend vraies les `expressions`
    portant sur ce champ (catalogue_parametre discriminant par sous_culture_form,
    ex PAR HdF vignes/legumes). On teste chaque valeur declaree au referentiel
    avec le contexte courant. Retourne None si aucune expression ne mentionne
    sous_culture_form, ou si aucune candidate ne satisfait -> l'appelant garde le
    defaut de la cascade form. Symetrique de `_sous_fertilisant_satisfaisant`."""
    pertinentes = [e for e in expressions if e and "sous_culture_form" in e]
    if not pertinentes:
        return None
    from envergo.nitrates.yaml_tree.expression import evaluer_expression

    ref = _load_ref()
    candidats: list[str] = []
    for cat in (ref or {}).get("categories_cultures", {}).values():
        candidats.extend(cat.get("sous_cultures") or [])
    for scf in candidats:
        contexte = dict(params)
        contexte["sous_culture_form"] = scf
        if all(evaluer_expression(expr, contexte) for expr in pertinentes):
            return scf
    return None


def _sous_fertilisant_satisfaisant(
    expressions: list[str],
    params: dict,
    type_fertilisant: str | None,
) -> str | None:
    """Retourne un slug sous_fertilisant qui rend TOUTES les `expressions`
    vraies (catalogue_parametre, preview). On teste chaque sous_fertilisant
    du referentiel en sandbox (meme evaluateur que le runtime), avec le
    contexte courant + ce sous_fertilisant. Premier qui matche l'emporte.

    On restreint aux sous_fertilisants mappant vers `type_fertilisant` si
    fourni (coherence avec la branche type deja choisie), sinon tous.
    Retourne None si aucun ne satisfait (l'appelant garde le defaut).
    """
    from envergo.nitrates.yaml_tree.expression import evaluer_expression

    ref = _load_ref()
    mapping = (ref or {}).get("mapping_sous_fertilisant_vers_type") or {}
    candidats = [
        sf
        for sf, tf in mapping.items()
        if type_fertilisant is None or tf == type_fertilisant
    ]
    for sf in candidats:
        contexte = dict(params)
        contexte["sous_fertilisant"] = sf
        if all(evaluer_expression(expr, contexte) for expr in expressions):
            return sf
    return None


def _select_point(sig_constraints: dict) -> dict:
    """Itere sur _SIG_RESOLVERS, retourne le premier point qui matche."""
    point, _ = _select_point_specifique(sig_constraints)
    return point


def _select_point_specifique(sig_constraints: dict) -> tuple[dict, bool]:
    """Comme _select_point mais retourne aussi si le match est SPECIFIQUE.

    Specifique = un resolveur a matche sur une vraie contrainte SIG du chemin
    (ZGE, ZAR, note_5/6/7, hors_zv...). Non specifique = on est retombe sur le
    fallback ZV generique (aucune contrainte de chemin). Sert a arbitrer avec
    le point par defaut du scope de l'arbre : le chemin prime quand il est
    specifique, sinon on prefere le defaut du scope (ZAR/PAR)."""
    for predicat, point_name in _SIG_RESOLVERS[:-1]:  # tous sauf le fallback ZV
        try:
            if predicat(sig_constraints):
                return _POINTS[point_name], True
        except (TypeError, KeyError):
            continue
    return _POINTS["reims_zv"], False  # fallback ultime, non specifique


def point_par_defaut_scope(scope: str, region_code: str = "") -> dict | None:
    """Point par defaut selon le scope d'un arbre, avec code_insee quand la zone
    se resout par commune (Zones Est). Sert de `point_override` (applique
    seulement si le chemin n'impose pas deja un point specifique).

      - scope 'zar'          -> point dans la couche ZAR de la region
                                (_POINT_ZAR_REGION, defaut = ZAR Grand Est)
      - scope 'region'       -> point PAR de la region (_POINT_PAR_REGION),
                                ex 44 -> Grand Est, 32 -> Hauts-de-France
      - autres / region sans -> None (resolution par le chemin)
        point connu

    Sans ce mapping, un PAR hors Grand Est (ex HdF, region 32, sans couche
    d'activation) retombait sur le fallback ZV national = un point Grand Est :
    les liens preview d'un arbre HdF pointaient donc en Grand Est.
    """
    from envergo.nitrates.models import DecisionTree

    if scope == DecisionTree.SCOPE_ZAR:
        point_name = _POINT_ZAR_REGION.get(region_code or "", _POINT_ZAR_DEFAUT)
        return dict(_POINTS[point_name])
    if scope == DecisionTree.SCOPE_REGION:
        point_name = _POINT_PAR_REGION.get(region_code or "")
        if point_name:
            return dict(_POINTS[point_name])
    return None


def point_for_activation_map(activation_map) -> dict | None:
    """Point reel (lat/lng/code_insee) a l'interieur de la couche SIG d'un
    arbre (ex ZAR), pour que la preview tombe DANS la zone d'activation.

    Prend le centroide d'une zone de la Map. Generique : marche pour toute
    couche d'activation, pas seulement la ZAR Grand Est. Retourne None si la
    Map n'a pas de geometrie exploitable (-> on retombe sur le resolveur SIG).
    """
    if activation_map is None:
        return None
    zone = activation_map.zones.exclude(geometry__isnull=True).first()
    if zone is None or zone.geometry is None:
        return None
    centroid = zone.geometry.centroid
    # code_insee laisse vide : les arbres actives par couche SIG (ZAR) ne
    # dependent pas du zonage commune ; le point geographique suffit a resoudre
    # en_zar / region / ZV cote moulinette.
    return {"lat": f"{centroid.y:.6f}", "lng": f"{centroid.x:.6f}"}


# ─── Cascade form ──────────────────────────────────────────────────────────
# Reconstruit les champs UI du formulaire principal (categorie_culture,
# sous_culture_form, categorie_fertilisant, sous_fertilisant) a partir des
# champs arbre (occupation_sol, sous_culture, type_fertilisant) en utilisant
# les mappings de referentiels.yaml.
#
# NOTE — DETTE TECHNIQUE : ce code lit referentiels.yaml (cache via le
# loader). Quand on migrera ce mapping vers une vraie DB (table de cascade
# dediee), cette fonction devra etre reecrite.


def _cascade_form_params(
    occupation_sol: str | None,
    sous_culture: str | None,
    type_fertilisant: str | None,
    flags: dict | None = None,
) -> dict:
    """Retourne le dict des params UI a injecter dans l'URL pour que la
    cascade form du simulateur reflete les valeurs arbre.

    `flags` est l'ensemble des params arbre (occupation_sol, sous_culture,
    sous_culture_couvert, etc.) deja resolus -- on s'en sert pour
    disambiguer entre plusieurs sous_culture_form qui partagent
    (occupation_sol, sous_culture).
    """
    out: dict = {}

    if occupation_sol and sous_culture:
        sc_form = _find_sous_culture_form(
            occupation_sol, sous_culture, flags=flags or {}
        )
        if sc_form:
            out["sous_culture_form"] = sc_form
            cat = _find_categorie_culture(sc_form)
            if cat:
                out["categorie_culture"] = cat

    if type_fertilisant:
        sous_fert = _find_sous_fertilisant(type_fertilisant)
        if sous_fert:
            out["sous_fertilisant"] = sous_fert
            cat = _find_categorie_fertilisant(sous_fert)
            if cat:
                out["categorie_fertilisant"] = cat

    return out


def _find_sous_culture_form(
    occupation_sol: str, sous_culture: str, flags: dict
) -> str | None:
    """Mapping inverse : (occupation_sol, sous_culture, flags...)
    -> sous_culture_form.

    Parcourt mapping_sous_culture_vers_branche. On selectionne le
    sous_culture_form dont `occupation_sol` et `sous_culture` matchent.

    Depuis l'aplatissement des couverts (spec_refactor_couverts_remontee_branches),
    chaque couvert a une valeur `sous_culture` unique (variante cie/cine), donc
    le couple (occupation_sol, sous_culture) identifie 1:1 le sous_culture_form
    -- plus besoin de disambiguer par `flags.sous_culture_couvert`.

    Reste un cas a 2+ candidats : les cultures qui partagent (occupation_sol,
    sous_culture) mais portent un `flags` distinct (ex mais / culture_irriguee_type).
    On prefere alors celui dont les `flags` cible matchent les flags fournis ;
    fallback au premier sinon.
    """
    ref = _load_ref()
    mapping = (ref or {}).get("mapping_sous_culture_vers_branche") or {}
    candidats = []
    for sc_form, target in mapping.items():
        if not isinstance(target, dict):
            continue
        if (
            target.get("occupation_sol") != occupation_sol
            or target.get("sous_culture") != sous_culture
        ):
            continue
        candidats.append((sc_form, target))

    if not candidats:
        return None

    # 1 seul candidat : ambiguite resolue, on prend.
    if len(candidats) == 1:
        return candidats[0][0]

    # 2+ candidats : on prefere celui dont les `flags` de la cible matchent
    # les flags fournis (cas mais / culture_irriguee_type).
    for sc_form, target in candidats:
        cible_flags = target.get("flags") or {}
        if cible_flags and all(flags.get(k) == v for k, v in cible_flags.items()):
            return sc_form

    # Fallback ultime : premier candidat.
    return candidats[0][0]


def _find_categorie_culture(sous_culture_form: str) -> str | None:
    """Mapping inverse : sous_culture_form -> categorie_culture en
    parcourant categories_cultures.X.sous_cultures (referentiels.yaml)."""
    ref = _load_ref()
    cats = (ref or {}).get("categories_cultures") or {}
    for cat_name, cat_data in cats.items():
        if not isinstance(cat_data, dict):
            continue
        if sous_culture_form in (cat_data.get("sous_cultures") or []):
            return cat_name
    return None


def _find_sous_fertilisant(type_fertilisant: str) -> str | None:
    """Mapping inverse : type_fertilisant -> premier sous_fertilisant qui
    mappe vers ce type (mapping_sous_fertilisant_vers_type dans
    referentiels.yaml)."""
    ref = _load_ref()
    mapping = (ref or {}).get("mapping_sous_fertilisant_vers_type") or {}
    for sous_fert, tf in mapping.items():
        if tf == type_fertilisant:
            return sous_fert
    return None


def _find_categorie_fertilisant(sous_fertilisant: str) -> str | None:
    """Mapping inverse : sous_fertilisant -> categorie_fertilisant en
    parcourant categories_fertilisants.X.sous_fertilisants
    (referentiels.yaml)."""
    ref = _load_ref()
    cats = (ref or {}).get("categories_fertilisants") or {}
    for cat_name, cat_data in cats.items():
        if not isinstance(cat_data, dict):
            continue
        if sous_fertilisant in (cat_data.get("sous_fertilisants") or []):
            return cat_name
    return None


def _load_ref() -> dict:
    """Charge referentiels.yaml (cache via le loader interne)."""
    try:
        from envergo.nitrates.yaml_tree.loader import load_referentiels

        return load_referentiels() or {}
    except Exception:
        return {}


# ─── Helpers ──────────────────────────────────────────────────────────────


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
    """Convertit la valeur YAML (bool/int/str) en str pour l'URL."""
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
