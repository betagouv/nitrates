"""Codes des bassins hydrographiques DCE (Directive Cadre sur l'Eau).

Codes UE (CdEuBassin dans le shapefile Sandre) avec leur nom propre.
Source : https://www.eaufrance.fr/les-bassins-hydrographiques

Le shapefile Sandre laisse parfois NomZoneVul vide pour 3 bassins
(FRA, FRB2, FRF), donc on a un fallback ici.
"""

BASSIN_NAMES = {
    "FRA": "Artois-Picardie",
    "FRB1": "Meuse",
    "FRB2": "Sambre",
    "FRC": "Rhin",
    "FRD": "Rhône-Méditerranée",
    "FRF": "Adour-Garonne",
    "FRG": "Loire-Bretagne",
    "FRH": "Seine-Normandie",
}


def bassin_name(code, fallback_nom=None):
    """Retourne le nom du bassin DCE depuis son code UE.

    Si le code est connu, prend la version propre. Sinon retourne le nom
    fourni en fallback (typiquement attributes['NomZoneVul'] du shapefile),
    ou la string "bassin <code>" en dernier recours.
    """
    if code and code in BASSIN_NAMES:
        return BASSIN_NAMES[code]
    if fallback_nom:
        return fallback_nom
    return f"bassin {code}" if code else "bassin inconnu"
