import json

from django.conf import settings
from django.contrib.gis.geos import Point
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.generic import View

from envergo.geodata.models import MAP_TYPES, Department, Zone
from envergo.nitrates.bassins import (
    bassin_code_from_attributes,
    bassin_label_from_attributes,
)
from envergo.nitrates.models import DecisionTree, MoulinetteNitrates
from envergo.nitrates.models_ouverture import departement_est_ouvert
from envergo.nitrates.regions import region_for_department
from envergo.nitrates.yaml_tree import load_active_tree, load_referentiels
from envergo.nitrates.zonage_zones_est import est_zone_grand_est_1, est_zone_grand_est_2


def _cache_in_prod(seconds):
    """Decorateur cache_page activé uniquement quand DEBUG=False (prod).
    En dev (DEBUG=True), no-op : pas de cache, refresh instantané quand
    on modifie un referentiel cote ORM ou un YAML.
    """
    if settings.DEBUG:

        def _noop(view):
            return view

        return _noop
    return cache_page(seconds)


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


class HomeView(View):
    """Racine `/` : sert le meme simulateur que `/simulateur/`, mais en
    mode "alpha-testeur public" -> sans les panneaux debug et avec le
    bandeau "site en construction".

    Acces : ouvert sans connexion quand NITRATES_ROOT_OUVERT=True (le
    middleware RequireLoginEverywhere exempte alors `/`). Sinon, reste
    derriere le lockdown ProConnect comme le reste du site.

    On delegue tout a `MoulinetteView.get()` (via des flags surchargeables)
    pour eviter toute duplication de logique avec `/simulateur/`.
    """

    def get(self, request, *args, **kwargs):
        # Import retarde pour eviter d'instancier MoulinetteView avant que
        # ses dependances (referentiels DB, etc.) soient chargees.
        view = MoulinetteView()
        view.force_debug = False  # jamais de panneaux debug sur le root public
        view.is_building = True  # bandeau "site en construction"
        return view.get(request, *args, **kwargs)


@method_decorator(_cache_in_prod(60 * 60 * 24), name="dispatch")
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


@method_decorator(_cache_in_prod(60 * 60 * 24), name="dispatch")
class ZoneActionRenforceeGeoJSONView(View):
    """Renvoie les polygones ZAR (Zone d'Action Renforcée) en GeoJSON.

    Couvre TOUTES les Map de type zone_action_renforcee (potentiellement
    plusieurs régions ; pour l'instant le Grand Est seul). Affiché comme
    overlay optionnel sur la carte du simulateur (tickbox), cf. carte #34.

    Les ZAR sont des petites zones (aires d'alimentation de captage), donc
    une tolérance de simplification faible suffit. Cache 24h (mêmes raisons
    que la ZV : données quasi-statiques).

    Format : FeatureCollection WGS84.
    """

    # ~0.0005° ≈ 50m : les ZAR sont petites, on garde plus de détail que la ZV.
    SIMPLIFY_TOLERANCE = 0.0005

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
                [self.SIMPLIFY_TOLERANCE, MAP_TYPES.zone_action_renforcee],
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
                            "nom": attrs.get("NOMZAR"),
                            "nom_complet": attrs.get("NOMCOMPL"),
                            "type": attrs.get("TYPABRG"),
                            "departement": attrs.get("CDDEPT"),
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

        en_zar = Zone.objects.filter(
            map__map_type=MAP_TYPES.zone_action_renforcee,
            geometry__intersects=point,
        ).exists()

        # Zones Est (resolues par code INSEE) : on les expose pour le panneau
        # debug gauche. code_insee n'est pas connu de cet endpoint (pas de
        # geocodage commune ici), on passe le code recu du front s'il existe.
        code_insee = request.GET.get("code_insee") or ""
        en_grand_est = region_code == "44"

        return JsonResponse(
            {
                "lng": lng,
                "lat": lat,
                "department_code": department_code,
                "region_code": region_code,
                "region_label": region_label,
                "en_zone_vulnerable": zv_zone is not None,
                "zv_info": zv_info,
                "en_zar": en_zar,
                "en_grand_est": en_grand_est,
                # ZGE1/ZGE2 : pertinents seulement en Grand Est (sinon None ->
                # le front ne les affiche pas).
                "zone_grand_est_1": (
                    est_zone_grand_est_1(code_insee) if en_grand_est else None
                ),
                "zone_grand_est_2": (
                    est_zone_grand_est_2(code_insee) if en_grand_est else None
                ),
                # Bornage géographique (carte #57) : le simulateur n'est ouvert
                # que dans certaines régions/départements. Si fermé, le front
                # affiche un message au lieu du formulaire. Allowlist : fermé
                # par défaut.
                "simulateur_ouvert": departement_est_ouvert(department_code),
            }
        )


@method_decorator(_cache_in_prod(60 * 60), name="dispatch")
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


@method_decorator(_cache_in_prod(60 * 60), name="dispatch")
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

    Deux flags surchargeables par les sous-vues (cf. HomeView) controlent
    le rendu sans dupliquer la logique :
      - `force_debug` : None -> suit NITRATES_FORM_DEBUG_PANELS (defaut
        simulateur). True/False -> force l'affichage des panneaux debug.
      - `is_building` : affiche le bandeau "site en construction" (mode
        alpha-testeur sur le root public).
    """

    # None = comportement par defaut (settings). Une sous-vue peut forcer.
    force_debug = None
    is_building = False

    def get(self, request, *args, **kwargs):
        from django.conf import settings

        # Charge les referentiels une fois (utilises pour resoudre les
        # libelles longs cote template).
        try:
            referentiels = load_referentiels()
        except FileNotFoundError:
            referentiels = {}

        # Mode preview admin : si ?draft_tree_id=<pk> est fourni ET que
        # l'utilisateur a le droit de voir ce draft, l'evaluateur charge
        # ce tree au lieu de l'actif. Sinon on strip le param (fallback
        # silencieux sur l'actif, pas d'erreur) pour eviter qu'un visiteur
        # non-staff puisse voir un brouillon non publie via une URL devinee.
        self._guard_draft_tree_id(request)

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
        ]

        ctx = {
            "data": request.GET,
            "codes_prescription": referentiels.get("codes_prescription", {}),
            "notes_referentiel": referentiels.get("notes", {}),
            "afficher_resultat": False,
            # Active les panels debug (info parcelle, chemin parcouru,
            # result_code, etc.). Pilote par NITRATES_FORM_DEBUG_PANELS pour
            # pouvoir activer en staging sans avoir DEBUG=True. Une sous-vue
            # (HomeView, root public) peut forcer a False via force_debug.
            "debug": (
                settings.NITRATES_FORM_DEBUG_PANELS
                if self.force_debug is None
                else self.force_debug
            ),
            # Bandeau "site en construction" (mode alpha-testeur, root public).
            "is_building": self.is_building,
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

        # Recap des QC sur le chemin actuel : repondues + en attente
        # (les "en attente" sont aussi rendues a gauche en radio buttons
        # editables pour que l'utilisateur change la cascade sans repartir
        # de zero). Les choix sont issus DIRECTEMENT de l'arbre YAML
        # (pas d'une table hardcodee), donc seules les valeurs reellement
        # presentes dans la branche en cours sont proposees.
        from envergo.nitrates.yaml_tree import (
            collecter_qc_du_chemin,
            load_active_tree,
            load_tree_by_id,
        )

        # On collecte les QC sur l'arbre REELLEMENT evalue par la cascade
        # (peut etre un PAR/ZAR, pas le PAN). Sinon le panel gauche ne
        # retrouverait pas les QC du ZAR (le PAN ne les a pas).
        arbre_actif = None
        for e in regulations_evaluees:
            ac = getattr(e["evaluator"], "arbre_courant", None)
            if ac:
                arbre_actif = ac
                break
        if arbre_actif is None:
            # Fallback (pas d'eval arbre, ex preview draft ou hors ZV).
            draft_id = request.GET.get("draft_tree_id")
            if draft_id:
                try:
                    arbre_actif = load_tree_by_id(int(draft_id))
                except (DecisionTree.DoesNotExist, ValueError, TypeError):
                    arbre_actif = load_active_tree()
            else:
                arbre_actif = load_active_tree()
        contexte_courant = dict(request.GET.items())
        # Le contexte URL ne contient pas les champs catalogue (en_zone_vulnerable,
        # zone_note_5, etc.) qui sont resolus par la moulinette. Pour permettre
        # a collecter_qc_du_chemin de descendre l'arbre, on force
        # en_zone_vulnerable=True (par definition si on a une QC sur le chemin,
        # on est dans la branche ZV) et on remonte les autres champs catalogue
        # depuis la moulinette si dispo.
        contexte_courant.setdefault("en_zone_vulnerable", True)
        try:
            cat = getattr(moulinette, "catalog", None) or {}
            for k in (
                "zone_note_5",
                "zone_montagne_d113_14",
                "zonage_montagne_regional",
                "zonage_prairie_III",
            ):
                if k in cat and k not in contexte_courant:
                    contexte_courant[k] = cat[k]
        except Exception:
            pass
        qc_repondues = []
        for q in collecter_qc_du_chemin(arbre_actif, contexte_courant):
            if q.champ in qc_actifs:
                # Deja en cours de saisie dans le panneau resultat (a droite),
                # on ne le redouble pas a gauche.
                continue
            raw = request.GET.get(q.champ) or ""
            # Stringify les valeurs des choix pour comparer avec ce qui
            # arrive par URL (toujours str). Sinon bool True != "True"
            # et le radio button n'est jamais coche.
            choix = [
                {
                    "valeur": str(c["valeur"]),
                    "libelle": c.get("libelle") or str(c["valeur"]),
                }
                for c in (q.choix or [])
            ]
            valeur = raw
            libelle = next(
                (c["libelle"] for c in choix if c["valeur"] == valeur),
                valeur,
            )
            qc_repondues.append(
                {
                    "champ": q.champ,
                    "valeur": valeur,
                    "texte": q.texte or q.champ,
                    "libelle": libelle,
                    "choix": choix,
                }
            )

        ctx.update(
            {
                "afficher_resultat": True,
                # Tant qu'une QC est en attente, on n'affiche PAS le panel
                # resultat : on reste en colonne unique et on pose les QC sous
                # le formulaire (cf. simulateur.html / _panneau_form.html). Le
                # resultat n'apparait a droite qu'une fois toutes les QC
                # repondues (premier_qc == None). (#112)
                "qc_en_attente": premier_qc is not None,
                "moulinette": moulinette,
                "regulations_evaluees": regulations_evaluees,
                "premier_evaluator_avec_questions": premier_qc,
                "qc_actifs": qc_actifs,
                "qc_repondues": qc_repondues,
                "qc_repondues_champs": [e["champ"] for e in qc_repondues],
            }
        )
        return render(request, "nitrates/simulateur.html", ctx)

    def _guard_draft_tree_id(self, request) -> None:
        """Si `?draft_tree_id=<pk>` est present mais que l'utilisateur n'a
        pas la permission de previsualiser ce tree, on retire le param
        en mutant `request.GET` (devient mutable temporairement).

        Strategie fail-safe : pas d'erreur 403 / 404 -- on tombe
        silencieusement sur l'arbre actif. Empeche un visiteur non-staff
        de voir un brouillon non publie via une URL devinee, tout en
        gardant le simulateur fonctionnel.
        """
        draft_id = request.GET.get("draft_tree_id")
        if not draft_id:
            return
        from envergo.nitrates.permissions import can_preview_tree

        try:
            tree = DecisionTree.objects.get(pk=int(draft_id))
        except (DecisionTree.DoesNotExist, ValueError, TypeError):
            tree = None
        allowed = tree is not None and can_preview_tree(request.user, tree)
        if not allowed:
            mutable = request.GET._mutable
            request.GET._mutable = True
            request.GET.pop("draft_tree_id", None)
            request.GET._mutable = mutable
