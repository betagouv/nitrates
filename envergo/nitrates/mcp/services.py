"""Services métier exposés aux assistants conversationnels (serveur MCP).

Aucune règle n'est réécrite ici. La simulation passe par la même
MoulinetteNitrates que le formulaire public (cascade ZAR > PAR > PAN, résolution
SIG, questions complémentaires) ; le calendrier jour par jour réutilise le port
Python de la matrice (compute_regime_par_jour) ; les catalogues viennent des
tables de référentiel et les textes des ContenuRichDSFR.

Chaque fonction publique prend des paramètres simples et rend un dict
sérialisable en JSON. Une saisie inexploitable lève ErreurSaisie, dont le
message est renvoyé tel quel à l'assistant pour qu'il corrige ou reformule
la question à l'agriculteur.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, Point
from django.core.cache import cache

from envergo.geodata.models import MAP_TYPES, Map, Zone
from envergo.moulinette.models import Moulinette
from envergo.nitrates.constants import SCOPE_NATIONAL, SCOPE_REGION, SCOPE_ZAR
from envergo.nitrates.contenu_rich.compilateur import resume_texte
from envergo.nitrates.matrice import TOTAL_JOURS, _est_plafond, compute_regime_par_jour
from envergo.nitrates.mcp import geocodage, images
from envergo.nitrates.models import (
    CodePrescription,
    Culture,
    Fertilisant,
    GroupeCultureUI,
    MoulinetteNitrates,
)
from envergo.nitrates.models_ouverture import DepartementOuverture
from envergo.nitrates.regulations.arbre_decision import ArbreDecisionEvaluator
from envergo.nitrates.templatetags.nitrates_tags import _day_of_year
from envergo.nitrates.yaml_tree import load_referentiels, select_active_trees

logger = logging.getLogger(__name__)


def images_png() -> bool:
    """Cartes et calendriers aussi en PNG (contenu image MCP). Coupé par
    défaut : ChatGPT et Claude affichent la vue interactive, l'image faisait
    doublon et coûtait du temps (tuiles IGN, rendu)."""
    return getattr(settings, "NITRATES_MCP_IMAGES_PNG", False)


AVERTISSEMENT = (
    "Information réglementaire issue du simulateur public nitrates (programme "
    "d'actions national et programmes régionaux en zone vulnérable). Ce n'est "
    "pas un conseil agronomique et cela ne remplace pas les arrêtés : en cas "
    "de doute, se référer au lien de la simulation et à la DDT(M)."
)

LIBELLES_REGIME = {
    "interdiction": "épandage interdit",
    "autorisation_sous_condition": "autorisé sous conditions (voir prescriptions)",
    "plafonnement": "autorisé dans la limite d'un plafond d'azote",
    "libre": "pas de période d'interdiction (les règles permanentes s'appliquent)",
    "non_applicable": "non concerné",
}

LIBELLES_TYPES_FERTILISANT = {
    "type_0": "Type 0 (C/N élevé, azote peu disponible, ex. composts ligneux)",
    "type_Ia": "Type Ia (C/N élevé, ex. fumiers compacts pailleux)",
    "type_Ib": "Type Ib (C/N élevé mais plus d'azote disponible, ex. fumiers mous)",
    "type_II": "Type II (C/N bas, azote rapidement disponible, ex. lisiers, "
    "digestats, fientes)",
    "type_III": "Type III (engrais azotés minéraux et de synthèse)",
}

# Champs que les reponses de l'assistant ne doivent jamais ecraser : la
# localisation, la cascade culture/fertilisant (posee par les catalogues) et
# surtout `draft_tree_id`, qui ferait evaluer un brouillon non publie (la vue
# publique le retire pour un visiteur sans droit, cf. _guard_draft_tree_id).
CHAMPS_RESERVES = {
    "lat",
    "lng",
    "code_insee",
    "categorie_culture",
    "sous_culture_form",
    "occupation_sol",
    "sous_culture",
    "categorie_fertilisant",
    "sous_fertilisant",
    "type_fertilisant",
    "draft_tree_id",
}

_DATE_JJMM = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/\d{2,4})?$")
_DATE_ISO = re.compile(r"^\d{4}-(\d{2})-(\d{2})$")
# Annee non bissextile commencant au 1er juillet : jour agricole 0 = 01/07.
_DEBUT_ANNEE_AGRICOLE = date(2025, 7, 1)


def regles_permanentes() -> str:
    """Bloc « Règles permanentes » affiché sous chaque résultat du simulateur
    (cours d'eau, pentes, sols détrempés, gelés, enneigés) : il vaut même
    quand le calendrier n'interdit rien."""
    from envergo.nitrates.contenu_rich.loader import load_blocs

    return blocs_en_texte(load_blocs("resultat.regles_permanentes"))


class ErreurSaisie(Exception):
    """Paramètre inexploitable. Le message (et les éventuelles suggestions)
    sont renvoyés à l'assistant, qui doit reformuler ou demander."""

    def __init__(self, message: str, **details):
        super().__init__(message)
        self.details = details


# ─── Localisation ──────────────────────────────────────────────────────────


@dataclass
class Localisation:
    lat: float
    lng: float
    code_insee: str = ""
    commune: str = ""
    code_departement: str = ""
    # coordonnees | adresse | parcelle_cadastrale | centre_commune
    precision: str = "coordonnees"
    libelle: str = ""
    autres_communes: list[dict] = field(default_factory=list)
    # Geometrie GeoJSON de la parcelle cadastrale, quand on la connait.
    parcelle: dict | None = None

    def as_dict(self) -> dict:
        d = {
            "commune": self.commune,
            "code_insee": self.code_insee,
            "precision": self.precision,
        }
        if self.precision != "centre_commune":
            # Pas de coordonnees pour un simple centre de commune : le modele
            # les recopiait pour simuler a la place de l'agriculteur.
            d["lat"], d["lng"] = round(self.lat, 6), round(self.lng, 6)
        if self.libelle:
            cle = (
                "parcelle"
                if self.parcelle
                else (
                    "zone_choisie"
                    if self.precision == "zone_choisie"
                    else "adresse_retenue"
                )
            )
            d[cle] = self.libelle
        if self.autres_communes:
            d["autres_communes_possibles"] = self.autres_communes
        return d


def _normaliser(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = re.sub(r"[-'’\s]+", " ", texte.lower()).strip()
    return re.sub(r"\bst\b", "saint", texte)


def _resume_commune(c: dict) -> dict:
    return {
        "commune": c["nom"],
        "code_insee": c["code_insee"],
        "departement": f"{c['departement']} ({c['code_departement']})",
        "codes_postaux": c["codes_postaux"][:3],
    }


_REFERENCE_CADASTRALE = re.compile(
    r"^\s*(?:\d{3}\s*)?([0-9A-Z]{1,2})\s*[-/ ]?\s*0*(\d{1,4})\s*$"
)


def _parcelle(loc: Localisation, reference: str) -> Localisation:
    """Affine une localisation communale avec la référence cadastrale
    (« YM 28 », « ZC0045 »...)."""
    m = _REFERENCE_CADASTRALE.match(reference.upper())
    if not m:
        raise ErreurSaisie(
            f"Référence cadastrale illisible : « {reference} ». Format attendu : "
            "section (1 ou 2 caractères) et numéro, par exemple « YM 28 »."
        )
    section, numero = m.group(1).rjust(2, "0"), m.group(2).rjust(4, "0")
    p = geocodage.parcelle_cadastrale(loc.code_insee, section, numero)
    if not p:
        raise ErreurSaisie(
            f"Parcelle {section} {int(numero)} introuvable sur la commune "
            f"{loc.commune or loc.code_insee}. Vérifier la commune (une parcelle "
            "peut être sur la commune voisine) ou la référence."
        )
    geom = GEOSGeometry(json.dumps(p["geometrie"]), srid=4326)
    centre = geom.point_on_surface
    loc.lat, loc.lng = centre.y, centre.x
    loc.precision = "parcelle_cadastrale"
    loc.libelle = f"Parcelle {section} {int(numero)}, {p['commune'] or loc.commune}"
    loc.parcelle = p["geometrie"]
    loc.autres_communes = []
    return loc


def resoudre_localisation(
    *,
    commune: str = "",
    code_postal: str = "",
    adresse: str = "",
    code_insee: str = "",
    reference_cadastrale: str = "",
    lat=None,
    lng=None,
) -> Localisation:
    """Transforme ce que dit l'agriculteur (commune, référence cadastrale,
    adresse, coordonnées) en point + code INSEE, comme le clic sur la carte du
    simulateur."""
    if reference_cadastrale:
        if not (code_insee or commune or code_postal):
            raise ErreurSaisie(
                "Une référence cadastrale ne suffit pas : demander aussi la commune."
            )
        loc = resoudre_localisation(
            commune=commune, code_postal=code_postal, code_insee=code_insee
        )
        return _parcelle(loc, reference_cadastrale)
    if lat not in (None, "") and lng not in (None, ""):
        try:
            lat, lng = float(lat), float(lng)
        except (TypeError, ValueError):
            raise ErreurSaisie("lat et lng doivent être des nombres décimaux.")
        loc = Localisation(lat=lat, lng=lng, code_insee=code_insee or "")
        if not loc.code_insee:
            c = geocodage.commune_au_point(lat, lng)
            if c:
                loc.code_insee = c["code_insee"]
        if loc.code_insee:
            c = geocodage.commune_par_code(loc.code_insee)
            if c:
                loc.commune = c["nom"]
                loc.code_departement = c["code_departement"]
                if (
                    c["lat"] is not None
                    and abs(c["lat"] - lat) < 5e-4
                    and abs(c["lng"] - lng) < 5e-4
                ):
                    # Le centre de la commune n'est pas une parcelle : le
                    # garde-fou de l'aire de captage doit s'appliquer.
                    loc.precision = "centre_commune"
        return loc

    if adresse:
        resultats = geocodage.chercher_adresse(adresse)
        if not resultats:
            raise ErreurSaisie(f"Adresse introuvable : « {adresse} ».")
        r = resultats[0]
        return Localisation(
            lat=r["lat"],
            lng=r["lng"],
            code_insee=r["code_insee"] or "",
            commune=r["commune"] or "",
            code_departement=(r["code_insee"] or "")[:2],
            precision="centre_commune" if r["type"] == "municipality" else "adresse",
            libelle=r["libelle"] or "",
        )

    if code_insee:
        c = geocodage.commune_par_code(code_insee)
        if not c:
            raise ErreurSaisie(f"Code INSEE inconnu : {code_insee}.")
        return _depuis_commune(c)

    if commune or code_postal:
        candidates = geocodage.chercher_communes(nom=commune, code_postal=code_postal)
        if not candidates:
            raise ErreurSaisie(
                f"Commune introuvable : « {commune or code_postal} ». Demander "
                "l'orthographe exacte, le code postal ou une adresse."
            )
        exactes = [
            c for c in candidates if _normaliser(c["nom"]) == _normaliser(commune)
        ]
        if len(exactes) > 1:
            raise ErreurSaisie(
                f"Plusieurs communes s'appellent « {commune} ». Demander laquelle "
                "(département ou code postal) puis rappeler avec son code_insee.",
                communes_possibles=[_resume_commune(c) for c in exactes],
            )
        retenue = exactes[0] if exactes else candidates[0]
        loc = _depuis_commune(retenue)
        if not exactes and len(candidates) > 1:
            # Recherche approchee : on garde la plus peuplee mais on montre les
            # autres pour que l'assistant puisse verifier avec l'agriculteur.
            loc.autres_communes = [
                _resume_commune(c) for c in candidates if c is not retenue
            ][:4]
        return loc

    raise ErreurSaisie(
        "Localisation manquante : demander la commune, et si possible la "
        "référence cadastrale de la parcelle, une adresse ou un lieu-dit."
    )


def _depuis_commune(c: dict) -> Localisation:
    return Localisation(
        lat=c["lat"],
        lng=c["lng"],
        code_insee=c["code_insee"],
        commune=c["nom"],
        code_departement=c["code_departement"],
        precision="centre_commune",
    )


def localisation_depuis_arguments(arguments: dict) -> Localisation:
    return resoudre_localisation(
        commune=arguments.get("commune") or "",
        code_postal=arguments.get("code_postal") or "",
        adresse=arguments.get("adresse") or "",
        code_insee=arguments.get("code_insee") or "",
        reference_cadastrale=arguments.get("reference_cadastrale") or "",
        lat=arguments.get("lat"),
        lng=arguments.get("lng"),
    )


# ─── Contexte geographique (zonages, programmes applicables) ───────────────


class _CatalogSeul(MoulinetteNitrates):
    """Moulinette réduite à son catalog géographique : pas d'évaluation
    d'arbre (sans culture ni fertilisant, elle ne servirait à rien)."""

    def evaluate(self):
        pass


DUREE_CACHE_GEO_S = 3600


def _catalog_geo(loc: Localisation) -> dict:
    """Catalog géographique du point, calculé par la moulinette elle-même
    (département, région, ZV, ZAR, zonages par code INSEE).

    Mis en cache une heure : l'intersection avec les zones vulnérables (des
    polygones de millions de points) coûte jusqu'à 3 s, et une conversation
    interroge le même point trois ou quatre fois."""
    # Les couches actives entrent dans la cle : le catalog retient des
    # identifiants de zones, qui changent quand une couche est reimportee.
    couches = "-".join(
        str(pk)
        for pk in Map.objects.filter(
            is_active=True,
            map_type__in=(MAP_TYPES.zv_nitrates, MAP_TYPES.zone_action_renforcee),
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    cle = f"nitrates-mcp-catalog:{couches}:{loc.lat:.6f}:{loc.lng:.6f}:{loc.code_insee}"
    catalog = cache.get(cle)
    if catalog is None:
        data = {"lat": str(loc.lat), "lng": str(loc.lng)}
        if loc.code_insee:
            data["code_insee"] = loc.code_insee
        catalog = dict(_CatalogSeul(form_kwargs={"data": data}).catalog)
        cache.set(cle, catalog, DUREE_CACHE_GEO_S)
    return dict(catalog)


def _nom_zar(zar_zone_id) -> str:
    if zar_zone_id is None:
        return ""
    attrs = (
        Zone.objects.filter(pk=zar_zone_id).values_list("attributes", flat=True).first()
    ) or {}
    return attrs.get("NOMCOMPL") or attrs.get("NOMZAR") or ""


def _libelle_programme(scope: str, catalog: dict) -> str:
    if scope == SCOPE_ZAR:
        nom = _nom_zar(catalog.get("zar_zone_id"))
        return "Zone d'action renforcée" + (f" « {nom} »" if nom else "")
    if scope == SCOPE_REGION:
        return (
            f"Programme d'actions régional {catalog.get('region_label') or ''}".strip()
        )
    if scope == SCOPE_NATIONAL:
        return "Programme d'actions national"
    return scope


def _contour(code_insee: str):
    """Contour GEOS de la commune, ou None si le service ne répond pas."""
    if not code_insee:
        return None
    try:
        contour = geocodage.contour_commune(code_insee)
    except geocodage.GeocodageIndisponible:
        return None
    return GEOSGeometry(json.dumps(contour), srid=4326) if contour else None


def _zar_autour(geom) -> list:
    """Zones d'action renforcée (aires de captage) qui touchent `geom`.

    Préfiltre par boîte englobante (index seul) sur les couches ZAR, puis test
    exact en GEOS sur les quelques candidates. Un ST_Intersects direct laisse
    PostGIS tester d'abord les zones géantes des autres couches (ZV) avant le
    filtre de couche : 50 s mesurées sur Pau."""
    couches = Map.objects.filter(
        map_type=MAP_TYPES.zone_action_renforcee, is_active=True
    ).values_list("id", flat=True)
    zones = [
        z
        for z in Zone.objects.filter(
            map_id__in=list(couches), geometry__bboverlaps=geom
        ).only("geometry", "attributes")
        if z.geometry.intersects(geom)
    ]
    return sorted(zones, key=lambda z: _nom_zone(z))


def _zones_de_la_commune(code_insee: str):
    """(contour, aires de captage qui touchent la commune). Les identifiants
    de zones sont gardés en cache une heure, le contour l'est par le
    géocodage."""
    contour = _contour(code_insee)
    if contour is None:
        return None, []
    couches = "-".join(
        str(pk)
        for pk in Map.objects.filter(
            is_active=True, map_type=MAP_TYPES.zone_action_renforcee
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    cle = f"nitrates-mcp-zar:{couches}:{code_insee}"
    ids = cache.get(cle)
    if ids is None:
        ids = [z.pk for z in _zar_autour(contour)]
        cache.set(cle, ids, DUREE_CACHE_GEO_S)
    zones = Zone.objects.filter(pk__in=ids).only("geometry", "attributes")
    return contour, sorted(zones, key=_nom_zone)


def _points_des_zones(contour, zones) -> dict:
    """Point représentatif de chaque aire de captage (dans la commune) et
    d'une partie hors de toute aire : {"1": {...}, "hors": {...}}. Usage
    interne seulement : ces coordonnées ne sont jamais montrées au modèle."""
    points = {
        str(i + 1): _point(z.geometry.intersection(contour) or z.geometry)
        for i, z in enumerate(zones)
    }
    reste = contour
    for z in zones:
        reste = reste.difference(z.geometry)
    if not reste.empty:
        points["hors"] = _point(reste)
    return points


def _choix_de_zone(contour, zones) -> dict:
    """Ce que voit le modèle : les zones numérotées de la carte, sans
    coordonnées (il les recopiait pour simuler chaque cas lui-même)."""
    points = _points_des_zones(contour, zones)
    return {
        "zones_sur_la_carte": [
            {
                "numero": i + 1,
                "nom": _nom_zone(z),
                "type": "aire de captage (zone d'action renforcée)",
            }
            for i, z in enumerate(zones)
        ],
        "hors_zones_possible": "hors" in points,
    }


_CONSIGNE_ZONE = (
    "STOP : la réponse dépend de l'endroit exact de la parcelle. N'appeler "
    "AUCUN autre outil et ne simuler AUCUN cas (ni la zone, ni le hors zone) "
    "avant la réponse de l'agriculteur. Lui demander, en une phrase, si sa "
    "parcelle est dans la zone numérotée de la carte (laquelle) ou en dehors, "
    "ou sa référence cadastrale ; il peut aussi cliquer sur la carte. Ensuite "
    'seulement, appeler l\'outil avec zone=<numéro> ou zone="hors", ou '
    "reference_cadastrale, ou le point qu'il a cliqué."
)


def preciser_localisation(loc: Localisation, zone=None) -> dict | None:
    """Garde-fou : quand on ne connaît que la commune et qu'une aire de
    captage la touche, la règle dépend de l'endroit exact de la parcelle.

    Sans `zone` : renvoie la demande à faire à l'agriculteur (avec la carte
    pour la vue), au lieu d'une réponse réglementaire qui pourrait être
    fausse. Avec `zone` (numéro ou « hors ») : déplace le point dans la zone
    choisie et renvoie None."""
    if loc.precision != "centre_commune":
        return None
    contour, zones = _zones_de_la_commune(loc.code_insee)
    if not zones:
        return None
    choix = _choix_de_zone(contour, zones)
    if zone not in (None, ""):
        points = _points_des_zones(contour, zones)
        cible = str(zone).strip().lower()
        if cible in ("hors", "hors_zones", "hors zone", "0", "aucune", "dehors"):
            point = points.get("hors")
            libelle = f"{loc.commune}, hors aire de captage"
        else:
            numero = re.sub(r"\D", "", cible)
            point = points.get(numero)
            nom = next(
                (
                    z["nom"]
                    for z in choix["zones_sur_la_carte"]
                    if str(z["numero"]) == numero
                ),
                "",
            )
            libelle = f"{loc.commune}, zone {numero} ({nom})"
        if point is None:
            raise ErreurSaisie(
                f"Zone inconnue : « {zone} ». Valeurs possibles : "
                + ", ".join(str(z["numero"]) for z in choix["zones_sur_la_carte"])
                + " ou « hors »."
            )
        loc.lat, loc.lng = point["lat"], point["lng"]
        loc.precision, loc.libelle = "zone_choisie", libelle
        return None
    return {
        "statut": "localisation_a_preciser",
        "localisation": loc.as_dict(),
        "question": (
            f"Une aire de captage touche la commune de {loc.commune} : les règles y "
            "sont plus strictes. Votre parcelle est-elle dans la zone numérotée sur "
            "la carte, ou en dehors ?"
        ),
        **choix,
        "consigne": _CONSIGNE_ZONE,
        "_vue": {"nitrates/carte": _donnees_carte(loc, contour, zones)},
    }


def _nom_zone(zone) -> str:
    attrs = zone.attributes or {}
    return attrs.get("NOMCOMPL") or attrs.get("NOMZAR") or f"zone {zone.pk}"


def _point(geom) -> dict:
    p = geom.point_on_surface
    return {"lat": round(p.y, 6), "lng": round(p.x, 6)}


def _carte(loc: Localisation, contour, zones) -> tuple[dict, dict]:
    """Carte PNG du lieu (commune ou parcelle) et des aires de captage
    alentour, numérotées. Renvoie (image, infos pour l'assistant)."""
    parcelle = (
        GEOSGeometry(json.dumps(loc.parcelle), srid=4326) if loc.parcelle else None
    )
    point = Point(loc.lng, loc.lat, srid=4326)
    if loc.precision == "centre_commune" and contour is not None:
        emprise, titre = contour, f"{loc.commune} : où est votre parcelle ?"
    elif parcelle is not None:
        emprise, titre = parcelle.buffer(0.015), loc.libelle
    else:
        emprise = point.buffer(0.012)
        titre = loc.libelle or f"{loc.commune} : votre point"
    numerotees = [(i + 1, z.geometry) for i, z in enumerate(zones)]
    png = images.carte_png(
        emprise,
        contour=contour,
        zones=numerotees,
        parcelle=parcelle,
        point=None if loc.precision == "centre_commune" else point,
        titre=titre,
    )
    return {"png": png, "titre": titre}, {}


def _geojson(geom, tolerance=0.0002) -> dict:
    return json.loads(geom.simplify(tolerance, preserve_topology=True).geojson)


def _donnees_carte(loc: Localisation, contour, zones) -> dict:
    """Géométries pour la carte cliquable de la vue (simplifiées, ~20 m)."""
    centre = contour if contour is not None else Point(loc.lng, loc.lat, srid=4326)
    cadre = centre.envelope.buffer(0.02)
    return {
        "contour": _geojson(contour) if contour is not None else None,
        "zones": [
            {
                "numero": i + 1,
                "nom": _nom_zone(z),
                "geojson": _geojson(z.geometry.intersection(cadre)),
            }
            for i, z in enumerate(zones)
        ],
        "point": (
            None
            if loc.precision == "centre_commune"
            else {"lat": loc.lat, "lng": loc.lng}
        ),
        "parcelle": loc.parcelle,
    }


def contexte_geographique(
    loc: Localisation, catalog: dict | None = None, avec_carte: bool = True
) -> dict:
    catalog = catalog if catalog is not None else _catalog_geo(loc)
    code_dept = catalog.get("department_code")
    zonages = {}
    if catalog.get("zone_montagne_classification") not in (None, "", "non_montagne"):
        zonages["zone_montagne"] = catalog["zone_montagne_classification"]
    if catalog.get("region_code") == "44":
        zonages["zone_grand_est_1"] = bool(catalog.get("zone_grand_est_1"))
        zonages["zone_grand_est_2"] = bool(catalog.get("zone_grand_est_2"))
    if catalog.get("zone_mais_bretagne"):
        zonages["zone_mais_bretagne"] = catalog["zone_mais_bretagne"]

    en_zv = bool(catalog.get("en_zone_vulnerable"))
    contexte = {
        "localisation": loc.as_dict(),
        "departement": code_dept,
        "region": catalog.get("region_label"),
        "en_zone_vulnerable": en_zv,
        "bassin": catalog.get("bassin_label"),
        "en_zone_action_renforcee": bool(catalog.get("en_zar")),
        "zonages_particuliers": zonages,
        "simulateur_ouvert_dans_ce_departement": bool(
            code_dept
            and DepartementOuverture.objects.filter(
                code=code_dept, est_ouvert=True
            ).exists()
        ),
    }
    if en_zv:
        candidats = select_active_trees(catalog)
        contexte["programmes_applicables"] = [
            _libelle_programme(c.scope, catalog) for c in candidats
        ]

    contour, zones = _zones_de_la_commune(loc.code_insee)
    if contour is None:
        zones = _zar_autour(Point(loc.lng, loc.lat, srid=4326).buffer(0.01))
    if loc.precision == "centre_commune":
        noms = [_nom_zone(z) for z in zones]
        if noms and not catalog.get("en_zar"):
            contexte["zar_dans_la_commune"] = noms
        contexte["a_verifier"] = (
            "Point placé au centre de la commune. Les zones vulnérables et "
            "surtout les aires de captage (zones d'action renforcée) peuvent ne "
            "couvrir qu'une partie de la commune."
        )
    if avec_carte:
        contexte["_vue"] = {"nitrates/carte": _donnees_carte(loc, contour, zones)}
        if loc.precision == "centre_commune" and contour is not None and zones:
            contexte.update(_choix_de_zone(contour, zones))
        if images_png():
            try:
                image, _ = _carte(loc, contour, zones)
                contexte["_images"] = [image]
            except Exception:  # la carte image est un plus : jamais bloquante
                logger.exception("MCP : carte impossible")
        if "zones_sur_la_carte" in contexte:
            contexte["consigne"] = _CONSIGNE_ZONE
    return contexte


# ─── Catalogues (cultures, fertilisants) ───────────────────────────────────


def catalogue_cultures() -> dict:
    groupes = []
    for g in GroupeCultureUI.objects.prefetch_related("cultures").all():
        cultures = [
            {"id": c.identifiant, "libelle": c.libelle_public} for c in g.cultures.all()
        ]
        if not cultures:
            # Groupe sans sous-culture (sol non cultive) : il se choisit
            # lui-meme, avec ses champs pre-remplis.
            cultures = [{"id": g.identifiant, "libelle": g.libelle_public}]
        groupes.append({"groupe": g.libelle_public, "cultures": cultures})
    return {
        "consigne": (
            "Passer l'`id` de la culture à simuler_epandage / comparer_cultures. "
            "Culture d'hiver = semée l'année civile en cours, récoltée l'année "
            "suivante (blé, orge, colza d'hiver...). Culture de printemps = semée "
            "et récoltée la même année (maïs, tournesol, betterave, orge de "
            "printemps...). Un couvert d'interculture (CIPAN, dérobée, CIVE) "
            "se choisit selon qu'il est récolté ou non et qu'il est encore en "
            "place après le 1er janvier."
        ),
        "groupes": groupes,
    }


def _nettoyer_description(texte: str) -> str:
    return re.sub(r"\s*\[note Miro[^\]]*\]", "", texte or "").strip()


def catalogue_fertilisants() -> dict:
    categories = {}
    for f in Fertilisant.objects.all():
        entree = {
            "id": f.identifiant,
            "libelle": f.libelle_public,
            "type": f.type_reglementaire,
        }
        description = _nettoyer_description(f.description)
        if description:
            entree["precision"] = " ".join(description.split())
        categories.setdefault(f.get_categorie_display(), []).append(entree)
    return {
        "consigne": (
            "Passer l'`id` du fertilisant. Le type réglementaire (0, Ia, Ib, II, "
            "III) détermine le calendrier. Lisier de bovins ou de porcs = "
            "« dejection_sans_litiere » ; en cas de doute sur un produit, "
            "demander à l'agriculteur ou choisir une entrée « type_..._declare » "
            "s'il connaît le type indiqué sur son plan d'épandage."
        ),
        "types": LIBELLES_TYPES_FERTILISANT,
        "categories": [
            {"categorie": cat, "fertilisants": ferts}
            for cat, ferts in categories.items()
        ],
    }


def _texte_flag(valeur) -> str:
    """Valeur poussée dans la query string comme le ferait cascade.js
    (String(true) -> "true")."""
    if isinstance(valeur, bool):
        return "true" if valeur else "false"
    return "" if valeur is None else str(valeur)


def _ids_proches(identifiant: str, ids: list[str]) -> list[str]:
    cible = _normaliser(identifiant).replace(" ", "_")
    morceaux = [m for m in cible.split("_") if len(m) > 2]
    return [i for i in ids if any(m in i for m in morceaux)][:8]


def parametres_culture(culture_id: str) -> tuple[dict, str]:
    culture = (
        Culture.objects.select_related("categorie", "branche_culturale")
        .filter(identifiant=culture_id)
        .first()
    )
    if culture:
        params = {
            "categorie_culture": culture.categorie.identifiant,
            "sous_culture_form": culture.identifiant,
            "occupation_sol": culture.occupation_sol,
            "sous_culture": culture.branche_culturale.identifiant,
        }
        for cle, val in (culture.champs_prefill or {}).items():
            params[cle] = _texte_flag(val)
        return params, culture.libelle_public
    groupe = GroupeCultureUI.objects.filter(
        identifiant=culture_id, cultures__isnull=True
    ).first()
    if groupe:
        params = {"categorie_culture": groupe.identifiant}
        for cle, val in (groupe.champs_prefill or {}).items():
            params[cle] = _texte_flag(val)
        return params, groupe.libelle_public
    ids = list(Culture.objects.values_list("identifiant", flat=True))
    raise ErreurSaisie(
        f"Culture inconnue : « {culture_id} ». Utiliser un id de lister_cultures.",
        ids_proches=_ids_proches(culture_id, ids),
    )


def parametres_fertilisant(fertilisant_id: str) -> tuple[dict, dict]:
    fert = Fertilisant.objects.filter(identifiant=fertilisant_id).first()
    if not fert:
        ids = list(Fertilisant.objects.values_list("identifiant", flat=True))
        raise ErreurSaisie(
            f"Fertilisant inconnu : « {fertilisant_id} ». Utiliser un id de "
            "lister_fertilisants.",
            ids_proches=_ids_proches(fertilisant_id, ids),
        )
    params = {
        "categorie_fertilisant": fert.categorie,
        "sous_fertilisant": fert.identifiant,
        "type_fertilisant": fert.type_reglementaire,
    }
    for cle, val in (fert.champs_prefill or {}).items():
        params[cle] = _texte_flag(val)
    return params, {
        "id": fert.identifiant,
        "libelle": fert.libelle_public,
        "type": fert.type_reglementaire,
    }


def _reponses_en_parametres(reponses: dict | None) -> dict:
    params = {}
    for champ, valeur in (reponses or {}).items():
        if champ in CHAMPS_RESERVES or valeur in (None, ""):
            continue
        if isinstance(valeur, str) and _DATE_ISO.match(valeur.strip()):
            valeur = normaliser_date(valeur)
        params[str(champ)] = _texte_flag(valeur)
    # Certaines feuilles couvert (ZAR GE) bornent sur date_destruction_prevue :
    # meme alias que la matrice (cf. matrice.construire_matrice).
    if "date_destruction_couvert" in params:
        params.setdefault("date_destruction_prevue", params["date_destruction_couvert"])
    return params


# ─── Dates et calendrier ───────────────────────────────────────────────────


def normaliser_date(valeur: str) -> str:
    """'15/02', '15/2/2027' ou '2027-02-15' -> '15/02'."""
    valeur = (valeur or "").strip()
    m = _DATE_JJMM.match(valeur)
    if m:
        jour, mois = int(m.group(1)), int(m.group(2))
    else:
        m = _DATE_ISO.match(valeur)
        if not m:
            raise ErreurSaisie(
                f"Date illisible : « {valeur} ». Format attendu JJ/MM ou AAAA-MM-JJ."
            )
        mois, jour = int(m.group(1)), int(m.group(2))
    if not (1 <= mois <= 12 and 1 <= jour <= 31):
        raise ErreurSaisie(f"Date invalide : « {valeur} ».")
    return f"{jour:02d}/{mois:02d}"


def _jour_agricole(jjmm: str) -> int:
    jour, mois = (int(x) for x in jjmm.split("/"))
    return _day_of_year(jour, mois)


def _jjmm(jour_agricole: int) -> str:
    return (_DEBUT_ANNEE_AGRICOLE + timedelta(days=jour_agricole)).strftime("%d/%m")


def _plages(regimes: list[str]) -> list[dict]:
    plages = []
    debut = 0
    for i in range(1, TOTAL_JOURS + 1):
        if i == TOTAL_JOURS or regimes[i] != regimes[debut]:
            plages.append(
                {
                    "du": _jjmm(debut),
                    "au": _jjmm(i - 1),
                    "regime": regimes[debut],
                    "signification": LIBELLES_REGIME.get(
                        regimes[debut], regimes[debut]
                    ),
                }
            )
            debut = i
    return plages


def _libelle_borne(borne: str, referentiels: dict, inputs: dict) -> str:
    if not borne or "/" in borne:
        return borne
    evenement = referentiels.get("evenements_phenologiques", {}).get(borne)
    if evenement:
        return f"{evenement['libelle_public']} ({borne})"
    racine = re.split(r"[+-]", borne)[0]
    if racine in inputs:
        return f"{borne} ({inputs[racine]})"
    return borne


# ─── Simulation ────────────────────────────────────────────────────────────


class _MoulinetteGeoConnue(MoulinetteNitrates):
    """Moulinette dont la partie géographique du catalog est déjà calculée.

    comparer_cultures rejoue la même parcelle pour chaque culture : on évite
    de refaire à chaque fois les intersections PostGIS (département, ZV, ZAR),
    qui ne dépendent que du point."""

    def __init__(self, form_kwargs, geo: dict):
        self._geo = geo
        super().__init__(form_kwargs)

    def get_catalog_data(self):
        catalog = Moulinette.get_catalog_data(self)
        for cle, valeur in self._geo.items():
            catalog.setdefault(cle, valeur)
        return catalog


def _evaluateur(moulinette) -> ArbreDecisionEvaluator | None:
    for regulation in moulinette.regulations:
        for criterion in regulation.criteria.all():
            evaluator = getattr(criterion, "_evaluator", None)
            if isinstance(evaluator, ArbreDecisionEvaluator):
                return evaluator
    return None


def _question(q, referentiels) -> dict:
    d = {
        "champ": q.champ,
        "question": q.texte,
        "choix": [
            {"valeur": c["valeur"], "libelle": c.get("libelle") or str(c["valeur"])}
            for c in (q.choix or [])
        ],
    }
    if q.aide:
        d["aide"] = q.aide
    if q.parent_champ:
        d["seulement_si"] = {q.parent_champ: q.parent_valeur}
    return d


def _prescription_courte(code: str, referentiel_pc: dict, base_url: str) -> dict:
    data = referentiel_pc.get(code) or {}
    d = {
        "code": code,
        "resume": resume_texte(data.get("blocs") or [], max_car=220),
        "url": f"{base_url}/prescription/{code}/",
    }
    if data.get("mots_cles"):
        d["mots_cles"] = data["mots_cles"]
    if data.get("plafond"):
        d["plafond"] = True
        d["unite_du_plafond"] = (
            "kg d'azote potentiellement libéré jusqu'en sortie d'hiver (APLSH) par "
            "hectare, ni azote efficace ni azote total"
        )
    return d


def _resultat(evaluator, valeurs_dates: dict, date_demandee, base_url) -> dict:
    referentiels = load_referentiels()
    referentiel_pc = referentiels.get("codes_prescription", {})
    res = evaluator.regle
    inputs = {
        i["id"]: i.get("label") or i["id"]
        for i in (res.inputs_requis or [])
        if isinstance(i, dict) and i.get("id")
    }
    for i in res.inputs_requis or []:
        if isinstance(i, str):
            inputs[i] = i.replace("_", " ")

    periodes = list(res.periodes or [])
    # Meme synthese que le calendrier statique et la matrice : une regle sans
    # periode vaut pour toute l'annee.
    if not periodes and res.type in ("autorisation_sous_condition", "plafonnement"):
        periodes = [{"du": "01/07", "au": "30/06", "regime": res.type}]
    if not periodes and res.type == "interdiction":
        periodes = [{"du": "01/07", "au": "30/06"}]

    codes = list(res.codes_prescription)
    tous_plafonds = bool(codes) and all(_est_plafond(c, referentiel_pc) for c in codes)
    manquantes = [
        {"champ": cle, "question": libelle, "format": "JJ/MM"}
        for cle, libelle in inputs.items()
        if cle not in valeurs_dates
    ]

    resultat = {
        "regle": res.regle_id,
        "type_regle": res.type,
        "programme": _libelle_programme(
            evaluator.arbre_matche.scope if evaluator.arbre_matche else "",
            evaluator.catalog,
        ),
        "periodes_reglementaires": [
            {
                "du": _libelle_borne(p.get("du"), referentiels, inputs),
                "au": _libelle_borne(p.get("au"), referentiels, inputs),
                "regime": p.get("regime") or res.type,
                **({"si": p["condition"]} if p.get("condition") else {}),
            }
            for p in periodes
        ],
        "prescriptions": [
            _prescription_courte(c, referentiel_pc, base_url) for c in codes
        ],
    }
    for champ in ("message", "texte", "texte_condition", "source_juridique"):
        if getattr(res, champ, None):
            resultat[champ] = getattr(res, champ)
    if res.plafond_azote_kg_n_ha:
        resultat["plafond_azote_kg_n_ha"] = res.plafond_azote_kg_n_ha
    if res.note:
        note = referentiels.get("notes", {}).get(res.note) or {}
        resultat["note"] = note.get("libelle_court") or res.note

    if res.type == "non_applicable":
        resultat["calendrier"] = []
        return resultat
    if manquantes:
        # Les fenetres bornees par ces dates seraient ignorees par le calcul :
        # le calendrier sortirait plus permissif que la regle. On demande.
        resultat["dates_a_preciser"] = manquantes
        resultat["calendrier"] = None
        resultat["consigne"] = (
            "Ne pas déduire le calendrier des periodes_reglementaires : demander "
            "ces dates à l'agriculteur (ou reprendre celles qu'il a déjà données) "
            "puis rappeler simuler_epandage avec reponses={champ: 'JJ/MM'}."
        )
        resultat["a_la_date"] = (
            {"date": date_demandee, "regime": "depend_des_dates_a_preciser"}
            if date_demandee
            else None
        )
        return resultat

    regimes = compute_regime_par_jour(
        res.type, periodes, valeurs_dates, tous_plafonds=tous_plafonds
    )
    resultat["calendrier"] = _plages(regimes)
    resultat["calendrier_lecture"] = "année culturale du 1er juillet au 30 juin"
    if date_demandee:
        regime = regimes[_jour_agricole(date_demandee)]
        resultat["a_la_date"] = {
            "date": date_demandee,
            "regime": regime,
            "signification": LIBELLES_REGIME.get(regime, regime),
        }
    return resultat


def _lien_simulation(base_url: str, params: dict) -> str:
    return f"{base_url}/?{urlencode(params)}"


def simuler(
    loc: Localisation,
    culture_id: str,
    fertilisant_id: str,
    *,
    reponses: dict | None = None,
    date_demandee: str = "",
    base_url: str = "",
    geo: dict | None = None,
) -> dict:
    """Une simulation, exactement comme une soumission du formulaire public."""
    params_culture, libelle_culture = parametres_culture(culture_id)
    params_fert, fertilisant = parametres_fertilisant(fertilisant_id)
    date_demandee = normaliser_date(date_demandee) if date_demandee else ""

    params = {"lat": str(loc.lat), "lng": str(loc.lng)}
    if loc.code_insee:
        params["code_insee"] = loc.code_insee
    params.update(params_culture)
    params.update(params_fert)
    params_reponses = _reponses_en_parametres(reponses)
    params.update(params_reponses)

    if geo is None:
        geo = _catalog_geo(loc)
        seule = True  # pas dans une comparaison : regles et image ici
    else:
        seule = False
    moulinette = _MoulinetteGeoConnue(form_kwargs={"data": dict(params)}, geo=geo)
    catalog = moulinette.catalog

    sortie = {
        "saisie": {
            "culture": {"id": culture_id, "libelle": libelle_culture},
            "fertilisant": fertilisant,
        },
        "a_annoncer": _a_annoncer(fertilisant, libelle_culture),
        "lien_simulation": _lien_simulation(base_url, params),
        "avertissement": AVERTISSEMENT,
    }
    if seule:
        # Reponses deja donnees : la vue les renvoie avec les nouvelles.
        sortie["_vue"] = {"nitrates/reponses": dict(reponses or {})}

    code_dept = catalog.get("department_code")
    if not DepartementOuverture.objects.filter(
        code=code_dept, est_ouvert=True
    ).exists():
        sortie["statut"] = "departement_non_ouvert"
        sortie["explication"] = (
            f"Le simulateur n'est pas encore ouvert pour le département "
            f"{code_dept or 'de ce point'} : pas de réponse réglementaire à donner."
        )
        sortie.pop("lien_simulation")
        return sortie
    if not catalog.get("en_zone_vulnerable"):
        sortie["statut"] = "hors_zone_vulnerable"
        sortie["explication"] = (
            "Ce point est hors zone vulnérable : les programmes d'actions nitrates "
            "(calendrier d'interdiction d'épandage, plafonds) ne s'y appliquent "
            "pas. D'autres réglementations peuvent s'appliquer."
        )
        return sortie

    evaluator = _evaluateur(moulinette)
    if evaluator is None:
        sortie["statut"] = "non_disponible"
        sortie["explication"] = "Le simulateur n'a pas pu évaluer ce cas."
        return sortie

    if evaluator.questions_subsidiaires:
        referentiels = load_referentiels()
        sortie["statut"] = "questions_complementaires"
        sortie["questions"] = [
            _question(q, referentiels)
            for q in evaluator.questions_subsidiaires.questions
        ]
        sortie["consigne"] = (
            "La vue affiche ces questions en boutons sous la réponse : ne pas "
            "les recopier avec leurs choix. Écrire seulement, en une ligne, ce "
            "qu'il faut préciser et qu'on peut répondre dans la vue ou ici. "
            "Puis rappeler l'outil avec `reponses` = {champ: valeur choisie}. "
            "Ne pas répondre à sa place : la règle dépend de la réponse."
        )
        return sortie

    if evaluator.regle is None or evaluator.regle.a_completer:
        sortie["statut"] = "non_disponible"
        sortie["explication"] = (
            "Ce cas n'est pas encore couvert par le simulateur (règle en cours "
            "de rédaction ou donnée géographique manquante)."
        )
        return sortie

    valeurs_dates = {
        k: v for k, v in params_reponses.items() if k.startswith("date_") and "/" in v
    }
    sortie["statut"] = "resultat"
    sortie["resultat"] = _resultat(evaluator, valeurs_dates, date_demandee, base_url)
    if seule:
        # Pas en comparaison (qui donne regles et image une fois pour toutes).
        sortie["regles_permanentes"] = regles_permanentes()
        if sortie["resultat"].get("calendrier") and images_png():
            sortie["_images"] = [
                {
                    "png": images.calendrier_png(
                        [{"plages": sortie["resultat"]["calendrier"]}],
                        date_demandee,
                        libelle_culture,
                        f"{_produit_court(params_fert, fertilisant)} · "
                        f"{sortie['resultat']['programme']}",
                    ),
                    "titre": "Calendrier d'épandage",
                }
            ]
    return sortie


def _court(texte: str, n: int) -> str:
    return texte if len(texte) <= n else texte[: n - 1].rstrip(" ,·") + "…"


def _produit_court(params_fert: dict, fertilisant: dict) -> str:
    """« Lisiers, type II » plutôt que le libellé réglementaire complet."""
    from envergo.nitrates.constants import CategorieFertilisant

    try:
        categorie = CategorieFertilisant(params_fert["categorie_fertilisant"]).label
    except ValueError:
        categorie = fertilisant["libelle"]
    return f"{categorie}, {fertilisant['type'].replace('type_', 'type ')}"


def _comparer(
    loc: Localisation,
    combinaisons: list[dict],
    date_demandee: str,
    *,
    reponses: dict | None,
    base_url: str,
    entete: dict,
    titre_image: str,
) -> dict:
    """Moteur commun des comparaisons : une simulation par combinaison
    {cle, libelle, culture, fertilisant}, même parcelle, même date. Les
    combinaisons qui attendent une précision sont dessinées, jamais omises."""
    date_demandee = normaliser_date(date_demandee)
    geo = _catalog_geo(loc)
    contexte = contexte_geographique(loc, geo, avec_carte=False)
    sortie = {
        **entete,
        "date": date_demandee,
        "parcelle": contexte,
        "avertissement": AVERTISSEMENT,
    }
    if not contexte["simulateur_ouvert_dans_ce_departement"]:
        sortie["statut"] = "departement_non_ouvert"
        return sortie
    if not contexte["en_zone_vulnerable"]:
        sortie["statut"] = "hors_zone_vulnerable"
        return sortie

    lignes = {
        "autorise": [],
        "sous_conditions": [],
        "interdit": [],
        "a_preciser": [],
        "non_couvert": [],
    }
    # Les memes questions reviennent pour plusieurs lignes (plan d'epandage
    # ICPE, fertirrigation...) : on les regroupe pour que l'assistant les pose
    # une seule fois, puis rappelle l'outil avec `reponses`.
    questions: dict[str, dict] = {}
    rangees = []
    for combinaison in combinaisons:
        r = simuler(
            loc,
            combinaison["culture"],
            combinaison["fertilisant"],
            reponses=reponses,
            date_demandee=date_demandee,
            base_url=base_url,
            geo=geo,
        )
        libelle = combinaison["libelle"]
        ligne = {"id": combinaison["cle"], "libelle": libelle}
        en_attente = []
        if r["statut"] == "questions_complementaires":
            en_attente = r["questions"]
        elif r["statut"] == "resultat":
            en_attente = r["resultat"].get("dates_a_preciser") or []
        else:
            # Cas non couvert par le simulateur (ou reponse qui ne correspond
            # a aucune branche) : on le dit plutot que de le faire disparaitre.
            lignes["non_couvert"].append(ligne)
            continue
        if en_attente:
            for q in en_attente:
                entree = questions.setdefault(q["champ"], {**q, "lignes": []})
                entree["lignes"].append(combinaison["cle"])
            ligne["en_attente_de"] = [q["champ"] for q in en_attente]
            lignes["a_preciser"].append(ligne)
            # Dessinee quand meme : une ligne qui disparait de la matrice
            # laisse croire que tout est permis.
            rangees.append(
                {
                    "libelle": libelle,
                    "plages": None,
                    "a_preciser": " ; ".join(
                        _court(q["question"], 70) for q in en_attente
                    ),
                }
            )
            continue
        # Lien vers la page de resultat de CETTE ligne (un lien partiel
        # retombait au milieu du formulaire).
        ligne["lien_simulation"] = r["lien_simulation"]
        if r["resultat"].get("calendrier"):
            rangees.append(
                {
                    "libelle": libelle,
                    "plages": r["resultat"]["calendrier"],
                    "lien": r["lien_simulation"],
                }
            )
        regime = (r["resultat"].get("a_la_date") or {}).get("regime")
        if regime == "interdiction":
            lignes["interdit"].append(ligne)
        elif regime in ("autorisation_sous_condition", "plafonnement"):
            ligne["prescriptions"] = [p["code"] for p in r["resultat"]["prescriptions"]]
            lignes["sous_conditions"].append(ligne)
        elif regime == "libre":
            lignes["autorise"].append(ligne)
    sortie["statut"] = "resultat"
    sortie["lignes"] = lignes
    sortie["regles_permanentes"] = regles_permanentes()
    sortie["_vue"] = {
        "nitrates/rangees": rangees,
        "nitrates/titre": titre_image,
        "nitrates/reponses": dict(reponses or {}),
    }
    if rangees and images_png():
        programmes = " / ".join(contexte.get("programmes_applicables") or [])
        sortie["_images"] = [
            {
                "png": images.calendrier_png(
                    rangees, date_demandee, titre_image, f"{loc.commune} · {programmes}"
                ),
                "titre": titre_image,
            }
        ]
    if questions:
        sortie["questions_a_poser"] = list(questions.values())
        sortie["_vue"]["nitrates/questions"] = list(questions.values())
    return sortie


def comparer_cultures(
    loc: Localisation,
    fertilisant_id: str,
    date_demandee: str,
    *,
    reponses: dict | None = None,
    base_url: str = "",
    cultures: list[str] | None = None,
) -> dict:
    """« Sur quelles cultures puis-je épandre ce produit à telle date ? » :
    une simulation par culture du catalogue (ou par culture de `cultures`),
    même parcelle, même date."""
    _, fertilisant = parametres_fertilisant(fertilisant_id)
    for culture_id in cultures or []:
        parametres_culture(culture_id)  # id inconnu : erreur de saisie
    combinaisons = [
        {
            "cle": culture["id"],
            "libelle": _libelle_dans_groupe(groupe["groupe"], culture["libelle"]),
            "culture": culture["id"],
            "fertilisant": fertilisant_id,
        }
        for groupe in catalogue_cultures()["groupes"]
        for culture in groupe["cultures"]
        if not cultures or culture["id"] in cultures
    ]
    type_ = fertilisant["type"].replace("type_", "type ")
    sortie = _comparer(
        loc,
        combinaisons,
        date_demandee,
        reponses=reponses,
        base_url=base_url,
        entete={"fertilisant": fertilisant},
        titre_image=f"{fertilisant['libelle']} ({type_}) : où épandre le "
        f"{normaliser_date(date_demandee)} ?",
    )
    if sortie.get("statut") == "resultat":
        sortie["cultures"] = sortie.pop("lignes")
        sortie["a_annoncer"] = _a_annoncer(fertilisant)
        sortie["consigne"] = (
            "Commencer par a_annoncer (produit et type retenus). Résumer par "
            "groupe sans tout énumérer, en distinguant interculture courte et "
            "longue. Les cultures « a_preciser » ne sont PAS autorisées : dire de "
            "quoi elles dépendent et poser les questions_a_poser (une fois "
            "chacune), puis rappeler l'outil avec `reponses`."
        )
    return sortie


def comparer_fertilisants(
    loc: Localisation,
    culture_id: str,
    date_demandee: str,
    *,
    reponses: dict | None = None,
    base_url: str = "",
    fertilisants: list[str] | None = None,
) -> dict:
    """« Je ne sais pas encore quoi épandre » : pour une culture, le calendrier
    de chaque type de fertilisant (0, Ia, Ib, II, II digestat, III), avec un
    produit représentatif par type (mêmes lignes que la matrice admin)."""
    from envergo.nitrates.matrice import LIGNES_FERTILISANTS

    _, libelle_culture = parametres_culture(culture_id)
    combinaisons = []
    if fertilisants:
        # Produits precis a comparer (ex. deux composts) : une ligne chacun
        for fertilisant_id in fertilisants:
            _, fert = parametres_fertilisant(fertilisant_id)
            combinaisons.append(
                {
                    "cle": fertilisant_id,
                    "libelle": f"{_court(fert['libelle'], 60)} "
                    f"({fert['type'].replace('type_', 'type ')})",
                    "culture": culture_id,
                    "fertilisant": fertilisant_id,
                }
            )
    else:
        exemples = dict(
            Fertilisant.objects.values_list("identifiant", "libelle_public")
        )
        for ligne in LIGNES_FERTILISANTS:
            fertilisant_id = ligne["contexte"]["sous_fertilisant"]
            exemple = exemples.get(fertilisant_id, "")
            combinaisons.append(
                {
                    "cle": ligne["id"],
                    "libelle": f"{ligne['label']} (ex. {_court(exemple, 45).lower()})",
                    "culture": culture_id,
                    "fertilisant": fertilisant_id,
                }
            )
    sortie = _comparer(
        loc,
        combinaisons,
        date_demandee,
        reponses=reponses,
        base_url=base_url,
        entete={"culture": {"id": culture_id, "libelle": libelle_culture}},
        titre_image=(
            f"{libelle_culture} : comparaison des produits"
            if fertilisants
            else f"{libelle_culture} : calendrier par type de fertilisant"
        ),
    )
    if sortie.get("statut") == "resultat":
        sortie["types"] = sortie.pop("lignes")
        sortie["consigne"] = (
            "Présenter le calendrier par type (la vue l'affiche) sans le recopier. "
            "Les types « a_preciser » ne sont PAS autorisés : dire de quoi ils "
            "dépendent et poser les questions_a_poser, puis rappeler l'outil avec "
            "`reponses`. Rappeler que le type figure sur l'étiquette ou l'analyse "
            "du produit."
        )
    return sortie


def _libelle_dans_groupe(groupe: str, libelle: str) -> str:
    """« Interculture courte · Couvert récolté… » : sans le groupe, les deux
    couverts d'interculture courte (toujours verts) passaient pour tous les
    couverts."""
    if "interculture" in groupe.lower():
        nom = re.sub(r"^couvert d'", "", groupe, flags=re.I)
        return f"{nom[:1].upper()}{nom[1:]} · {libelle}"
    return libelle


def _a_annoncer(fertilisant: dict, libelle_culture: str = "") -> str:
    type_ = fertilisant["type"].replace("type_", "type ")
    texte = f"Produit retenu : {fertilisant['libelle']} ({type_})"
    if libelle_culture:
        texte += f" ; culture : {libelle_culture}"
    return texte + ". Le dire à l'agriculteur pour qu'il corrige si ce n'est pas ça."


# ─── Contenus (prescriptions, definitions) ─────────────────────────────────


def _texte_riche(valeur) -> str:
    if isinstance(valeur, list):
        return "".join(
            s if isinstance(s, str) else (s or {}).get("texte", "") for s in valeur
        )
    return valeur or ""


def blocs_en_texte(blocs, profondeur=0) -> str:
    """Contenu riche (blocs typés) -> texte brut façon markdown, lisible par
    un assistant (le HTML DSFR ne lui sert à rien)."""
    if isinstance(blocs, dict):
        blocs = blocs.get("blocs") or []
    lignes = []

    def items(liste, niveau):
        for item in liste or []:
            item = item if isinstance(item, dict) else {"texte": item}
            lignes.append(f"{'  ' * niveau}- {_texte_riche(item.get('texte'))}")
            items(item.get("enfants"), niveau + 1)

    for bloc in blocs or []:
        data = (bloc or {}).get("data") or {}
        type_bloc = (bloc or {}).get("type")
        if type_bloc == "titre_principal":
            lignes.append(f"# {_texte_riche(data.get('texte'))}")
        elif type_bloc == "titre_paragraphe":
            lignes.append(f"## {_texte_riche(data.get('texte'))}")
        elif type_bloc in ("paragraphe", "citation"):
            lignes.append(_texte_riche(data.get("texte")))
        elif type_bloc == "liste":
            items(data.get("items"), 0)
        elif type_bloc == "foldable":
            lignes.append(f"## {data.get('titre') or ''}")
            lignes.append(blocs_en_texte(data.get("blocs"), profondeur + 1))
        elif type_bloc == "tableau":
            for ligne in data.get("lignes") or []:
                if isinstance(ligne, list):
                    lignes.append(" | ".join(_texte_riche(c) for c in ligne))
    return "\n".join(ligne for ligne in lignes if ligne.strip())


def _liens_cites(blocs) -> list[str]:
    """Identifiants des LienReference cités dans un contenu riche (segments
    `lien_ref`), dans l'ordre d'apparition."""
    trouves = []

    def parcourir(noeud):
        if isinstance(noeud, dict):
            ref = noeud.get("lien_ref")
            if ref and ref not in trouves:
                trouves.append(ref)
            for valeur in noeud.values():
                parcourir(valeur)
        elif isinstance(noeud, list):
            for valeur in noeud:
                parcourir(valeur)

    parcourir(blocs)
    return trouves


def _url_absolue(url: str, base_url: str) -> str:
    return url if url.startswith(("http://", "https://")) else f"{base_url}{url}"


def _titre_lien(libelle: str) -> str:
    titre = re.sub(r"^consultez\s+", "", libelle or "", flags=re.I)
    return titre[:1].upper() + titre[1:]


def lire_document(identifiant: str = "", base_url: str = "") -> dict:
    """Texte d'un document de référence (annexe d'un arrêté...) cité par une
    prescription. Le texte est extrait une fois pour toutes à côté du PDF
    (même nom en .txt), pour que l'assistant réponde sans ouvrir le PDF."""
    from django.contrib.staticfiles import finders

    from envergo.nitrates.models_referentiels import LienReference

    if not identifiant:
        return {
            "documents": [
                {"identifiant": lien.identifiant, "titre": _titre_lien(lien.libelle)}
                for lien in LienReference.objects.order_by("identifiant")
            ]
        }
    lien = LienReference.objects.filter(identifiant=identifiant).first()
    if not lien:
        raise ErreurSaisie(f"Document inconnu : « {identifiant} ».")
    sortie = {
        "identifiant": lien.identifiant,
        "titre": _titre_lien(lien.libelle),
        "url": _url_absolue(lien.url, base_url),
    }
    texte = None
    if lien.url.startswith("/static/") and lien.url.endswith(".pdf"):
        relatif = lien.url.removeprefix("/static/").removesuffix(".pdf")
        chemin = finders.find(relatif + ".txt")
        if chemin:
            with open(chemin, encoding="utf-8") as fichier:
                texte = fichier.read().strip()
    if texte:
        sortie["texte"] = texte
    else:
        sortie["explication"] = "Texte non disponible : donner le lien du document."
    return sortie


def lire_prescription(code: str, base_url: str = "") -> dict:
    code = (code or "").strip().lower()
    pc = CodePrescription.objects.filter(identifiant=code).first()
    if not pc:
        raise ErreurSaisie(f"Prescription inconnue : « {code} ».")
    d = {
        "code": pc.identifiant,
        "texte": blocs_en_texte(pc.blocs),
        "url": f"{base_url}/prescription/{pc.identifiant}/",
    }
    if pc.mots_cles:
        d["mots_cles"] = pc.mots_cles
    if pc.plafond:
        d["plafond"] = True
    from envergo.nitrates.models_referentiels import LienReference

    cites = _liens_cites(pc.blocs)
    if cites:
        liens = {
            lien.identifiant: lien
            for lien in LienReference.objects.filter(identifiant__in=cites)
        }
        d["documents_cites"] = [
            {
                "identifiant": ident,
                "titre": _titre_lien(liens[ident].libelle),
                "url": _url_absolue(liens[ident].url, base_url),
            }
            for ident in cites
            if ident in liens
        ]
        d["consigne"] = (
            "Si la question porte sur un document cité, le lire avec lire_document."
        )
    return d


def chercher_definition(terme: str, base_url: str = "") -> dict:
    from envergo.nitrates.contenu_rich.glossaire import load_definitions

    cible = _normaliser(terme)
    if not cible:
        raise ErreurSaisie("Terme vide.")
    trouvees = []
    definitions = load_definitions()
    for d in definitions:
        variantes = [_normaliser(v) for v in [d.titre_public, *d.liste_termes] if v]
        texte = blocs_en_texte(d.liste_blocs)
        if cible in variantes:
            score = 3
        elif any(cible in v or v in cible for v in variantes):
            score = 2
        elif re.search(rf"\b{re.escape(cible)}\b", _normaliser(texte)):
            # Terme cite dans le corps d'une definition (CIPAN est explique
            # dans « Couvert vegetal d'interculture »).
            score = 1
        else:
            continue
        trouvees.append((score, d, texte))
    trouvees.sort(key=lambda t: -t[0])
    if not trouvees:
        # Trace pour l'equipe : ce que les agriculteurs cherchent sans trouver
        # de definition officielle (pistes pour le glossaire).
        logger.info("MCP : terme sans définition officielle : %s", terme)
        return {
            "terme": terme,
            "definitions": [],
            "explication": "Pas de définition officielle pour ce terme dans le simulateur.",
            "termes_disponibles": [d.titre_public for d in definitions],
        }
    return {
        "terme": terme,
        "definitions": [
            {
                "titre": d.titre_public,
                "texte": texte,
                "url": f"{base_url}/definitions/#{d.ancre}",
            }
            for _, d, texte in trouvees[:3]
        ],
    }


# ─── Calcul APLSH (plan de fumure) ─────────────────────────────────────────

PLAFOND_APLSH_DEFAUT = 70  # 7e PAN, mesure 1 (couverts, prairies)
ELEVAGE_HORS_CATEGORIE = (
    "compost_effluents_elevage",
    "compost_fientes_volailles",
    "effluents_peu_charges_elevage",
)


def calculer_aplsh(
    loc: Localisation,
    fertilisant_id: str,
    date_apport: str,
    *,
    dose=None,
    teneur_n=None,
    variante: str = "",
    plafond=None,
) -> dict:
    """Azote potentiellement libéré jusqu'en sortie d'hiver d'un apport, et
    dose maximale pour rester sous le plafond. Même moteur que la calculette
    admin (aplsh.calculer), avec le référentiel GREN de la région du point."""
    from envergo.nitrates.aplsh import (
        PLAFOND_EFFLUENTS_ELEVAGE_KG_N_HA,
        calculer,
        saison_apport,
    )
    from envergo.nitrates.models_aplsh import ReferentielAPLSH

    catalog = _catalog_geo(loc)
    region = catalog.get("region_code") or ""
    referentiel = ReferentielAPLSH.objects.filter(
        region_code=region, actif=True
    ).first()
    if referentiel is None:
        disponibles = ", ".join(
            r.get_region_code_display()
            for r in ReferentielAPLSH.objects.filter(actif=True)
        )
        return {
            "statut": "non_disponible",
            "explication": (
                f"Pas de référentiel APLSH pour {catalog.get('region_label') or 'cette région'} "
                f"dans le simulateur (disponibles : {disponibles or 'aucun'})."
            ),
        }

    lignes = [p for p in referentiel.produits() if p["fertilisant"] == fertilisant_id]
    if not lignes:
        connus = sorted({p["fertilisant"] for p in referentiel.produits()})
        raise ErreurSaisie(
            f"Le référentiel {referentiel.get_region_code_display()} ne donne pas "
            f"de coefficient pour « {fertilisant_id} ».",
            fertilisants_du_referentiel=connus,
        )
    if len(lignes) > 1:
        cible = _normaliser(variante)
        # Exacte d'abord : « Lisier de bovins » est inclus dans « Lisier de
        # bovins non dilue » et ne serait jamais choisi par inclusion seule.
        choisies = [p for p in lignes if cible and cible == _normaliser(p["variante"])]
        if not choisies:
            choisies = [
                p for p in lignes if cible and cible in _normaliser(p["variante"])
            ]
        if len(choisies) != 1:
            return {
                "statut": "elements_manquants",
                "manque": [
                    {
                        "element": "variante",
                        "question": "Quel produit exactement ?",
                        "choix": [p["variante"] for p in lignes],
                    }
                ],
                "consigne": "Demander lequel, puis rappeler avec `variante`.",
            }
        lignes = choisies
    produit = lignes[0]

    n_total = produit["n_total"]
    source_n = "référentiel régional"
    if teneur_n not in (None, ""):
        n_total, source_n = float(teneur_n), "analyse ou étiquette de l'agriculteur"
    if n_total is None:
        return {
            "statut": "elements_manquants",
            "manque": [
                {
                    "element": "teneur_n",
                    "question": (
                        "Quelle est la teneur en azote total du produit (kg N par "
                        f"{'tonne' if produit['unite'] == 't' else 'm³'}, sur l'analyse "
                        "ou le bon de livraison) ?"
                    ),
                }
            ],
            "consigne": (
                f"Le référentiel {referentiel.get_region_code_display()} ne donne pas "
                "la teneur de ce produit : la demander, puis rappeler avec teneur_n."
            ),
        }

    jjmm = normaliser_date(date_apport)
    jour, mois = (int(x) for x in jjmm.split("/"))
    annee = 2025 if mois >= 7 else 2026  # annee quelconque, seul JJ/MM compte
    saison = saison_apport(date(annee, mois, jour), referentiel.fin_apports_ete)
    p = produit["p_ete"] if saison == "ete" else produit["p_automne"]

    categorie = (
        Fertilisant.objects.filter(identifiant=fertilisant_id)
        .values_list("categorie", flat=True)
        .first()
    )
    elevage = (
        categorie in ("fumiers", "lisiers") or fertilisant_id in ELEVAGE_HORS_CATEGORIE
    )
    plafond_utilise = (
        float(plafond) if plafond not in (None, "") else PLAFOND_APLSH_DEFAUT
    )
    resultat = calculer(
        plafond_utilise,
        n_total,
        p,
        saison,
        dose=float(dose) if dose not in (None, "") else None,
        plafond_azote_total=PLAFOND_EFFLUENTS_ELEVAGE_KG_N_HA if elevage else None,
    )
    unite_dose = "t/ha" if produit["unite"] == "t" else "m³/ha"
    sortie = {
        "statut": "resultat",
        "referentiel": referentiel.intitule or referentiel.get_region_code_display(),
        "produit": produit["libelle"],
        "teneur_n_kg_par_unite": n_total,
        "teneur_n_source": source_n,
        "date_apport": jjmm,
        "saison": "été" if saison == "ete" else "automne",
        "coefficient_p": p,
        "plafond_kg_aplsh_ha": plafond_utilise,
        "plafond_par_defaut": plafond in (None, ""),
        "dose_max": f"{resultat.dose_max_affichee:g} {unite_dose}".replace(".", ","),
        "dose_max_limitee_par": (
            "le plafond APLSH"
            if resultat.limite == "aplsh"
            else f"les {PLAFOND_EFFLUENTS_ELEVAGE_KG_N_HA} kg d'azote total des "
            "effluents d'élevage"
        ),
        "formule": "APLSH = dose × teneur en azote total × coefficient p",
        "avertissement": AVERTISSEMENT,
    }
    if resultat.dose is not None:
        sortie.update(
            {
                "dose": f"{resultat.dose:g} {unite_dose}".replace(".", ","),
                "aplsh_kg_ha": round(resultat.aplsh, 1),
                "conforme": resultat.conforme,
            }
        )
        if not resultat.conforme:
            sortie["depassement_pct"] = round(resultat.depassement_pct)
    if sortie["plafond_par_defaut"]:
        sortie["consigne"] = (
            "Plafond par défaut de 70 kg : le remplacer par celui de la "
            "prescription de plafond renvoyée par simuler_epandage (35 kg en aire "
            "de captage du Grand Est, par exemple)."
        )
    return sortie


# ─── Choix a faire par l'agriculteur (culture, produit) ─────────────────────

MOTS_COUVERT = ("couvert", "cipan", "interculture", "derobee", "derobe", "cive")
MOTS_PRODUIT = {
    "fumier": "fumiers",
    "lisier": "lisiers",
    "compost": "composts",
    "digestat": "digestats",
    "engrais": "engrais_mineral",
    "mineral": "engrais_mineral",
    "ammonitrate": "engrais_mineral",
    "boue": "boues",
}


def _choix_culture(texte: str) -> list[dict] | None:
    """None si `texte` désigne une culture précise ; sinon les cultures entre
    lesquelles l'agriculteur doit choisir (groupe du formulaire, ou mot
    générique comme « couvert » ou « CIPAN »)."""
    if Culture.objects.filter(identifiant=texte).exists():
        return None
    if GroupeCultureUI.objects.filter(
        identifiant=texte, cultures__isnull=True
    ).exists():
        return None  # groupe sans sous-culture (sol non cultive) : deja precis
    cible = _normaliser(texte).replace(" ", "_")
    groupes = GroupeCultureUI.objects.prefetch_related("cultures")
    if any(mot in cible for mot in MOTS_COUVERT):
        retenus = [g for g in groupes if "couvert" in g.identifiant]
    else:
        retenus = [g for g in groupes if g.identifiant == texte]
    choix = [
        {
            "valeur": c.identifiant,
            "libelle": _libelle_dans_groupe(g.libelle_public, c.libelle_public),
        }
        for g in retenus
        for c in g.cultures.all()
    ]
    return choix or None


def _choix_fertilisant(texte: str) -> list[dict] | None:
    if Fertilisant.objects.filter(identifiant=texte).exists():
        return None
    cible = _normaliser(texte).replace(" ", "_")
    categories = [cat for mot, cat in MOTS_PRODUIT.items() if mot in cible]
    if texte in dict(Fertilisant._meta.get_field("categorie").choices):
        categories = [texte]
    if not categories:
        return None
    return [
        {
            "valeur": f.identifiant,
            "libelle": f"{f.libelle_public} ({f.type_reglementaire.replace('type_', 'type ')})",
        }
        for f in Fertilisant.objects.filter(categorie__in=categories)
    ] or None


def demande_de_choix(arguments: dict) -> dict | None:
    """Garde-fou : une culture ou un produit générique (« couvert », « CIPAN »,
    « fumier ») ne doit pas être tranché par l'assistant à la place de
    l'agriculteur (récolté ou non, en place après le 1er janvier, type...).
    Renvoie le choix à présenter (boutons de la vue), ou None. Un choix
    unique est appliqué directement."""
    questions = {
        "culture": "Quel couvert ou quelle culture exactement ?",
        "fertilisant": "Quel produit exactement ?",
    }
    for champ, trouver in (
        ("culture", _choix_culture),
        ("fertilisant", _choix_fertilisant),
    ):
        valeur = arguments.get(champ)
        if not valeur:
            continue
        choix = trouver(str(valeur))
        if not choix:
            continue
        if len(choix) == 1:
            arguments[champ] = choix[0]["valeur"]
            continue
        return {
            "statut": "choix_a_faire",
            "champ": champ,
            "question": questions[champ],
            "choix": choix,
            "consigne": (
                "Ne pas choisir à la place de l'agriculteur : la vue lui montre les "
                "choix en boutons ; attendre sa réponse, puis rappeler l'outil avec "
                f"{champ}=<valeur choisie>."
            ),
        }
    return None
