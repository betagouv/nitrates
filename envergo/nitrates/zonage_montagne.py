"""Mapping commune INSEE -> classification zone montagne (D113-14).

Regle metier (validee juriste 2026-04-30) :

  Set A = { commune dans region PACA ou Occitanie }
        UNION { commune dans departements 24, 33, 40, 47, 64 }
  Set B = { commune flaggee `zone_montagne=C` dans le CSV juriste }

  - `montagne_note_7`  : commune dans  B  inter  A
  - `montagne_note_6`  : commune dans  B  inter  ¬A   (= dans B, hors A)
  - `non_montagne`     : commune hors B (peu importe A)

L'arbre de decision PAN consomme ces 3 valeurs sur le champ
`zonage_montagne_d113_14` (et la reference `zonage_prairie_III` qui
porte la meme semantique). Set A est code en dur dans ce module ;
Set B est lu depuis le CSV juriste.

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

# Set A : zones où une commune montagne tombe en Note 7 (cf. regle
# juriste validee 2026-04-30). Codes INSEE de region (76, 93) et de
# departement (24/33/40/47/64). Si le CSV juriste evolue, Set A reste
# stable -- c'est une derogation reglementaire fixe par le PAN.
_REGIONS_NOTE_7 = {"76", "93"}  # Occitanie, PACA
_DEPARTEMENTS_NOTE_7 = {"24", "33", "40", "47", "64"}  # Aquitaine

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


def zonage_montagne_pour_commune(code_insee: str | None) -> str:
    """Retourne `montagne_note_7`, `montagne_note_6` ou `non_montagne`
    pour un code INSEE donne. Retourne `non_montagne` par defaut si le
    code est inconnu (commune absente du CSV : on suppose hors montagne).
    """
    if not code_insee:
        return "non_montagne"
    info = _mapping().get(str(code_insee).strip())
    if info is None or not info["montagne"]:
        return "non_montagne"
    if info["region"] in _REGIONS_NOTE_7 or info["departement"] in _DEPARTEMENTS_NOTE_7:
        return "montagne_note_7"
    return "montagne_note_6"
