"""Mapping commune INSEE -> appartenance a la zone note_5 (PAN).

Regle juriste (NoteReglementaire 'note_5') :

  Zone note_5 = parcelle situee en region PACA ou Occitanie,
                ou dans les departements 24/33/40/47/64.

La liste exacte des regions et departements est lue depuis la DB
(`NoteReglementaire.regions_concernees` / `departements_concernes`)
plutot que codee en dur ici : les admins peuvent ainsi modifier la
note via l'admin Django sans toucher au code (cf. carte #61 phase 4).

Resolution purement geographique : pas de PostGIS, pas de CSV --
on lit juste le code INSEE pousse par le front (apres reverse
geocoding via geo.api.gouv.fr).
"""

from functools import lru_cache

from envergo.nitrates.zonage_montagne import _mapping


@lru_cache(maxsize=1)
def _codes_note_5() -> tuple[frozenset[str], frozenset[str]]:
    """Lit les codes regions/departements de note_5 depuis la DB.

    Les regions sont stockees avec prefixe `R` (R76, R93) ; on strip
    pour matcher le format du CSV montagne (`"76"`, `"93"`).

    Retourne (regions_sans_prefixe, departements). Cache d'une entree :
    re-import du module pour invalider (cf. seed_referentiels).
    """
    from envergo.nitrates.models import NoteReglementaire

    try:
        note = NoteReglementaire.objects.get(identifiant="note_5")
    except NoteReglementaire.DoesNotExist:
        return frozenset(), frozenset()
    regions = frozenset(
        r[1:] if r.startswith("R") else r for r in (note.regions_concernees or [])
    )
    departements = frozenset(note.departements_concernes or [])
    return regions, departements


@lru_cache(maxsize=4096)
def zone_note_5_pour_commune(code_insee: str | None) -> bool:
    """Retourne True si la commune est en zone note_5, False sinon.

    Si le code INSEE est inconnu ou vide, retourne False (par defaut on
    considere la commune hors zone note_5, ce qui est le cas le plus
    frequent : seules ~quelques milliers de communes sont concernees).
    """
    if not code_insee:
        return False
    regions_note_5, departements_note_5 = _codes_note_5()
    code = str(code_insee).strip()
    info = _mapping().get(code)
    if info is not None:
        if info["region"] in regions_note_5:
            return True
        if info["departement"] in departements_note_5:
            return True
        return False
    # Commune absente du CSV montagne (commune hors zone montagne) : on
    # retombe sur une heuristique code_insee -> departement (les 2-3
    # premiers chiffres du code INSEE = code departement, sauf Corse
    # 2A/2B et DOM 97x). Suffit pour les 5 departements de la liste.
    if len(code) >= 2 and code[:2] in departements_note_5:
        return True
    return False
