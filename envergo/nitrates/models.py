"""Modeles de l'app nitrates.

Contient :
  - `RpgCulture` : table de reference des codes culture du RPG
  - `MoulinetteNitrates` : moulinette nitrates (heritage du pattern
    Envergo `Moulinette`, definie ici plutot que dans
    envergo/moulinette/models.py qui est deja sature)
"""

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.db import models
from django.db.models import F, IntegerField
from django.db.models.functions import Cast

from envergo.geodata.models import MAP_TYPES, Department, Zone
from envergo.moulinette.models import Moulinette
from envergo.nitrates.bassins import bassin_name
from envergo.nitrates.forms import MoulinetteFormNitrates
from envergo.nitrates.regions import region_for_department

EPSG_WGS84 = 4326


class RpgCulture(models.Model):
    """Code culture du Registre Parcellaire Graphique (PAC).

    Reference officielle IGN/ASP, dispo en CSV sur data.gouv. 144 codes en 2024.
    Le RPG stocke un code a 3 lettres par parcelle (ex BTH = ble tendre), on
    se sert de cette table pour mapper vers un libelle lisible et un groupe
    de culture (ex BTH -> "ble tendre" / groupe "Cereales a paille").

    Le groupe sera particulierement utile pour le YAML PAN qui parle de
    categories ("cereales", "olegineux") plutot que de trigrammes.
    """

    code = models.CharField(max_length=3, primary_key=True)
    libelle = models.CharField(max_length=255)
    code_groupe = models.CharField(max_length=10, blank=True)
    libelle_groupe = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "Code culture RPG"
        verbose_name_plural = "Codes culture RPG"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.libelle}"


class MoulinetteNitrates(Moulinette):
    """Moulinette nitrates : pilote la reglementation epandage azote
    via l'arbre de decision YAML.

    Herite directement de `Moulinette`.
    On reprend le pattern Regulation/Criterion/Evaluator
    pour rester forward-compatible.

    MVP : pas de ConfigNitrates -- on accepte tous les points sans filtrage
    geographique.
      Le jour ou on a besoin d'une configuration (PAR par region, overrides
      par bassin versant, ZAR, templates editoriaux par DDT...), on se posera
      d'abord la question de la cle d'agregation. Dans Envergo classique
      c'est le departement, mais pour nitrates ce sera peut-etre la region
      ou autre chose selon l'evolution du produit. On fera peut-etre un
      override de la classe abstraite ConfigBase a ce moment-la.

    Activation : le critere `arbre_decision` a la map ZV nitrates comme
    activation_map, donc la moulinette ne tourne (= ne retourne le critere
    et n'evalue l'arbre) que pour des points dans une zone vulnerable.
    Hors ZV, aucun critere n'est retourne. La logique "hors ZV ->
    non applicable" reste documentee dans le YAML pour la lisibilite des
    juristes mais n'est jamais empruntee en pratique.
    """

    REGULATIONS = ["directive_nitrates"]

    home_template = "nitrates/home.html"
    result_template = "nitrates/result.html"
    debug_result_template = "nitrates/result_debug.html"
    result_available_soon = "nitrates/result_available_soon.html"
    result_non_disponible = "nitrates/result_non_disponible.html"
    form_template = "nitrates/form.html"
    main_form_class = MoulinetteFormNitrates
    triage_form_class = None

    # ─── Catalog ───────────────────────────────────────────────────────────

    def get_catalog_data(self):
        """Construit le catalog pour ce point.

        Reprend la logique de la `DebugView` deja existante : le point
        Wgs84, le departement, la region, le statut ZV (pour l'injecter
        ensuite dans le contexte du parcours d'arbre)."""
        catalog = super().get_catalog_data()

        if "lng" in catalog and "lat" in catalog:
            point = Point(float(catalog["lng"]), float(catalog["lat"]), srid=EPSG_WGS84)
            catalog["lng_lat"] = point

            department = (
                Department.objects.filter(geometry__intersects=point)
                .only("department")
                .first()
            )
            catalog["department_code"] = department.department if department else None
            region_code, region_label = region_for_department(
                catalog["department_code"] or ""
            )
            catalog["region_code"] = region_code
            catalog["region_label"] = region_label

            zv_zone = (
                Zone.objects.filter(
                    map__map_type=MAP_TYPES.zv_nitrates,
                    geometry__intersects=point,
                )
                .only("attributes")
                .first()
            )
            catalog["en_zone_vulnerable"] = zv_zone is not None
            if zv_zone:
                attrs = zv_zone.attributes or {}
                bassin = attrs.get("CdEuBassin")
                catalog["bassin"] = bassin
                catalog["bassin_label"] = bassin_name(bassin, attrs.get("NomZoneVul"))
            else:
                catalog["bassin"] = None
                catalog["bassin_label"] = None

        return catalog

    def get_criteria(self):
        """Filtre les criteres par intersection avec leur activation_map.

        Le critere `arbre_decision` a la map ZV comme activation_map :
        si le point n'intersecte aucune ZV, le critere n'est pas retourne
        et l'arbre ne tourne pas."""
        coords = self.catalog.get("lng_lat")
        criteria = super().get_criteria()
        if coords is None:
            return criteria.none()
        return (
            criteria.filter(activation_map__zones__geometry__intersects=coords)
            .annotate(
                distance=Cast(
                    Distance("activation_map__zones__geometry", coords),
                    IntegerField(),
                )
            )
            .filter(distance__lte=F("activation_distance"))
            .select_related("activation_map")
        )

    # ─── Implementations des abstracts ─────────────────────────────────────

    def get_department(self):
        if "lng_lat" not in self.catalog:
            return None
        return Department.objects.filter(
            geometry__contains=self.catalog["lng_lat"]
        ).first()

    def get_config(self):
        # Pas de ConfigNitrates au MVP. Cf. docstring de la classe.
        return None

    def is_evaluation_available(self):
        # Pas de config a verifier : on est dispo des qu'on a un point valide
        # et que le formulaire principal est valide.
        return self.is_valid() and "lng_lat" in self.catalog

    def is_valid(self):
        return self.bound_main_form.is_valid()

    @property
    def moulinette_data(self):
        return self.catalog

    def get_triage_params(self):
        return []

    # ─── Summary / debug ───────────────────────────────────────────────────

    def summary(self):
        """Donnees pour analytics."""
        return {
            "lat": f"{self.catalog['lat']:.5f}" if "lat" in self.catalog else None,
            "lng": f"{self.catalog['lng']:.5f}" if "lng" in self.catalog else None,
            "department_code": self.catalog.get("department_code"),
            "region_code": self.catalog.get("region_code"),
            "en_zone_vulnerable": self.catalog.get("en_zone_vulnerable"),
            "is_eval_available": self.is_evaluation_available(),
        }

    def get_debug_context(self):
        return {
            "department_code": self.catalog.get("department_code"),
            "region_code": self.catalog.get("region_code"),
            "region_label": self.catalog.get("region_label"),
            "en_zone_vulnerable": self.catalog.get("en_zone_vulnerable"),
            "bassin": self.catalog.get("bassin"),
            "bassin_label": self.catalog.get("bassin_label"),
        }
