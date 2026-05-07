import json

from django.contrib.gis.geos import Point
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.generic import TemplateView, View

from envergo.geodata.models import MAP_TYPES, Department, Zone
from envergo.nitrates.bassins import (
    bassin_code_from_attributes,
    bassin_label_from_attributes,
)
from envergo.nitrates.models import DecisionTree, MoulinetteNitrates
from envergo.nitrates.regions import region_for_department
from envergo.nitrates.yaml_tree import load_active_tree, load_referentiels

# Mapping pour le recap des QC repondues (rendu dans le panneau gauche apres
# que l'utilisateur a repondu via le mini-form du panneau droit). Donne le
# texte de la question et le libelle humain de chaque valeur.
# Si on ajoute de nouveaux champs subsidiaires dans l'arbre, les ajouter ici.
_QC_LIBELLES = {
    "plan_epandage": {
        "texte": "Plan d'épandage",
        "choix": {
            "icpe_a": "À autorisation (ICPE A)",
            "icpe_e": "À enregistrement (ICPE E)",
            "icpe_d": "À déclaration (ICPE D)",
            "non_concerne": "Non concerné",
        },
    },
    "effluents_peu_charges": {
        "texte": "Effluents peu chargés",
        "choix": {
            "oui": "Oui",
            "non": "Non",
        },
    },
}


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
                features.append(
                    {
                        "type": "Feature",
                        "geometry": json.loads(geom_json),
                        "properties": {
                            "nom": bassin_label_from_attributes(attrs),
                            "bassin": bassin_code_from_attributes(attrs),
                        },
                    }
                )
        return JsonResponse({"type": "FeatureCollection", "features": features})


class DebugView(View):
    """Renvoie les infos géographiques pour un point (lng, lat) cliqué.

    Endpoint de démo end-to-end : département, région, appartenance
    à une zone vulnérable nitrates.

    Le RPG (Registre Parcellaire Graphique) a été retiré de cet
    endpoint en 0.0.3 (retour juriste 0.0.1 : la donnée correcte pour
    la zone d'activation est le cadastre, pas le RPG). L'import et la
    table sont conservés pour réactivation V1+ : résoudre la culture
    déclarée par l'agriculteur à partir de la parcelle RPG.
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
                "nom": bassin_label_from_attributes(attrs),
                "bassin": bassin_code_from_attributes(attrs),
            }

        return JsonResponse(
            {
                "lng": lng,
                "lat": lat,
                "department_code": department_code,
                "region_code": region_code,
                "region_label": region_label,
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
            "categorie_culture",
            "sous_culture_form",
            "occupation_sol",
            "sous_culture",
            "categorie_fertilisant",
            "sous_fertilisant",
            "type_fertilisant",
            "culture_irriguee_type",
            "prairie_permanente",
            "sous_culture_couvert",
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
            "qc_repondues_champs": [],
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

        # Recap des QC deja repondues : champs subsidiaires connus presents
        # dans request.GET ET qui ne sont plus en cours de saisie (sinon le
        # walker les redemanderait). Le libelle est resolu via _QC_LIBELLES.
        qc_repondues = []
        for champ, meta in _QC_LIBELLES.items():
            if champ in qc_actifs:
                continue
            valeur = request.GET.get(champ)
            if not valeur:
                continue
            qc_repondues.append(
                {
                    "champ": champ,
                    "valeur": valeur,
                    "texte": meta["texte"],
                    "libelle": meta["choix"].get(valeur, valeur),
                }
            )

        ctx.update(
            {
                "afficher_resultat": True,
                "moulinette": moulinette,
                "regulations_evaluees": regulations_evaluees,
                "premier_evaluator_avec_questions": premier_qc,
                "qc_actifs": qc_actifs,
                "qc_repondues": qc_repondues,
                "qc_repondues_champs": [e["champ"] for e in qc_repondues],
            }
        )
        return render(request, "nitrates/simulateur.html", ctx)
