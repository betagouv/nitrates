"""Modeles de l'app nitrates.

Contient :
  - `RpgCulture` : table de reference des codes culture du RPG
  - `DecisionTree` : versions de l'arbre de decision (draft/active/archive),
    source de verite runtime depuis la migration de l'arbre YAML vers la DB
  - `MoulinetteNitrates` : moulinette nitrates (heritage du pattern
    Envergo `Moulinette`, definie ici plutot que dans
    envergo/moulinette/models.py qui est deja sature)
"""

import copy
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
from envergo.nitrates.bassins import (
    bassin_code_from_attributes,
    bassin_label_from_attributes,
)
from envergo.nitrates.forms import MoulinetteFormNitrates
from envergo.nitrates.regions import region_for_department
from envergo.nitrates.zonage_montagne import (
    est_zone_montagne_d113_14,
    zonage_montagne_pour_commune,
)
from envergo.nitrates.zonage_note_5 import zone_note_5_pour_commune

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

    LOCK_TIMEOUT = timedelta(minutes=60)

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

        Renommage automatique :
          - L'actif courant (qui devient archive) est renomme avec un
            suffixe horodate '<canonical> – archive YYYY-MM-DD HH:MM'
            pour distinguer les versions historiques.
          - Le draft qui devient actif reprend le nom canonique de
            l'archive qu'il remplace (sans suffixe '– username-N').

        Idempotent : re-activer un tree deja actif ne casse rien.

        TODO MVP : un seul tree actif global. Quand on ajoutera les
        overrides regionaux (PAR), la notion d'actif devra etre adossee
        a un scope (national | region | dept | bassin) +
        champ optionnel `scope_value` (code region/dept/bassin), avec
        contrainte unique partielle sur (status='active', scope, scope_value).
        Cette methode `activate()` devra alors n'archiver que les actifs
        du meme scope.
        """
        now = timezone.now()
        canonical_name = None
        for current_active in DecisionTree.objects.filter(
            status=self.STATUS_ACTIVE
        ).exclude(pk=self.pk):
            # Sauvegarde le nom canonique (sans suffixe d'archive) pour
            # le passer au nouveau tree actif.
            canonical_name = canonical_name or current_active.name
            current_active.status = self.STATUS_ARCHIVE
            current_active.name = (
                f"{current_active.name} – archive {now:%Y-%m-%d %H:%M}"
            )
            current_active.save(update_fields=["status", "name", "updated_at"])
        # Le nouveau tree actif reprend le nom canonique. Si plusieurs
        # archives etaient au meme nom (peu probable), on garde le 1er.
        if canonical_name and self.name != canonical_name:
            self.name = canonical_name
        self.status = self.STATUS_ACTIVE
        self.activated_at = now
        self.save(update_fields=["status", "name", "activated_at", "updated_at"])

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

    @classmethod
    def unique_draft_name(cls, base_name: str, user=None) -> str:
        """Genere un nom de draft '<base> – <username>-<N>' sans collision.

        Quand plusieurs juristes editent en parallele, le nom du draft
        contient leur username pour qu'on identifie qui travaille sur
        quoi. <N> est le prochain numero libre pour cet utilisateur sur
        cette base.
        """
        username = (
            getattr(user, "username", None) or getattr(user, "email", None) or "anon"
        )
        # Garde une forme compacte : pas d'@ ni d'espace.
        username = username.split("@")[0].replace(" ", "_")
        n = 1
        while True:
            candidate = f"{base_name} – {username}-{n}"
            if not cls.objects.filter(name=candidate).exists():
                return candidate
            n += 1

    @classmethod
    def clone_to_draft(cls, source: "DecisionTree", user=None) -> "DecisionTree":
        """Clone un tree existant en nouveau draft. Le contenu et le YAML
        brut sont dupliques en profondeur. Le nouveau draft pointe vers
        `source` via `parent`."""
        return cls.objects.create(
            name=cls.unique_draft_name(source.name, user=user),
            status=cls.STATUS_DRAFT,
            contenu=copy.deepcopy(source.contenu),
            contenu_yaml_brut=source.contenu_yaml_brut,
            parent=source,
            created_by=user,
        )

    @classmethod
    def find_or_create_edit_draft(cls, user) -> "DecisionTree | None":
        """Trouve le draft d'edition de l'arbre actif pour cet utilisateur,
        ou en cree un nouveau.

        Logique : on cherche un draft existant qui satisfait les 3 criteres :
          1. parent = arbre actif courant
          2. created_by = user
          3. pas locked par un autre user (lock libre ou expire ou meme user)

        Si aucun match, on clone l'actif en nouveau draft. Permet a
        l'utilisateur de retrouver son travail en cours s'il revient
        plus tard, sans pour autant perturber un autre admin qui
        editerait deja un draft sur le meme actif.

        Retourne None si aucun arbre actif n'existe (cas anormal).
        """
        active = cls.objects.filter(status=cls.STATUS_ACTIVE).first()
        if active is None:
            return None

        # Cherche un draft reutilisable de cet utilisateur sur cet actif.
        candidates = cls.objects.filter(
            status=cls.STATUS_DRAFT,
            parent=active,
            created_by=user,
        ).order_by("-updated_at")
        for draft in candidates:
            if not draft.is_locked_by_other(user):
                return draft

        # Aucun draft reutilisable : on en cree un nouveau.
        return cls.clone_to_draft(active, user=user)


class DecisionTreeRevision(models.Model):
    """Historique d'une edition d'un DecisionTree.

    Chaque action d'edition (edit / add / delete / rename) cree une
    revision qui contient le snapshot complet d'AVANT l'action. Permet
    le retour en arriere pas a pas.

    Stockage : full snapshot (JSON + YAML brut). C'est plus simple et
    plus robuste qu'un systeme de patches, et la taille est OK
    (~40 KB par revision, max 50 revisions par tree = ~2 MB par draft).

    Auto-purge : au-dela de MAX_REVISIONS_PER_TREE, les revisions les
    plus anciennes sont supprimees. Voir `record()`.
    """

    ACTION_EDIT = "edit"
    ACTION_ADD = "add"
    ACTION_DELETE = "delete"
    ACTION_RENAME = "rename"
    ACTION_RESTORE = "restore"
    ACTION_CHOICES = [
        (ACTION_EDIT, "Édition"),
        (ACTION_ADD, "Ajout"),
        (ACTION_DELETE, "Suppression"),
        (ACTION_RENAME, "Renommage"),
        (ACTION_RESTORE, "Restauration"),
    ]

    MAX_REVISIONS_PER_TREE = 50

    tree = models.ForeignKey(
        "DecisionTree",
        on_delete=models.CASCADE,
        related_name="revisions",
    )
    action = models.CharField(max_length=16, choices=ACTION_CHOICES)
    target_path = models.CharField(max_length=500, blank=True)
    description = models.CharField(max_length=500, blank=True)

    # Snapshot complet d'avant l'action.
    previous_contenu = models.JSONField()
    previous_yaml_brut = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tree", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.tree.name} #{self.pk} {self.action} ({self.created_at:%Y-%m-%d %H:%M})"

    @classmethod
    def record(
        cls,
        tree: "DecisionTree",
        action: str,
        user=None,
        target_path: str = "",
        description: str = "",
    ) -> "DecisionTreeRevision":
        """Enregistre une revision avec snapshot de l'etat actuel du tree.

        A appeler AVANT toute mutation : on capture l'etat existant comme
        previous_contenu / previous_yaml_brut, puis l'appelant applique
        sa modification au tree et le save().

        Auto-purge : si on depasse MAX_REVISIONS_PER_TREE, on supprime les
        plus anciennes pour rester sous la limite.
        """
        revision = cls.objects.create(
            tree=tree,
            action=action,
            target_path=target_path,
            description=description,
            previous_contenu=copy.deepcopy(tree.contenu),
            previous_yaml_brut=tree.contenu_yaml_brut,
            created_by=user,
        )
        # Purge des revisions excedentaires.
        excess_pks = list(
            cls.objects.filter(tree=tree)
            .order_by("-created_at")
            .values_list("pk", flat=True)[cls.MAX_REVISIONS_PER_TREE :]  # noqa: E203
        )
        if excess_pks:
            cls.objects.filter(pk__in=excess_pks).delete()
        return revision

    def restore(self, drop: bool = True) -> None:
        """Restaure le tree dans l'etat capture par cette revision.

        Si `drop=True` (defaut) : on supprime cette revision apres
        restauration. C'est le comportement de "undo" : annuler une
        action efface aussi sa trace de l'historique. Permet d'undo en
        chaine sans ping-pong (la prochaine "derniere revision" est
        l'avant-derniere reelle).

        Si `drop=False` : on conserve la revision (utile si on veut
        permettre un redo, ou pour la page d'historique qui restaure un
        etat ancien sans casser le suivi).
        """
        self.tree.contenu = copy.deepcopy(self.previous_contenu)
        self.tree.contenu_yaml_brut = self.previous_yaml_brut
        self.tree.save(update_fields=["contenu", "contenu_yaml_brut", "updated_at"])
        if drop:
            self.delete()


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
                catalog["bassin"] = bassin_code_from_attributes(attrs)
                catalog["bassin_label"] = bassin_label_from_attributes(attrs)
            else:
                catalog["bassin"] = None
                catalog["bassin_label"] = None

            # Zonages reglementaires resolus a partir du code INSEE pousse
            # par le front (clic carte). Calcul cheap (lookup CSV en
            # memoire), on les pre-resoud ici pour les exposer dans le
            # panel debug -- le parcours d'arbre les recalcule a la
            # demande, mais c'est la meme fonction donc cohérent.
            # `code_insee` n'est pas un champ du form (il n'apparait pas
            # dans cleaned_data) ; on le lit dans les form_kwargs bruts.
            raw_data = self.form_kwargs.get("data", {}) or {}
            code_insee = raw_data.get("code_insee")
            catalog["code_insee"] = code_insee
            catalog["zone_montagne_d113_14"] = est_zone_montagne_d113_14(code_insee)
            catalog["zone_montagne_classification"] = zonage_montagne_pour_commune(
                code_insee
            )
            catalog["zone_note_5"] = zone_note_5_pour_commune(code_insee)

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


# ─── Validation manuelle des feuilles de l'arbre ───────────────────────────


def _branche_screenshot_path(instance, filename):
    """Stockage des screenshots Miro / Playwright sous media/nitrates_validation/."""
    return f"nitrates_validation/{instance.regle_id}/{filename}"


class BrancheValidation(models.Model):
    """Une ligne de validation manuelle pour une feuille de l'arbre nitrates.

    Cf. issue #28 / sprint MVP-1 fin : Max veut valider exhaustivement
    chaque feuille `culture_principale` de l'arbre en croisant 4 sources :
      1. screenshot du Miro juriste (uploade par Max)
      2. extrait YAML de la regle (calcule au seed)
      3. URL simulateur deeplink avec lat/lng + cascade pre-remplie
      4. screenshot Playwright auto-capture du resultat simulateur

    Pas de FK vers `DecisionTree` exprès : l'arbre actif change quand on
    re-import, et on veut garder l'historique des validations passees
    associees a leurs `regle_id` (qui sont stables a travers les imports).
    """

    STATUT_NON_VALIDE = "non_valide"
    STATUT_VALIDE = "valide"
    STATUT_A_CORRIGER = "a_corriger"
    STATUT_CHOICES = [
        (STATUT_NON_VALIDE, "Non validé"),
        (STATUT_VALIDE, "Validé"),
        (STATUT_A_CORRIGER, "À corriger"),
    ]

    # Identifiants stables a travers les re-imports d'arbre.
    regle_id = models.CharField(max_length=200, unique=True)
    branche_label = models.CharField(
        max_length=500,
        help_text="Chemin metier lisible (ex: 'culture_principale > colza > type_III > note_5')",
    )

    # Snapshot YAML de la regle au moment du seed. Permet de detecter une
    # divergence entre la regle qu'on a validee et la regle actuelle.
    yaml_snapshot = models.TextField(
        blank=True,
        help_text="Extrait YAML de la regle au moment du seed (round-trip)",
    )

    # Deeplink simulateur calcule au seed (lat/lng + cascade pour atteindre
    # la feuille). Format URL relative (sans host) pour rester portable
    # entre local / staging / prod.
    url_simulateur = models.CharField(
        max_length=2000,
        blank=True,
        help_text="URL relative du simulateur pre-rempli pour cette feuille",
    )

    # Screenshots
    screenshot_miro = models.ImageField(
        upload_to=_branche_screenshot_path,
        blank=True,
        null=True,
        help_text="Capture du Miro juriste pour cette branche (uploade par Max)",
    )
    screenshot_playwright = models.ImageField(
        upload_to=_branche_screenshot_path,
        blank=True,
        null=True,
        help_text="Capture auto Playwright du resultat simulateur",
    )
    playwright_run_at = models.DateTimeField(blank=True, null=True)

    # Validation
    statut = models.CharField(
        max_length=20, choices=STATUT_CHOICES, default=STATUT_NON_VALIDE
    )
    commentaire = models.TextField(blank=True)
    valide_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="branches_validees",
    )
    valide_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["branche_label"]
        verbose_name = "Validation de branche"
        verbose_name_plural = "Validations de branches"

    def __str__(self):
        return f"{self.regle_id} ({self.get_statut_display()})"
