"""Reconstruction des champs FRONT de cascade a partir des champs backend (#175).

Contexte du bug #175 : un lien direct vers le simulateur pilote le parcours via
les champs *hidden derives* (`occupation_sol`, `sous_culture`, `type_fertilisant`,
`sous_fertilisant`...). Le backend calcule alors un resultat. Mais l'affichage des
RADIOS du formulaire (colonne gauche) depend, lui, des champs *front de cascade*
(`categorie_culture`, `sous_culture_form`, `categorie_fertilisant`) injectes dans
`NITRATES_INITIAL_DATA`. Quand un lien omet ces champs front (liens de validation
PAR/ZAR mal generes, ou liens tapes a la main depuis le YAML), on obtient
« un resultat affiche mais un formulaire vide/non selectionne ».

Ce module reconstruit ces champs front A L'AFFICHAGE, a partir des champs backend
presents, MAIS UNIQUEMENT quand la reconstruction est NON AMBIGUE :

- `(occupation_sol, sous_culture)` -> `sous_culture_form` : plusieurs formes UI
  peuvent resoudre vers le meme `sous_culture` (ex. culture_printemps <- mais /
  autre / prairie<6mois). On ne backfill QUE si une seule forme correspond.
- `sous_culture_form` -> `categorie_culture` : deterministe (structurel du form).
- `sous_fertilisant` -> `categorie_fertilisant` : chaque sous_fertilisant
  appartient a une seule categorie -> toujours non ambigu.

On ne reconstruit JAMAIS `sous_fertilisant` a partir du seul `type_fertilisant`
(un type regroupe jusqu'a 15 sous_fertilisants : l'info du choix utilisateur est
reellement perdue, l'inventer tromperait l'utilisateur).

Principe : NE JAMAIS ECRASER une valeur deja fournie dans l'URL. On ne comble que
les trous. Si le referentiel ne tranche pas, on laisse vide (comportement
actuel), on ne devine pas.
"""


def _sous_culture_form_vers_categorie(referentiels):
    """{ sous_culture_form: categorie_culture } derive de `categories_cultures`
    (source de verite : chaque categorie liste ses sous_cultures/formes).

    On DERIVE au lieu de coder en dur : la categorie UI (`culture_hiver`,
    `couvert_intercultures_longue`, `couvert_intercultures_courte`...) est la
    VALEUR du radio de 1er niveau, que cascade.js doit matcher exactement pour
    re-cocher. Un table hardcodee derivait (bug #175 : couvert mappait sur
    `couvert_intercultures`, qui n'est PAS une categorie UI valide -> radio non
    coche)."""
    rev = {}
    cats = referentiels.get("categories_cultures") or {}
    for cat_key, cat_data in cats.items():
        if not isinstance(cat_data, dict):
            continue
        for form in cat_data.get("sous_cultures") or []:
            rev.setdefault(form, cat_key)
    return rev


def _sous_culture_vers_forms(referentiels):
    """{ (occupation_sol, sous_culture): [sous_culture_form, ...] } depuis le
    referentiel. Liste car la resolution peut etre ambigue."""
    rev = {}
    mapping = referentiels.get("mapping_sous_culture_vers_branche") or {}
    for form_key, target in mapping.items():
        if not isinstance(target, dict):
            continue
        key = (target.get("occupation_sol"), target.get("sous_culture"))
        rev.setdefault(key, []).append(form_key)
    return rev


def _sous_fertilisant_vers_categorie(referentiels):
    """{ sous_fertilisant: categorie_fertilisant } depuis le referentiel.
    Chaque sous_fertilisant appartient a une seule categorie -> non ambigu."""
    rev = {}
    cats = referentiels.get("categories_fertilisants") or {}
    for cat_key, cat_data in cats.items():
        if not isinstance(cat_data, dict):
            continue
        for sf in cat_data.get("sous_fertilisants") or []:
            rev.setdefault(sf, cat_key)
    return rev


def backfill_form_fields(data, referentiels):
    """Rend un nouveau dict {champ: valeur} = `data` + les champs front de
    cascade reconstruits (non ambigus uniquement). N'ecrase jamais une valeur
    deja presente et non vide.

    `data` : mapping type QueryDict.dict() ou dict simple.
    Retourne toujours un dict simple (copie).
    """
    out = dict(data)
    form_vers_categorie = _sous_culture_form_vers_categorie(referentiels)

    def manquant(champ):
        return not (out.get(champ) or "").strip()

    # ── Culture ────────────────────────────────────────────────────────────
    sous_culture = (out.get("sous_culture") or "").strip()
    occupation_sol = (out.get("occupation_sol") or "").strip()
    if sous_culture and (
        manquant("sous_culture_form") or manquant("categorie_culture")
    ):
        forms = _sous_culture_vers_forms(referentiels).get(
            (occupation_sol, sous_culture)
        )
        # On ne backfill sous_culture_form QUE si la resolution est unique.
        if forms and len(forms) == 1:
            form_key = forms[0]
            if manquant("sous_culture_form"):
                out["sous_culture_form"] = form_key
            if manquant("categorie_culture"):
                cat = form_vers_categorie.get(form_key)
                if cat:
                    out["categorie_culture"] = cat

    # Si sous_culture_form est fourni (ou vient d'etre reconstruit) sans
    # categorie_culture, on comble : la categorie est deterministe.
    if not manquant("sous_culture_form") and manquant("categorie_culture"):
        cat = form_vers_categorie.get(out["sous_culture_form"])
        if cat:
            out["categorie_culture"] = cat

    # ── Fertilisant ──────────────────────────────────────────────────────────
    # categorie_fertilisant depuis sous_fertilisant (toujours non ambigu).
    if not manquant("sous_fertilisant") and manquant("categorie_fertilisant"):
        cat = _sous_fertilisant_vers_categorie(referentiels).get(
            out["sous_fertilisant"]
        )
        if cat:
            out["categorie_fertilisant"] = cat

    return out
