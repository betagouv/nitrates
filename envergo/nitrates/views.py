import json

from django.contrib.gis.geos import Point
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.generic import TemplateView, View

from envergo.geodata.models import MAP_TYPES, Department, Zone
from envergo.nitrates.bassins import bassin_name
from envergo.nitrates.models import RpgCulture
from envergo.nitrates.regions import region_for_department


class HomeView(TemplateView):
    template_name = "nitrates/home.html"


@method_decorator(cache_page(60 * 60 * 24), name="dispatch")
class ZoneVulnerableGeoJSONView(View):
    """Renvoie les polygones ZV nitrates au format GeoJSON.

    Geometrie simplifiees via ST_SimplifyPreserveTopology pour rester
    raisonnable a charger cote client (sinon ~90 MB pour 8 polygones nationaux
    avec leur précision originale au mètre).

    Mis en cache 24h : les ZV ne changent qu'au rythme des arretes
    prefectoraux (pas plus d'une fois par an en pratique). La simplification
    PostGIS sur les polygones de 100k km2 coûte ~7s sans cache.

    Format : FeatureCollection WGS84.
    """

    # ~0.005° ≈ 500m à la latitude de la France métropolitaine.
    # Largement suffisant pour un overlay régional/national.
    SIMPLIFY_TOLERANCE = 0.005

    def get(self, request, *args, **kwargs):
        from django.db import connection

        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    ST_AsGeoJSON(
                        ST_SimplifyPreserveTopology(
                            z.geometry::geometry, %s
                        )
                    ),
                    z.attributes
                FROM geodata_zone z
                JOIN geodata_map m ON z.map_id = m.id
                WHERE m.map_type = %s
                """,
                [self.SIMPLIFY_TOLERANCE, MAP_TYPES.zv_nitrates],
            )
            features = []
            for geom_json, attributes in cur.fetchall():
                attrs = attributes or {}
                if isinstance(attrs, str):
                    attrs = json.loads(attrs)
                bassin = attrs.get("CdEuBassin")
                features.append(
                    {
                        "type": "Feature",
                        "geometry": json.loads(geom_json),
                        "properties": {
                            "nom": bassin_name(bassin, attrs.get("NomZoneVul")),
                            "bassin": bassin,
                        },
                    }
                )
        return JsonResponse({"type": "FeatureCollection", "features": features})


class DebugView(View):
    """Renvoie les infos géographiques pour un point (lng, lat) cliqué.

    Endpoint de démo end-to-end : département, région, parcelle RPG si
    présente, appartenance à une zone vulnérable nitrates.
    """

    def get(self, request, *args, **kwargs):
        try:
            lng = float(request.GET["lng"])
            lat = float(request.GET["lat"])
        except (KeyError, ValueError):
            return JsonResponse(
                {"error": "Paramètres lng et lat requis (floats)"}, status=400
            )

        point = Point(lng, lat, srid=4326)

        department = (
            Department.objects.filter(geometry__intersects=point)
            .only("department")
            .first()
        )
        department_code = department.department if department else None
        region_code, region_label = region_for_department(department_code or "")

        rpg_zone = (
            Zone.objects.filter(
                map__map_type=MAP_TYPES.rpg_parcelle,
                geometry__intersects=point,
            )
            .only("attributes")
            .first()
        )
        rpg_parcelle = None
        if rpg_zone:
            attrs = rpg_zone.attributes or {}
            code_cultu = attrs.get("CODE_CULTU")
            # Lookup du libelle depuis la table de reference si on l'a chargee
            libelle = ""
            groupe = ""
            if code_cultu:
                culture = RpgCulture.objects.filter(pk=code_cultu).first()
                if culture:
                    libelle = culture.libelle
                    groupe = culture.libelle_groupe
            rpg_parcelle = {
                "id_parcel": attrs.get("ID_PARCEL"),
                "code_cultu": code_cultu,
                "libelle_cultu": libelle,
                "groupe_cultu": groupe,
                "surf_parc": attrs.get("SURF_PARC"),
            }

        zv_zone = (
            Zone.objects.filter(
                map__map_type=MAP_TYPES.zv_nitrates,
                geometry__intersects=point,
            )
            .only("attributes")
            .first()
        )
        zv_info = None
        if zv_zone:
            attrs = zv_zone.attributes or {}
            bassin = attrs.get("CdEuBassin")
            zv_info = {
                "nom": bassin_name(bassin, attrs.get("NomZoneVul")),
                "bassin": bassin,
            }

        return JsonResponse(
            {
                "lng": lng,
                "lat": lat,
                "department_code": department_code,
                "region_code": region_code,
                "region_label": region_label,
                "rpg_parcelle": rpg_parcelle,
                "en_zone_vulnerable": zv_zone is not None,
                "zv_info": zv_info,
            }
        )
