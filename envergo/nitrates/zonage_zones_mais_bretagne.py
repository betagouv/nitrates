"""Mapping commune INSEE -> zone maïs 1 / 2 du PAR Bretagne.

Regle metier (arrete PAR Bretagne modifie du 28/08/2026, art. 4.1 et annexe 7) :
la periode d'interdiction d'epandage des fertilisants de type II sur mais
(01/07 au 15/03 inclus) peut etre adaptee par arrete du prefet de departement,
differemment selon la zone :

  Zone 1 : avancement possible au 1er mars (meteo favorable).
  Zone 2 : prolongation possible jusqu'au 31 mars (meteo defavorable).

L'annexe 7 ne liste que les communes de la zone 2 (Cotes-d'Armor, Finistere,
Morbihan) ; la zone 1 est le complement sur la Bretagne (carte de l'annexe 7).
Les deux zones sont listees EXPLICITEMENT dans le CSV, commune par commune :
la zone 1 n'est pas deduite a la volee, une commune absente du CSV n'est dans
aucune zone.

Source : CSV plat `assets/zones_mais_bretagne.csv` (zone,code_insee,nom_commune),
genere depuis l'annexe 7 (zone 2, 422 communes) et la table nationale des
communes (zone 1 = communes des departements 22, 29, 35, 56 hors zone 2).

Comme `zonage_zones_est` : pas de PostGIS, pas de DB, resolution sur le code
INSEE pousse par le front apres reverse geocoding.
"""

import csv
from functools import lru_cache
from pathlib import Path

_CSV_PATH = Path(__file__).parent / "assets" / "zones_mais_bretagne.csv"

ZONES = ("zone_1", "zone_2")


@lru_cache(maxsize=1)
def _mapping() -> dict[str, str]:
    """{code_insee: zone}. Vide si le CSV est absent (aucune commune en zone)."""
    if not _CSV_PATH.exists():
        return {}
    with open(_CSV_PATH, encoding="utf-8") as f:
        return {
            row["code_insee"].strip(): row["zone"].strip()
            for row in csv.DictReader(f)
            if row.get("zone", "").strip() in ZONES and row.get("code_insee")
        }


def zone_mais_bretagne(code_insee: str | None) -> str | None:
    """`zone_1` / `zone_2` pour une commune bretonne, None hors liste."""
    if not code_insee:
        return None
    return _mapping().get(str(code_insee).strip())
