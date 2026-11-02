"""Géocodage par les API publiques de l'État, sans clé.

Mêmes services que ceux appelés par le simulateur depuis le navigateur :
  - geo.api.gouv.fr (découpage administratif) : recherche de commune par nom
    ou code postal, commune au point (cf. simulator.js fetchCommuneInfo) ;
  - Géoplateforme IGN (data.geopf.fr/geocodage) : recherche d'adresse
    (cf. address_autocomplete.js).

Toutes les fonctions renvoient des dicts simples et lèvent
GeocodageIndisponible si le service ne répond pas, pour que l'outil MCP puisse
le dire à l'assistant au lieu de planter.
"""

import hashlib

import requests
from django.core.cache import cache

GEO_API = "https://geo.api.gouv.fr"
GEOPF_RECHERCHE = "https://data.geopf.fr/geocodage/search"
TIMEOUT_S = 6
ESSAIS = 2
# Communes et adresses ne bougent pas d'un jour a l'autre : le cache absorbe
# les questions repetees d'une meme conversation et les hoquets du service.
CACHE_S = 24 * 3600
CHAMPS_COMMUNE = "nom,code,codesPostaux,centre,codeDepartement,departement,population"


class GeocodageIndisponible(Exception):
    """Le service de géocodage n'a pas répondu (réseau, 5xx, JSON invalide)."""


def _get(url: str, params: dict | None = None, essais=ESSAIS, timeout=TIMEOUT_S):
    url_complete = requests.Request("GET", url, params=params).prepare().url
    cle = "nitrates-mcp-geo:" + hashlib.sha1(url_complete.encode()).hexdigest()
    en_cache = cache.get(cle)
    if en_cache is not None:
        return en_cache.get("data")
    derniere = None
    for _ in range(essais):
        try:
            reponse = requests.get(url, params=params, timeout=timeout)
            if reponse.status_code == 404:
                data = None
            else:
                reponse.raise_for_status()
                data = reponse.json()
            cache.set(cle, {"data": data}, CACHE_S)
            return data
        except (requests.RequestException, ValueError) as exc:
            derniere = exc
    raise GeocodageIndisponible(str(derniere)) from derniere


def _commune(c: dict) -> dict:
    lng, lat = (c.get("centre") or {}).get("coordinates") or (None, None)
    departement = c.get("departement") or {}
    return {
        "nom": c.get("nom"),
        "code_insee": c.get("code"),
        "codes_postaux": c.get("codesPostaux") or [],
        "departement": departement.get("nom"),
        "code_departement": c.get("codeDepartement") or departement.get("code"),
        "population": c.get("population"),
        "lat": lat,
        "lng": lng,
    }


def chercher_communes(
    nom: str = "", code_postal: str = "", code_departement: str = "", limite=5
) -> list[dict]:
    """Communes correspondant au nom (recherche approchée, les plus peuplées
    d'abord) et/ou au code postal."""
    params = {"fields": CHAMPS_COMMUNE, "boost": "population", "limit": limite}
    if nom:
        params["nom"] = nom
    if code_postal:
        params["codePostal"] = code_postal
    if code_departement:
        params["codeDepartement"] = code_departement
    data = _get(f"{GEO_API}/communes", params) or []
    return [_commune(c) for c in data if c.get("centre")]


def commune_par_code(code_insee: str) -> dict | None:
    data = _get(f"{GEO_API}/communes/{code_insee}", {"fields": CHAMPS_COMMUNE})
    return _commune(data) if data else None


def commune_au_point(lat: float, lng: float) -> dict | None:
    data = _get(
        f"{GEO_API}/communes", {"lat": lat, "lon": lng, "fields": CHAMPS_COMMUNE}
    )
    return _commune(data[0]) if data else None


def contour_commune(code_insee: str) -> dict | None:
    """Contour GeoJSON (WGS84) de la commune, ou None. Sert à la carte et à
    l'indice « aire de captage dans la commune » : l'appelant s'en passe si
    le service ne répond pas (lenteurs intermittentes observées)."""
    data = _get(f"{GEO_API}/communes/{code_insee}", {"fields": "contour"}, timeout=4)
    return (data or {}).get("contour")


def chercher_adresse(texte: str, limite=5) -> list[dict]:
    """Adresses (ou lieux-dits) correspondant au texte libre, meilleur score
    d'abord."""
    data = _get(GEOPF_RECHERCHE, {"q": texte, "limit": limite}) or {}
    resultats = []
    for f in data.get("features") or []:
        p = f.get("properties") or {}
        lng, lat = (f.get("geometry") or {}).get("coordinates") or (None, None)
        resultats.append(
            {
                "libelle": p.get("label"),
                "commune": p.get("city"),
                "code_insee": p.get("citycode"),
                "code_postal": p.get("postcode"),
                "type": p.get("type"),
                "score": p.get("score"),
                "lat": lat,
                "lng": lng,
            }
        )
    return resultats


APICARTO_CADASTRE = "https://apicarto.ign.fr/api/cadastre/parcelle"


def parcelle_cadastrale(code_insee: str, section: str, numero: str) -> dict | None:
    """Parcelle cadastrale (API Carto de l'IGN) : géométrie GeoJSON WGS84 et
    référence, ou None si elle n'existe pas. C'est la référence que
    l'agriculteur trouve sur son bail ou son avis de taxe foncière."""
    data = _get(
        APICARTO_CADASTRE,
        {"code_insee": code_insee, "section": section, "numero": numero},
    )
    features = (data or {}).get("features") or []
    if not features:
        return None
    f = features[0]
    p = f.get("properties") or {}
    return {
        "geometrie": f.get("geometry"),
        "section": p.get("section"),
        "numero": p.get("numero"),
        "commune": p.get("nom_com"),
        "contenance_m2": p.get("contenance"),
    }
