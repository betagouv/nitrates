"""Rappels réglementaires sous les dates du couvert (carte #407).

Sous les champs « date de semis » et « date de destruction » du couvert, le
formulaire rappelle les obligations de couverture des sols (mesure 7 du
programme d'actions : implantation au plus tard le…, maintien minimal de…,
pas de destruction avant le…). Ces rappels sont NON bloquants (« sauf
dérogation »), à la différence de `min` / `max` des inputs calculatrice (#126)
qui bornent la saisie.

Ils sont déclarés au niveau de l'arbre, dans un bloc racine `rappels_dates`,
avec la grammaire des inputs date des feuilles calculatrice :

    rappels_dates:
      - sous_cultures: [cine_avant_3112, cine_apres_0101,
                        cie_avant_3112, cie_apres_0101]
        source_juridique: "PAR7 Grand Est, article 10"
        inputs:
          - id: date_semis_couvert
            rappel_max: "30/09"                   # implanté au plus tard le…
          - id: date_destruction_couvert
            rappel_min:                           # pas détruit avant…
              - "date_semis_couvert+2mois"        #  … maintenu N après semis
              - "15/10"                           #  … et pas avant le 15/10

Pourquoi l'arbre et pas les feuilles : la mesure 7 est une règle de zone
(PAN / PAR / ZAR), indépendante du fertilisant, et le formulaire pose les dates
AVANT le fertilisant (la feuille n'est pas connue). Les PAR étant des
surcharges partielles, une sous-culture absente d'un PAR retomberait sinon sur
le rappel national.

Une borne est une date fixe JJ/MM ou un événement (± offset), même syntaxe que
les bornes de période calculatrice. `rappel_min` / `rappel_max` acceptent une
borne seule ou une liste. Cascade : pour chaque (sous-culture, input), l'arbre
le plus spécifique qui déclare un rappel l'emporte (ZAR > PAR > PAN).

La phrase affichée est générée ici, selon que l'input est une date de semis ou
de destruction.
"""

from __future__ import annotations

import re

CLE_RACINE = "rappels_dates"
RAPPEL_CLES = ("rappel_min", "rappel_max")

_DATE_FIXE_RE = re.compile(r"^(?P<j>\d{2})/(?P<m>\d{2})$")
_EVENT_RE = re.compile(
    r"^(?P<event>[a-z][a-z0-9_]*)"
    r"(?:(?P<sign>[+-])(?P<n>\d+)(?P<unit>jours|semaines|mois))?$"
)
_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_JOURS_PAR_MOIS = {
    1: 31,
    2: 29,
    3: 31,
    4: 30,
    5: 31,
    6: 30,
    7: 31,
    8: 31,
    9: 30,
    10: 31,
    11: 30,
    12: 31,
}
_MOIS = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]

PREFIXE = "Pour rappel, sauf dérogation, le couvert"


def bornes_rappel(valeur) -> list[str]:
    """Normalise `rappel_min` / `rappel_max` (str | list | None) en liste."""
    if valeur in (None, "", []):
        return []
    if isinstance(valeur, str):
        return [valeur]
    return [v for v in valeur if isinstance(v, str) and v]


def _erreur_borne(val, input_id: str) -> str | None:
    if not isinstance(val, str) or not val:
        return f"borne {val!r} vide ou non textuelle"
    m = _DATE_FIXE_RE.match(val)
    if m:
        j, mo = int(m.group("j")), int(m.group("m"))
        if mo not in _JOURS_PAR_MOIS or not 1 <= j <= _JOURS_PAR_MOIS[mo]:
            return f"borne {val!r} : date invalide"
        return None
    m = _EVENT_RE.match(val)
    if not m:
        return (
            f"borne {val!r} : ni date JJ/MM, ni événement, "
            "ni événement±N(jours|semaines|mois)"
        )
    if m.group("event") == input_id:
        return f"borne {val!r} : un input ne peut pas se borner lui-même"
    if m.group("sign") and int(m.group("n")) < 1:
        return f"borne {val!r} : offset doit être >= 1"
    return None


def valider_rappels_dates(arbre: dict, sous_cultures_connues=None) -> list[str]:
    """Erreurs du bloc racine `rappels_dates` (liste vide si absent ou OK).

    `sous_cultures_connues` (optionnel) : valeurs de sous_culture du
    référentiel, pour signaler une faute de frappe qui rendrait le rappel
    invisible."""
    bloc = (arbre or {}).get(CLE_RACINE)
    if bloc is None:
        return []
    pfx = f"[{CLE_RACINE}]"
    if not isinstance(bloc, list):
        return [f"{pfx} doit être une liste de groupes {{sous_cultures, inputs}}."]
    errors: list[str] = []
    vus: set[tuple[str, str]] = set()
    for g, groupe in enumerate(bloc, start=1):
        if not isinstance(groupe, dict):
            errors.append(f"{pfx} groupe #{g} : doit être un objet.")
            continue
        sous_cultures = groupe.get("sous_cultures")
        if (
            not isinstance(sous_cultures, list)
            or not sous_cultures
            or not all(isinstance(s, str) and s for s in sous_cultures)
        ):
            errors.append(
                f"{pfx} groupe #{g} : `sous_cultures` doit être une liste non vide."
            )
            sous_cultures = []
        elif sous_cultures_connues is not None:
            inconnues = sorted(set(sous_cultures) - set(sous_cultures_connues))
            if inconnues:
                errors.append(
                    f"{pfx} groupe #{g} : sous_cultures inconnues du "
                    f"référentiel : {inconnues}."
                )
        inputs = groupe.get("inputs")
        if not isinstance(inputs, list) or not inputs:
            errors.append(f"{pfx} groupe #{g} : `inputs` doit être une liste non vide.")
            continue
        for i, inp in enumerate(inputs, start=1):
            if not isinstance(inp, dict):
                errors.append(f"{pfx} groupe #{g} input #{i} : doit être un objet.")
                continue
            iid = inp.get("id")
            if not isinstance(iid, str) or not _SLUG_RE.match(iid):
                errors.append(
                    f"{pfx} groupe #{g} input #{i} : `id` obligatoire au format "
                    f"snake_case (reçu {iid!r})."
                )
                continue
            inconnus = sorted(set(inp) - {"id", *RAPPEL_CLES})
            if inconnus:
                errors.append(
                    f"{pfx} groupe #{g} input {iid} : clés inconnues {inconnus}."
                )
            if not any(bornes_rappel(inp.get(c)) for c in RAPPEL_CLES):
                errors.append(
                    f"{pfx} groupe #{g} input {iid} : au moins un de "
                    f"{list(RAPPEL_CLES)} attendu."
                )
            for cle in RAPPEL_CLES:
                brut = inp.get(cle)
                if brut is None:
                    continue
                if isinstance(brut, str):
                    bornes = [brut]
                elif isinstance(brut, list) and brut:
                    bornes = brut
                else:
                    errors.append(
                        f"{pfx} groupe #{g} input {iid} : `{cle}` doit être une "
                        f"borne ou une liste non vide de bornes (reçu {brut!r})."
                    )
                    continue
                for borne in bornes:
                    err = _erreur_borne(borne, iid)
                    if err:
                        errors.append(f"{pfx} groupe #{g} input {iid} `{cle}` : {err}")
            for sc in sous_cultures:
                if (sc, iid) in vus:
                    errors.append(
                        f"{pfx} sous_culture {sc} / input {iid} déclaré dans "
                        f"plusieurs groupes."
                    )
                vus.add((sc, iid))
    return errors


# ─── Phrase ──────────────────────────────────────────────────────────────


def _date_longue(jjmm: str) -> str:
    j, m = (int(x) for x in jjmm.split("/"))
    jour = "1er" if j == 1 else str(j)
    return f"{jour} {_MOIS[m - 1]}"


def _duree(n: str, unite: str) -> str:
    n_int = int(n)
    if unite == "mois" or n_int > 1:
        return f"{n_int} {unite}"
    return f"1 {unite[:-1]}"


def _role(input_id: str) -> str:
    if "semis" in input_id:
        return "semis"
    if "destruction" in input_id:
        return "destruction"
    return "autre"


_PARTICIPES = {"semis": "implanté", "destruction": "détruit"}


def _clause(input_id: str, sens: str, borne: str) -> str:
    """Une proposition de la phrase de rappel pour une borne."""
    participe = _PARTICIPES.get(_role(input_id))
    if _DATE_FIXE_RE.match(borne):
        date = _date_longue(borne)
        if participe is None:
            return (
                f"ne peut pas aller au-delà du {date}"
                if sens == "max"
                else f"ne peut pas commencer avant le {date}"
            )
        if sens == "max":
            return f"doit être {participe} au plus tard le {date} inclus"
        return f"ne peut pas être {participe} avant le {date}"
    m = _EVENT_RE.match(borne)
    event, sign = m.group("event"), m.group("sign")
    ref = {"semis": "semis", "destruction": "destruction"}.get(
        _role(event), event.replace("_", " ")
    )
    participe = participe or "concerné"
    if not sign:
        if sens == "min":
            return f"ne peut pas être {participe} avant le {ref}"
        return f"doit être {participe} au plus tard au {ref}"
    duree = _duree(m.group("n"), m.group("unit"))
    if _role(input_id) == "destruction" and sens == "min" and sign == "+":
        # Cas phare : durée minimale de maintien après semis.
        return f"doit être maintenu au moins {duree} après {ref}"
    position = "après" if sign == "+" else "avant"
    if sens == "min":
        return f"ne peut pas être {participe} moins de {duree} {position} {ref}"
    return f"doit être {participe} au plus tard {duree} {position} {ref}"


def _ordre(borne: str) -> int:
    # Durées relatives d'abord, dates fixes ensuite : « maintenu au moins
    # 2 mois après semis et ne peut pas être détruit avant le 15 octobre »
    # (formulation validée sur la carte #407).
    return 1 if _DATE_FIXE_RE.match(borne) else 0


def _joindre(clauses: list[str]) -> str:
    if len(clauses) <= 1:
        return "".join(clauses)
    return ", ".join(clauses[:-1]) + " et " + clauses[-1]


def texte_rappel(input_id: str, rappel_min=None, rappel_max=None) -> str:
    """Phrase de rappel affichée sous le champ date. "" si aucune borne."""
    clauses = [
        _clause(input_id, "min", b)
        for b in sorted(bornes_rappel(rappel_min), key=_ordre)
    ] + [
        _clause(input_id, "max", b)
        for b in sorted(bornes_rappel(rappel_max), key=_ordre)
    ]
    if not clauses:
        return ""
    return f"{PREFIXE} {_joindre(clauses)}."


# ─── Cascade sur les arbres du point ─────────────────────────────────────


def rappels_par_sous_culture(arbre: dict) -> dict[str, dict[str, dict]]:
    """{sous_culture: {input_id: {"rappel_min": [...], "rappel_max": [...]}}}
    déclarés par un arbre (bloc racine `rappels_dates`). Tolérant : un bloc
    mal formé est ignoré (le validateur le signale à l'enregistrement)."""
    out: dict[str, dict[str, dict]] = {}
    bloc = (arbre or {}).get(CLE_RACINE)
    if not isinstance(bloc, list):
        return out
    for groupe in bloc:
        if not isinstance(groupe, dict):
            continue
        for inp in groupe.get("inputs") or []:
            if not isinstance(inp, dict) or not isinstance(inp.get("id"), str):
                continue
            rappel = {c: bornes_rappel(inp.get(c)) for c in RAPPEL_CLES}
            if not any(rappel.values()):
                continue
            for sc in groupe.get("sous_cultures") or []:
                out.setdefault(str(sc), {})[inp["id"]] = rappel
    return out


def rappels_dates_couvert(arbres: list[dict], mapping_sous_culture: dict) -> dict:
    """Rappels à afficher dans le formulaire, indexés par identifiant de
    culture du formulaire (`sous_culture_form`, ex couvert_courte_recolte).

    `arbres` : contenus des arbres applicables au point, du plus spécifique au
    moins spécifique (ordre de `select_active_trees`).

    Retour : {culture_form: {input_id: {"texte", "rappel_min", "rappel_max"}}}
    """
    par_arbre = [rappels_par_sous_culture(a) for a in arbres]
    out: dict = {}
    for culture_form, branche in (mapping_sous_culture or {}).items():
        sous_culture = (branche or {}).get("sous_culture")
        if not sous_culture:
            continue
        retenus: dict = {}
        for rappels in par_arbre:
            for input_id, r in (rappels.get(sous_culture) or {}).items():
                if input_id not in retenus:
                    retenus[input_id] = {
                        **r,
                        "texte": texte_rappel(
                            input_id, r["rappel_min"], r["rappel_max"]
                        ),
                    }
        if retenus:
            out[culture_form] = retenus
    return out
