"""Mapping commune INSEE -> appartenance a la zone note_5 (PAN).

Regle juriste (referentiels.yaml note_5) :

  Zone note_5 = parcelle situee en region PACA ou Occitanie,
                ou dans les departements 24/33/40/47/64.

Codes INSEE :
  - regions  : 76 (Occitanie), 93 (PACA)
  - departements : 24 (Dordogne), 33 (Gironde), 40 (Landes),
                   47 (Lot-et-Garonne), 64 (Pyrenees-Atlantiques).

Ces codes sont stables (derogation reglementaire fixe par le PAN). On
les code en dur ici, comme pour Set A dans `zonage_montagne`. La
resolution est purement geographique : pas de PostGIS, pas de CSV --
on lit juste le code INSEE pousse par le front (apres reverse
geocoding via geo.api.gouv.fr).

L'arbre de decision branche sur `valeur: true` / `valeur: false` ;
cette fonction retourne donc un bool.
"""

from functools import lru_cache

from envergo.nitrates.zonage_montagne import _mapping

_REGIONS_NOTE_5 = {"76", "93"}  # Occitanie, PACA
_DEPARTEMENTS_NOTE_5 = {"24", "33", "40", "47", "64"}


@lru_cache(maxsize=4096)
def zone_note_5_pour_commune(code_insee: str | None) -> bool:
    """Retourne True si la commune est en zone note_5, False sinon.

    Si le code INSEE est inconnu ou vide, retourne False (par defaut on
    considere la commune hors zone note_5, ce qui est le cas le plus
    frequent : seules ~quelques milliers de communes sont concernees).
    """
    if not code_insee:
        return False
    code = str(code_insee).strip()
    info = _mapping().get(code)
    if info is not None:
        if info["region"] in _REGIONS_NOTE_5:
            return True
        if info["departement"] in _DEPARTEMENTS_NOTE_5:
            return True
        return False
    # Commune absente du CSV montagne (commune hors zone montagne) : on
    # retombe sur une heuristique code_insee -> departement (les 2-3
    # premiers chiffres du code INSEE = code departement, sauf Corse
    # 2A/2B et DOM 97x). Suffit pour les 5 departements de la liste.
    if len(code) >= 2 and code[:2] in _DEPARTEMENTS_NOTE_5:
        return True
    return False
