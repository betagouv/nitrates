"""Choix verifie du point de preview d'un arbre (carte #584).

Le resolveur de preview.py choisit un point par heuristique (contraintes SIG du
chemin, puis point par defaut du scope). Il rate quand l'heuristique ne connait
pas la zone (ZAR hors Grand Est), quand le point sort de la region de l'arbre
(note 5 a Toulouse pour un PAR Grand Est) ou quand un arbre plus specifique
capte la preview (feuille du PAN previsualisee a Reims, ou le PAR Grand Est
s'active).

Ici on VERIFIE : pour chaque point candidat on regarde ce que le moteur verrait
(region, ZV, couches ZAR, valeurs des resolveurs catalogue) et on prend le
premier qui active l'arbre et satisfait les contraintes du chemin. Evaluation
paresseuse, du moins couteux au plus couteux, chaque mesure cachee : un rendu
d'arbre appelle ceci des centaines de fois. Lecture seule.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

_TTL_SECONDES = 3600
_cache: dict = {}

_REGION_POINTS = Path(__file__).resolve().parents[1] / "scripts" / "region_points.json"
_ABSENT = object()
_MAX_REQUETES_ZV = 5


def vider_cache() -> None:
    _cache.clear()


def _memo(cle, calcul):
    entree = _cache.get(cle)
    if entree is not None and time.monotonic() - entree[0] < _TTL_SECONDES:
        return entree[1]
    valeur = calcul()
    _cache[cle] = (time.monotonic(), valeur)
    return valeur


def _cle(point: dict) -> tuple:
    return (point.get("lat"), point.get("lng"), point.get("code_insee") or "")


def _points_reservoir() -> list[dict]:
    """Points connus : ceux de preview.py puis ceux generes par region (dont
    on connait deja la region, ce qui evite une requete)."""

    def _calcul():
        from envergo.nitrates.yaml_admin.preview import _POINTS

        # Statut ZV connu (points verifies a leur creation) : evite la requete
        # PostGIS sur la couche ZV, tres couteuse (plusieurs secondes/point).
        points = [dict(p, _zv=(nom != "hors_zv")) for nom, p in _POINTS.items()]
        try:
            data = json.loads(_REGION_POINTS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        for region, profils in data.items():
            for nom_profil, p in (profils or {}).items():
                if isinstance(p, dict) and p.get("lat") and p.get("lng"):
                    points.append(
                        {
                            "lat": str(p["lat"]),
                            "lng": str(p["lng"]),
                            "code_insee": str(p.get("code_insee") or ""),
                            "_region": str(region),
                            "_zv": not nom_profil.startswith("hors_zv"),
                        }
                    )
        vus, out = set(), []
        for p in points:
            if _cle(p) not in vus:
                vus.add(_cle(p))
                out.append(p)
        return out

    return _memo(("reservoir",), _calcul)


def points_couche(map_id) -> list[dict]:
    """Quelques points garantis A L'INTERIEUR des zones d'une couche
    (point_on_surface, pas le centroide qui peut tomber dehors)."""
    if map_id is None:
        return []

    def _calcul():
        from envergo.geodata.models import Zone

        out = []
        zones = (
            Zone.objects.filter(map_id=map_id)
            .exclude(geometry__isnull=True)
            .order_by("pk")
        )
        for zone in zones[:8]:
            try:
                pt = zone.geometry.point_on_surface
            except Exception:
                continue
            # Une ZAR est incluse dans la zone vulnerable.
            out.append(
                {
                    "lat": f"{pt.y:.6f}",
                    "lng": f"{pt.x:.6f}",
                    "code_insee": "",
                    "_zv": True,
                }
            )
        return out

    return _memo(("couche", map_id), _calcul)


def _geos(point: dict):
    from django.contrib.gis.geos import Point

    return Point(float(point["lng"]), float(point["lat"]), srid=4326)


def _region(point: dict) -> str:
    if point.get("_region"):
        return point["_region"]

    def _calcul():
        from envergo.geodata.models import Department
        from envergo.nitrates.regions import region_for_department

        dept = (
            Department.objects.filter(geometry__intersects=_geos(point))
            .values_list("department", flat=True)
            .first()
        )
        return region_for_department(dept or "")[0] or ""

    return _memo(("region",) + _cle(point), _calcul)


def _zv(point: dict) -> bool:
    if "_zv" in point:
        return point["_zv"]

    def _calcul():
        from envergo.geodata.models import MAP_TYPES, Zone

        return Zone.objects.filter(
            map__map_type=MAP_TYPES.zv_nitrates,
            map__is_active=True,
            geometry__intersects=_geos(point),
        ).exists()

    return _memo(("zv",) + _cle(point), _calcul)


def _dans_couches(point: dict, map_ids) -> bool:
    """Le point est-il dans une des couches `map_ids` ? On ne teste que les
    zones de ces couches (quelques dizaines), pas toute la table : une requete
    sur toutes les couches coute plusieurs secondes par point."""
    map_ids = tuple(sorted(m for m in map_ids if m is not None))
    if not map_ids:
        return False

    def _calcul():
        from envergo.geodata.models import Zone

        return Zone.objects.filter(
            map_id__in=map_ids, geometry__intersects=_geos(point)
        ).exists()

    return _memo(("couches", map_ids) + _cle(point), _calcul)


def _ref(point: dict, reference: str):
    def _calcul():
        from envergo.nitrates.yaml_admin.catalogue_refs import (
            ResolveContext,
            get_resolver,
        )

        resolver = get_resolver(reference)
        if resolver is None:
            return _ABSENT
        try:
            return resolver.resolve(
                ResolveContext(
                    code_insee=point.get("code_insee") or None, lng_lat=_geos(point)
                )
            )
        except Exception:
            return _ABSENT

    return _memo(("ref", reference) + _cle(point), _calcul)


def _arbres_actifs() -> tuple[set, set]:
    """(regions avec un PAR actif, couches des ZAR actives)."""

    def _calcul():
        from envergo.nitrates.models import DecisionTree

        regions, couches = set(), set()
        for scope, region, map_id in DecisionTree.objects.filter(
            status=DecisionTree.STATUS_ACTIVE
        ).values_list("scope", "region_code", "activation_map_id"):
            if scope == DecisionTree.SCOPE_REGION and region:
                regions.add(region)
            if scope == DecisionTree.SCOPE_ZAR and map_id:
                couches.add(map_id)
        return regions, couches

    # Cache court : une activation doit se voir vite dans l'editeur.
    entree = _cache.get(("actifs",))
    if entree is not None and time.monotonic() - entree[0] < 30:
        return entree[1]
    valeur = _calcul()
    _cache[("actifs",)] = (time.monotonic(), valeur)
    return valeur


def _contraintes_ok(point: dict, contraintes) -> bool:
    from envergo.nitrates.yaml_tree.parcours import _valeurs_egales

    for reference, attendu in contraintes:
        if attendu is None or reference == "zone_vulnerable_nitrates":
            continue  # sans branche choisie : tout convient ; ZV testee a part
        obtenu = _ref(point, reference)
        if obtenu is _ABSENT:
            continue  # reference sans resolveur : pas verifiable
        if not _valeurs_egales(attendu, obtenu):
            return False
    return True


def _active(point: dict, zone: dict, strict: bool, actifs) -> bool:
    scope = zone.get("scope")
    regions_par, couches_zar = actifs
    if scope == "zar":
        return _dans_couches(point, [zone.get("activation_map_id")])
    region = _region(point)
    if scope == "region":
        if region != zone.get("region_code"):
            return False
        # Strict : hors des ZAR actives, sinon la ZAR capte la preview.
        return not (strict and _dans_couches(point, couches_zar))
    # PAN : strict = dans une region connue, sans PAR actif, hors ZAR actives.
    if strict:
        return (
            bool(region)
            and region not in regions_par
            and not _dans_couches(point, couches_zar)
        )
    return True


def point_verifie(zone: dict, contraintes, prefere: list[dict]) -> dict | None:
    """Premier point qui active l'arbre decrit par `zone` ({scope,
    region_code, activation_map_id}) et satisfait `contraintes`
    ([(reference_catalogue, valeur_branche)]). `prefere` : points essayes en
    premier (choix historique de preview.py). None si aucun ne convient."""
    couche = points_couche(zone.get("activation_map_id"))
    reservoir = _points_reservoir() if zone.get("scope") != "zar" else []
    # Les points preferes sont souvent des points du reservoir ou de la couche :
    # on leur reporte ce qu'on sait deja d'eux (region, statut ZV).
    connus = {_cle(c): c for c in reservoir + couche}
    candidats = [
        {**connus.get(_cle(c), {}), **c} for c in prefere if c and c.get("lat")
    ]
    candidats += couche + reservoir
    zv_attendue = True
    for reference, attendu in contraintes:
        if reference == "zone_vulnerable_nitrates" and attendu is not None:
            zv_attendue = attendu is True or str(attendu).lower() == "true"
    if not zv_attendue:
        # Hors zone vulnerable aucun arbre ne s'active : le point historique
        # (en mer) suffit, rien a verifier.
        return None
    actifs = _arbres_actifs()
    # Statut ZV connu d'abord (rapide). Puis, si rien ne convient, statut ZV
    # reellement interroge : l'etiquette stockee d'un point peut etre perimee
    # (nouveau zonage ZV 2026), mais la requete coute plusieurs secondes.
    reels = [{k: v for k, v in c.items() if k != "_zv"} for c in candidats]
    requetes_zv = [0]

    def _zv_ok(c) -> bool:
        if "_zv" in c:
            return c["_zv"] == zv_attendue
        # Requete PostGIS couteuse : plafonnee par lien.
        if requetes_zv[0] >= _MAX_REQUETES_ZV:
            return False
        requetes_zv[0] += 1
        return _zv(c) == zv_attendue

    for liste, strict in (
        (candidats, True),
        (candidats, False),
        (reels, True),
        (reels, False),
    ):
        vus = set()
        for c in liste:
            if _cle(c) in vus:
                continue
            vus.add(_cle(c))
            try:
                # Du moins couteux au plus couteux : region/activation, codes
                # INSEE (fichiers), puis ZV (PostGIS sur une grosse couche).
                if (
                    _active(c, zone, strict, actifs)
                    and _contraintes_ok(c, contraintes)
                    and _zv_ok(c)
                ):
                    return {k: v for k, v in c.items() if not k.startswith("_")}
            except Exception:
                continue
    return None
