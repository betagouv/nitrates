import json

from django.contrib.gis.geos import Point
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.generic import TemplateView, View

from envergo.geodata.models import MAP_TYPES, Department, Zone
from envergo.nitrates.bassins import bassin_name
from envergo.nitrates.models import DecisionTree, MoulinetteNitrates, RpgCulture
from envergo.nitrates.regions import region_for_department
from envergo.nitrates.yaml_tree import load_active_tree, load_referentiels


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


@method_decorator(cache_page(60 * 60), name="dispatch")
class ReferentielsView(View):
    """Expose les listes fermees du YAML referentiels (types fertilisants,
    cultures, codes prescription, notes...) en JSON pour le front.

    Permet a la cascade JS d'afficher les bons libelles (libelle_public)
    et de filtrer les options en fonction des choix precedents
    (mapping_sous_fertilisant_vers_type).

    Cache 1h : ce fichier ne change qu'au rythme de la reglementation.
    """

    def get(self, request, *args, **kwargs):
        return JsonResponse(load_referentiels())


@method_decorator(cache_page(60 * 60), name="dispatch")
class DecisionTreeView(View):
    """Expose l'arbre de decision actif en JSON pour que le front puisse
    construire les selects en cascade (occupation_sol, sous_culture,
    type_fertilisant) en suivant la structure exacte de l'arbre.

    Source de verite : la table DecisionTree. Si aucun tree actif, on
    retourne 503 plutot que 500 (cause = data manquante en base).
    """

    def get(self, request, *args, **kwargs):
        try:
            return JsonResponse(load_active_tree())
        except DecisionTree.DoesNotExist:
            return JsonResponse(
                {
                    "error": (
                        "Aucun arbre de decision actif en base. "
                        "Importer via `manage.py import_decision_tree`."
                    )
                },
                status=503,
            )


class MoulinetteView(View):
    """Simulateur nitrates : instancie la moulinette avec les query params
    et rend un template debug brut (resultat ou questions subsidiaires).

    Tout passe en GET pour faciliter le debug et le partage d'URL. Plus
    tard on pourra convertir en POST + redirect si besoin.

    Sans lat/lng : on rend le formulaire vide.
    Avec lat/lng + (optionnel) reponses cascade : on rend le resultat.
    """

    def get(self, request, *args, **kwargs):
        from django.conf import settings

        # Charge les referentiels une fois (utilises pour resoudre les
        # libelles longs cote template).
        try:
            referentiels = load_referentiels()
        except FileNotFoundError:
            referentiels = {}

        # Champs deja rendus dans le form principal (cascade + lat/lng +
        # code_insee + hidden type_fertilisant). On les exclut du
        # passthrough. Liste (et pas set) car Django templates rendent
        # mal les sets.
        cascade_fields = [
            "lat",
            "lng",
            "code_insee",
            "occupation_sol",
            "sous_culture",
            "categorie_fertilisant",
            "sous_fertilisant",
            "type_fertilisant",
        ]

        ctx = {
            "data": request.GET,
            "codes_prescription": referentiels.get("codes_prescription", {}),
            "notes_referentiel": referentiels.get("notes", {}),
            "afficher_resultat": False,
            # Active les panels debug (info parcelle, chemin parcouru,
            # result_code, etc.) uniquement en mode developpeur.
            "debug": settings.DEBUG,
            "cascade_fields": cascade_fields,
            "qc_actifs": [],
        }

        # Sans lat/lng -> on rend juste le panneau form (pas de resultat).
        if "lng" not in request.GET or "lat" not in request.GET:
            return render(request, "nitrates/simulateur.html", ctx)

        # Avec lat/lng -> moulinette + resultat dans la 2e colonne.
        moulinette = MoulinetteNitrates(form_kwargs={"data": request.GET.dict()})
        # Le template ne peut pas acceder a `criterion._evaluator` (Django
        # interdit les attributs commencant par underscore). On expose
        # explicitement les evaluators evalues sous forme de liste
        # d'objets {regulation, criterion, evaluator}.
        regulations_evaluees = []
        for regulation in moulinette.regulations:
            for criterion in regulation.criteria.all():
                regulations_evaluees.append(
                    {
                        "regulation": regulation,
                        "criterion": criterion,
                        "evaluator": getattr(criterion, "_evaluator", None),
                    }
                )

        # Premier evaluator porteur de questions complementaires
        # (le QC est rendu sous le form principal, colonne gauche, pas
        # dans le panel resultat).
        premier_qc = next(
            (
                e["evaluator"]
                for e in regulations_evaluees
                if getattr(e["evaluator"], "questions_subsidiaires", None)
            ),
            None,
        )
        # Noms des QC en cours de saisie : exclus du passthrough hidden
        # pour eviter d'envoyer 2 fois la meme cle a la prochaine
        # soumission.
        qc_actifs = []
        if premier_qc and getattr(premier_qc, "questions_subsidiaires", None):
            qc_actifs = list(premier_qc.questions_subsidiaires.champs_set)

        ctx.update(
            {
                "afficher_resultat": True,
                "moulinette": moulinette,
                "regulations_evaluees": regulations_evaluees,
                "premier_evaluator_avec_questions": premier_qc,
                "qc_actifs": qc_actifs,
            }
        )
        return render(request, "nitrates/simulateur.html", ctx)
