"""Mapping département → région (codes INSEE officiels 2016).

On n'utilise pas localflavor car il garde des codes historiques (2015).
Source : code officiel géographique INSEE.
"""

REGIONS = {
    "11": "Île-de-France",
    "24": "Centre-Val de Loire",
    "27": "Bourgogne-Franche-Comté",
    "28": "Normandie",
    "32": "Hauts-de-France",
    "44": "Grand Est",
    "52": "Pays de la Loire",
    "53": "Bretagne",
    "75": "Nouvelle-Aquitaine",
    "76": "Occitanie",
    "84": "Auvergne-Rhône-Alpes",
    "93": "Provence-Alpes-Côte d'Azur",
    "94": "Corse",
}

DEPARTMENT_TO_REGION = {
    # Île-de-France
    "75": "11",
    "77": "11",
    "78": "11",
    "91": "11",
    "92": "11",
    "93": "11",
    "94": "11",
    "95": "11",
    # Centre-Val de Loire
    "18": "24",
    "28": "24",
    "36": "24",
    "37": "24",
    "41": "24",
    "45": "24",
    # Bourgogne-Franche-Comté
    "21": "27",
    "25": "27",
    "39": "27",
    "58": "27",
    "70": "27",
    "71": "27",
    "89": "27",
    "90": "27",
    # Normandie
    "14": "28",
    "27": "28",
    "50": "28",
    "61": "28",
    "76": "28",
    # Hauts-de-France
    "02": "32",
    "59": "32",
    "60": "32",
    "62": "32",
    "80": "32",
    # Grand Est
    "08": "44",
    "10": "44",
    "51": "44",
    "52": "44",
    "54": "44",
    "55": "44",
    "57": "44",
    "67": "44",
    "68": "44",
    "88": "44",
    # Pays de la Loire
    "44": "52",
    "49": "52",
    "53": "52",
    "72": "52",
    "85": "52",
    # Bretagne
    "22": "53",
    "29": "53",
    "35": "53",
    "56": "53",
    # Nouvelle-Aquitaine
    "16": "75",
    "17": "75",
    "19": "75",
    "23": "75",
    "24": "75",
    "33": "75",
    "40": "75",
    "47": "75",
    "64": "75",
    "79": "75",
    "86": "75",
    "87": "75",
    # Occitanie
    "09": "76",
    "11": "76",
    "12": "76",
    "30": "76",
    "31": "76",
    "32": "76",
    "34": "76",
    "46": "76",
    "48": "76",
    "65": "76",
    "66": "76",
    "81": "76",
    "82": "76",
    # Auvergne-Rhône-Alpes
    "01": "84",
    "03": "84",
    "07": "84",
    "15": "84",
    "26": "84",
    "38": "84",
    "42": "84",
    "43": "84",
    "63": "84",
    "69": "84",
    "73": "84",
    "74": "84",
    # Provence-Alpes-Côte d'Azur
    "04": "93",
    "05": "93",
    "06": "93",
    "13": "93",
    "83": "93",
    "84": "93",
    # Corse
    "2A": "94",
    "2B": "94",
}


def region_for_department(department_code):
    """Retourne (region_code, region_label) ou (None, None)."""
    code = DEPARTMENT_TO_REGION.get(department_code)
    if code is None:
        return (None, None)
    return (code, REGIONS.get(code, ""))
