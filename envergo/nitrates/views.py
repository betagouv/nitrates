from django.contrib.gis.geos import Point
from django.http import JsonResponse
from django.views.generic import TemplateView, View

from envergo.geodata.models import MAP_TYPES, Department, Zone
from envergo.nitrates.regions import region_for_department


class HomeView(TemplateView):
    template_name = "nitrates/home.html"


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
            rpg_parcelle = {
                "id_parcel": attrs.get("ID_PARCEL"),
                "code_cultu": attrs.get("CODE_CULTU"),
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
            zv_info = {
                "nom": attrs.get("NomZoneVul"),
                "bassin": attrs.get("CdEuBassin"),
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
