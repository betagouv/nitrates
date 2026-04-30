"""Modeles de l'app nitrates.

Contient :
  - `RpgCulture` : table de reference des codes culture du RPG
  - `DecisionTree` : versions de l'arbre de decision (draft/active/archive),
    source de verite runtime depuis la migration de l'arbre YAML vers la DB
  - `MoulinetteNitrates` : moulinette nitrates (heritage du pattern
    Envergo `Moulinette`, definie ici plutot que dans
    envergo/moulinette/models.py qui est deja sature)
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.db import models, transaction
from django.db.models import F, IntegerField, Q
from django.db.models.functions import Cast
from django.utils import timezone

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


class DecisionTree(models.Model):
    """Une version de l'arbre de decision nitrates.

    Source de verite runtime : la moulinette et les vues lisent l'arbre
    depuis cette table, plus depuis le fichier YAML monte en volume.

    Lifecycle :
      - draft : version en preparation, peut coexister avec d'autres drafts
      - active : version actuellement servie. UNE seule a la fois (contrainte
        unique partielle).
      - archive : ancienne version active. On garde toutes les archives.

    Le YAML (champ `contenu_yaml_brut`) est conserve via ruamel round-trip
    pour pouvoir re-exporter avec commentaires + ordre + ancres preserves.
    Le parse pyyaml (champ `contenu`) est ce qui est consomme en runtime.
    """

    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_ARCHIVE = "archive"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Brouillon"),
        (STATUS_ACTIVE, "Actif"),
        (STATUS_ARCHIVE, "Archive"),
    ]

    name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT
    )

    # Arbre deserialise -- manipulable comme dict. Source de verite runtime.
    contenu = models.JSONField()

    # YAML round-trip ruamel : preserve commentaires + ordre + ancres.
    # Sert a l'export et au viewer admin.
    contenu_yaml_brut = models.TextField(blank=True)

    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    activated_at = models.DateTimeField(null=True, blank=True)

    # Lock simple : un seul editeur a la fois sur un draft donne. Le lock
    # expire automatiquement apres LOCK_TIMEOUT (cf methodes utilitaires).
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    locked_at = models.DateTimeField(null=True, blank=True)

    LOCK_TIMEOUT = timedelta(minutes=15)

    class Meta:
        constraints = [
            # Une seule version active a la fois.
            models.UniqueConstraint(
                fields=["status"],
                condition=Q(status="active"),
                name="nitrates_decisiontree_unique_active",
            ),
        ]
        indexes = [
            models.Index(fields=["status"]),
        ]
        ordering = ["-activated_at", "-created_at"]

    def __str__(self):
        return f"{self.name} ({self.status})"

    @transaction.atomic
    def activate(self):
        """Active ce DecisionTree. L'actif courant passe en archive.

        Idempotent : re-activer un tree deja actif ne casse rien.

        TODO MVP : un seul tree actif global. Quand on ajoutera les
        overrides regionaux (PAR), la notion d'actif devra etre adossee
        a un scope (national / region / departement / bassin). Modele
        cible : champ `scope` (national | region | dept | bassin) +
        champ optionnel `scope_value` (code region/dept/bassin), avec
        contrainte unique partielle sur (status='active', scope, scope_value).
        Cette methode `activate()` devra alors n'archiver que les actifs
        du meme scope.
        """
        DecisionTree.objects.filter(status=self.STATUS_ACTIVE).exclude(
            pk=self.pk
        ).update(status=self.STATUS_ARCHIVE)
        self.status = self.STATUS_ACTIVE
        self.activated_at = timezone.now()
        self.save(update_fields=["status", "activated_at", "updated_at"])

    # ─── Lock d'edition ────────────────────────────────────────────────────

    def is_locked_by_other(self, user) -> bool:
        """True si quelqu'un d'autre detient un lock encore valide."""
        if self.locked_by_id is None or self.locked_at is None:
            return False
        if self.locked_by_id == user.pk:
            return False
        return self.locked_at >= timezone.now() - self.LOCK_TIMEOUT

    @transaction.atomic
    def acquire_lock(self, user) -> bool:
        """Tente de prendre le lock pour user. Retourne True si OK,
        False si quelqu'un d'autre detient un lock encore valide.

        Idempotent : si user detient deja le lock, on rafraichit
        simplement locked_at.
        """
        # Re-check avec lock pessimiste pour eviter la race entre 2 admins
        # qui cliquent en meme temps.
        fresh = DecisionTree.objects.select_for_update().get(pk=self.pk)
        if fresh.is_locked_by_other(user):
            return False
        fresh.locked_by = user
        fresh.locked_at = timezone.now()
        fresh.save(update_fields=["locked_by", "locked_at", "updated_at"])
        # Refresh self pour que l'appelant voie l'etat a jour
        self.locked_by = fresh.locked_by
        self.locked_at = fresh.locked_at
        return True

    def release_lock(self, user) -> None:
        """Libere le lock si user le detient. No-op sinon."""
        if self.locked_by_id == user.pk:
            self.locked_by = None
            self.locked_at = None
            self.save(update_fields=["locked_by", "locked_at", "updated_at"])


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
