"""Mapping commune INSEE -> classification zone montagne (D113-14).

L'arbre de decision PAN distingue 3 valeurs pour le champ
`zonage_montagne_d113_14` :

  - `montagne_note_7` : commune en zone montagne ET dans une region/dept
    deroge "Note 7" (PACA, Occitanie, Aquitaine 24/33/40/47/64)
  - `montagne_note_6` : commune en zone montagne, hors zones Note 7
  - `non_montagne`    : commune hors zone montagne D113-14

Source : CSV juriste `zone_montagne_communes_2026-04-30.csv` (5789
communes flaggees `zone_montagne=C`). Lecture en memoire au premier
appel, mise en cache process. ~3MB de CSV, dictionnaire final ~600KB.

Pas de PostGIS, pas de polygones de communes : on resoud uniquement
sur le code INSEE (5 chiffres) que le front passe en query param apres
reverse geocoding via `geo.api.gouv.fr`. Si le code INSEE est manquant,
on retombe sur un appel geo.api cote serveur.
"""

import csv
from functools import lru_cache
from pathlib import Path

# Identifiants des regions/departements en "Note 7" (zone montagne avec
# derogation a periode plus courte, cf. arbre PAN). Source : juriste,
# avril 2026. Format : ensembles de strings INSEE.
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
