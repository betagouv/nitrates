"""Mapping commune INSEE -> classification zone montagne (D113-14).

Regle metier zone montagne :

  Set B = { commune flaggee `zone_montagne=C` dans le CSV juriste }

  Set A_<variante> = ensemble des communes "Sud-Ouest" eligibles a la
  Note 7. Selon le contexte d'application juridique, Set A peut etre
  l'une de 2 variantes distinctes (cf. ci-dessous).

  - `montagne_note_7`  : commune dans  B  inter  A_<variante>
  - `montagne_note_6`  : commune dans  B  inter  ¬A_<variante>  (dans B, hors A)
  - `non_montagne`     : commune hors B (peu importe A)

------------------------------------------------------------------------
Note 7 : 2 variantes juridiques distinctes
------------------------------------------------------------------------

D'apres la spec metier (Miro juriste), il existe 2 versions de la
"Note 7" selon l'usage :

  - Variante "elargie" :
        regions PACA + Occitanie
        ou departements 24 (Dordogne), 33 (Gironde), 40 (Landes),
        47 (Lot-et-Garonne), 64 (Pyrenees-Atlantiques).
    Utilisee notamment pour les noeuds YAML
    `zone_note_7_vs_note_6` et `zone_note_7_montagne` (alias retro
    compat, et l'arbitrage culture principale type II/III via la
    `note_5` du referentiel).

  - Variante "Pyrenees-Atlantiques" (stricte) :
        regions PACA + Occitanie
        ou departement 64 (Pyrenees-Atlantiques) seul.
    Utilisee par le noeud YAML `zonage_prairie_III` (prairies de plus
    de 6 mois, fertilisant type III).

Ce sont 2 regles juridiques differentes : on ne factorise PAS, on les
expose comme 2 variantes nommees explicites. L'appelant choisit
laquelle il veut via le parametre `variante`.

Source CSV : `assets/zone_montagne_communes_2026-04-30.csv` (5789
communes flaggees C). Lecture en memoire au premier appel, mise en
cache process. ~3MB de CSV, dictionnaire final ~600KB.

Pas de PostGIS, pas de polygones de communes : on resoud uniquement
sur le code INSEE (5 chiffres) que le front passe en query param apres
reverse geocoding via `geo.api.gouv.fr` au clic carte.
"""

import csv
from functools import lru_cache
from pathlib import Path

# Regions communes aux 2 variantes Note 7 (Occitanie 76, PACA 93).
_REGIONS_NOTE_7 = {"76", "93"}

# Variante "elargie" : PACA, Occitanie + 5 departements Sud-Ouest
# (Dordogne, Gironde, Landes, Lot-et-Garonne, Pyrenees-Atlantiques).
_DEPARTEMENTS_NOTE_7_ELARGIE = {"24", "33", "40", "47", "64"}

# Variante "Pyrenees-Atlantiques" : PACA, Occitanie + 64 seul.
_DEPARTEMENTS_NOTE_7_PYRENEES_ATL = {"64"}

VARIANTES_NOTE_7 = ("elargie", "pyrenees_atl")

_CSV_PATH = Path(__file__).parent / "assets" / "zone_montagne_communes_2026-04-30.csv"


@lru_cache(maxsize=1)
def _mapping() -> dict[str, dict]:
    """Charge le CSV et indexe par code_commune INSEE. Retourne un dict
    {code_insee: {"region": str, "departement": str, "montagne": bool}}.

    Mis en cache process : appele une fois par worker, ~50ms.
    """
    out: dict[str, dict] = {}
    with open(_CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = (row.get("code_commune") or "").strip()
            if not code:
                continue
            out[code] = {
                "region": (row.get("Code région") or "").strip(),
                "departement": (row.get("Code département") or "").strip(),
                "montagne": (row.get("zone_montagne") or "").strip() == "C",
            }
    return out


def zonage_montagne_pour_commune(
    code_insee: str | None, variante: str = "elargie"
) -> str:
    """Retourne `montagne_note_7`, `montagne_note_6` ou `non_montagne`
    pour un code INSEE donne, selon la variante de Note 7 demandee.

    Args:
        code_insee: code commune INSEE 5 chiffres (None ou vide = non_montagne).
        variante: "elargie" (5 dept Sud-Ouest, defaut) ou "pyrenees_atl"
            (64 uniquement). Cf. docstring module pour le detail.

    Retourne `non_montagne` par defaut si le code est inconnu (commune
    absente du CSV : on suppose hors montagne).
    """
    if variante not in VARIANTES_NOTE_7:
        raise ValueError(
            f"variante inconnue : {variante!r}. "
            f"Valeurs valides : {VARIANTES_NOTE_7}"
        )
    if not code_insee:
        return "non_montagne"
    info = _mapping().get(str(code_insee).strip())
    if info is None or not info["montagne"]:
        return "non_montagne"
    if variante == "pyrenees_atl":
        depts = _DEPARTEMENTS_NOTE_7_PYRENEES_ATL
    else:
        depts = _DEPARTEMENTS_NOTE_7_ELARGIE
    if info["region"] in _REGIONS_NOTE_7 or info["departement"] in depts:
        return "montagne_note_7"
    return "montagne_note_6"


def est_zone_montagne_d113_14(code_insee: str | None) -> bool:
    """Retourne True si la commune est flaggee zone montagne (D113-14)
    dans le CSV juriste, False sinon. Utilise pour le noeud catalogue
    YAML `zone_montagne_d113_14` qui branche sur true/false (sans
    distinction note 6/7)."""
    if not code_insee:
        return False
    info = _mapping().get(str(code_insee).strip())
    return bool(info and info["montagne"])


def note_7_vs_note_6_pour_commune(
    code_insee: str | None, variante: str = "elargie"
) -> str:
    """Tranche entre `note_7` et `note_6` pour une commune deja
    consideree comme etant en zone montagne (le catalogue parent
    `zone_montagne_d113_14` a deja filtre).

    Retourne strictement "note_7" ou "note_6" (sans prefixe
    `montagne_`), pour matcher les valeurs des branches YAML du noeud
    catalogue `zone_note_7_vs_note_6`.

    Differences avec `zonage_montagne_pour_commune` :
      - pas de cas `non_montagne` (le parent l'a deja exclu)
      - pas de prefixe `montagne_` (l'arbre branche sur note_7/note_6)
      - meme logique Set A (PACA + Occitanie + dept selon variante)
        que `zonage_montagne_pour_commune`

    Si la commune n'est pas en montagne ou pas connue, on retombe par
    defaut sur "note_6" (le moins restrictif des 2 mais on n'est pas
    cense passer par cette fonction dans ce cas).
    """
    if variante not in VARIANTES_NOTE_7:
        raise ValueError(
            f"variante inconnue : {variante!r}. "
            f"Valeurs valides : {VARIANTES_NOTE_7}"
        )
    if not code_insee:
        return "note_6"
    info = _mapping().get(str(code_insee).strip())
    if info is None:
        return "note_6"
    if variante == "pyrenees_atl":
        depts = _DEPARTEMENTS_NOTE_7_PYRENEES_ATL
    else:
        depts = _DEPARTEMENTS_NOTE_7_ELARGIE
    if info["region"] in _REGIONS_NOTE_7 or info["departement"] in depts:
        return "note_7"
    return "note_6"
