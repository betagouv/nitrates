"""Mapping commune INSEE -> appartenance aux zones Est 1 / Est 2 (PAR7 Grand Est).

Regle metier (arrete PAR7 consolide Grand Est 2025, Article 3) :

  Zone Est 1 (alinea 1) : allongement des periodes d'interdiction d'epandage
    Type II/III sur mais et prairies>6mois / luzerne. Definie par :
      - 720 communes listees explicitement (Annexe 1, dept 08/51/52/57) ;
      - + les departements 54/55/88 en entier (toutes communes en ZV).

  Zone Est 2 (alinea 2) : meme allongement mais pour la VIGNE uniquement.
    Definie par 4 departements entiers (08/10/51/52), sans annexe commune.

Recouvrement : 08/51/52 sont dans les deux zones. Une commune peut donc etre
Est 1 (mais/prairie) ET Est 2 (vigne) -> deux flags distincts, pas une zone
unique. D'ou deux fonctions / deux references catalogue.

Source : CSV plat `assets/zones_est_grand_est.csv`, genere depuis l'Excel
juriste `specs/zones_est_par_grand_est.xlsx` par la commande
`provision_zones_est`. Format du CSV :

    zone,code_departement,code_insee,portee
    est_1,08,08041,commune
    est_1,54,,departement
    est_2,10,,departement

Une regle `portee=commune` matche le code INSEE exact. Une regle
`portee=departement` matche toute commune du departement (code_insee vide).

Comme `zonage_montagne` : pas de PostGIS, pas de DB. On resout sur le code
INSEE 5 chiffres pousse par le front apres reverse geocoding (geo.api.gouv.fr).
Le code departement est deduit des 2 premiers chiffres du code INSEE (suffit
pour les departements concernes, tous en metropole hors Corse).

NB metier : l'appartenance a une zone Est ne presume PAS de la ZV. Pour Est 1,
les departements entiers visent juridiquement "les communes en ZV du
departement", mais la condition ZV est portee en amont par l'arbre PAR (la ZV
est une pre-condition d'activation de tout PAR Grand Est, cf. chantier PAR GE).
Ce module repond donc strictement "la commune est-elle dans le perimetre
geographique de la zone Est ?".
"""

import csv
from functools import lru_cache
from pathlib import Path

_CSV_PATH = Path(__file__).parent / "assets" / "zones_est_grand_est.csv"

ZONES = ("est_1", "est_2")


@lru_cache(maxsize=1)
def _mapping() -> dict[str, dict]:
    """Charge le CSV genere et l'indexe par zone.

    Retourne un dict :
        {
          "est_1": {"communes": frozenset[str], "departements": frozenset[str]},
          "est_2": {...},
        }

    `communes` = codes INSEE listes explicitement. `departements` = codes
    departement couvrant tout le departement. Mis en cache process (~1 appel
    par worker). Si le CSV est absent (provisioning pas lance), retourne des
    ensembles vides -> toutes les communes ressortent hors zone.
    """
    out: dict[str, dict] = {
        zone: {"communes": set(), "departements": set()} for zone in ZONES
    }
    if not _CSV_PATH.exists():
        return _freeze(out)

    with open(_CSV_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            zone = (row.get("zone") or "").strip()
            if zone not in out:
                continue
            portee = (row.get("portee") or "").strip()
            if portee == "departement":
                dep = (row.get("code_departement") or "").strip()
                if dep:
                    out[zone]["departements"].add(dep)
            else:
                code = (row.get("code_insee") or "").strip()
                if code:
                    out[zone]["communes"].add(code)
    return _freeze(out)


def _freeze(out: dict[str, dict]) -> dict[str, dict]:
    return {
        zone: {
            "communes": frozenset(d["communes"]),
            "departements": frozenset(d["departements"]),
        }
        for zone, d in out.items()
    }


def _departement_de(code_insee: str) -> str:
    """Code departement deduit du code INSEE 5 chiffres (2 premiers chiffres ;
    les zones Est ne concernent que la metropole hors Corse)."""
    return code_insee[:2]


def _est_dans_zone(zone: str, code_insee: str | None) -> bool:
    if not code_insee:
        return False
    code = str(code_insee).strip()
    data = _mapping()[zone]
    if code in data["communes"]:
        return True
    if _departement_de(code) in data["departements"]:
        return True
    return False


def est_zone_grand_est_1(code_insee: str | None) -> bool:
    """True si la commune est en Zone Est 1 (mais / prairies>6mois / luzerne).

    Retourne False pour un code inconnu/vide (commune hors zone par defaut)."""
    return _est_dans_zone("est_1", code_insee)


def est_zone_grand_est_2(code_insee: str | None) -> bool:
    """True si la commune est en Zone Est 2 (vigne).

    Retourne False pour un code inconnu/vide (commune hors zone par defaut)."""
    return _est_dans_zone("est_2", code_insee)
