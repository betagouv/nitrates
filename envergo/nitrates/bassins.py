"""Codes des bassins hydrographiques DCE (Directive Cadre sur l'Eau).

Codes UE pour les 8 bassins metropole + nom propre.
Source : https://www.eaufrance.fr/les-bassins-hydrographiques

Le shapefile Sandre actuel (ZoneVuln_delimitation_EU, schema 2.x) expose
le code via le prefixe de l'attribut `inspireid` (ex 'FRG_ZV_2021_2',
'FRB1_48') et un libelle dans `name`. L'ancien shapefile (FXX) exposait
`CdEuBassin` + `NomZoneVul` directement -- on supporte les 2 schemas
pour la retro-compat des fixtures de tests.
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

# Ordre d'essai pour l'extraction depuis inspireid : long d'abord pour
# disambiguer FRB1 vs FRB2 vs (un jour) FRB.
_BASSIN_CODES_ORDONNES = sorted(BASSIN_NAMES.keys(), key=len, reverse=True)


def bassin_name(code, fallback_nom=None):
    """Retourne le nom du bassin DCE depuis son code UE.

    Si le code est connu, prend la version propre. Sinon retourne le nom
    fourni en fallback (typiquement attributes['name'] / 'NomZoneVul'
    du shapefile), ou la string "bassin <code>" en dernier recours.
    """
    if code and code in BASSIN_NAMES:
        return BASSIN_NAMES[code]
    if fallback_nom:
        return fallback_nom
    return f"bassin {code}" if code else "bassin inconnu"


def bassin_code_from_attributes(attrs):
    """Extrait le code de bassin DCE (ex 'FRB1') depuis les attributs
    d'une Zone ZV nitrates, en gerant les 2 schemas Sandre :

      - Schema actuel (delimitation_EU) : `inspireid` prefixe par le
        code bassin (ex 'FRG_ZV_2021_2' -> 'FRG', 'FRB1_48' -> 'FRB1').
      - Ancien schema (delimitation_FXX, fixtures de tests) :
        `CdEuBassin` directement.

    Retourne None si rien ne match.
    """
    if not attrs:
        return None
    # Ancien schema : champ direct.
    if attrs.get("CdEuBassin"):
        return attrs["CdEuBassin"]
    # Nouveau schema : prefixe de inspireid.
    inspireid = attrs.get("inspireid") or ""
    for code in _BASSIN_CODES_ORDONNES:
        if inspireid.startswith(code + "_"):
            return code
    return None


def bassin_label_from_attributes(attrs):
    """Libelle lisible du bassin pour une Zone ZV nitrates. Combine le
    code (via `bassin_code_from_attributes`) avec le nom propre
    (via `bassin_name`), avec fallback sur `name`/`NomZoneVul` si le
    code est inconnu."""
    if not attrs:
        return None
    code = bassin_code_from_attributes(attrs)
    fallback = attrs.get("name") or attrs.get("NomZoneVul")
    return bassin_name(code, fallback)
