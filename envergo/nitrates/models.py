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
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
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
from envergo.nitrates.zonage_zones_est import est_zone_grand_est_1, est_zone_grand_est_2

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

    # Perimetre d'application (zone d'activation declarative) de cet arbre.
    #   national : PAN, defaut partout (pas de region ni de couche SIG).
    #   region   : PAR regional (ex Grand Est R44), actif sur la region + ZV.
    #   zar      : PAR en zone d'action renforcee, actif sur une couche SIG.
    # Le PAN est declaratif (scope=national), jamais deduit de l'absence de FK.
    SCOPE_NATIONAL = "national"
    SCOPE_REGION = "region"
    SCOPE_ZAR = "zar"
    SCOPE_CHOICES = [
        (SCOPE_NATIONAL, "National (PAN)"),
        (SCOPE_REGION, "Régional (PAR)"),
        (SCOPE_ZAR, "Zone d'action renforcée (ZAR)"),
    ]
    # Poids de resolution : le candidat active de poids MAX gagne. Trous
    # volontaires pour inserer un scope intermediaire (ex dept=15) plus tard
    # sans rejouer les poids existants.
    DEFAULT_WEIGHT_BY_SCOPE = {
        SCOPE_NATIONAL: 1,
        SCOPE_REGION: 10,
        SCOPE_ZAR: 20,
    }

    name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT
    )

    # ─── Zone d'activation (selection dynamique PAN/PAR/ZAR) ───────────────
    scope = models.CharField(
        "Périmètre",
        max_length=16,
        choices=SCOPE_CHOICES,
        default=SCOPE_NATIONAL,
    )
    # Code region INSEE (ex "44" = Grand Est). Requis si scope=region.
    region_code = models.CharField("Code région", max_length=3, blank=True, default="")
    # Couche SIG d'activation (ZAR). Requise si scope=zar ; optionnelle ailleurs
    # (plasticite : un PAR peut a terme s'activer par SIG, region ou codes).
    activation_map = models.ForeignKey(
        "geodata.Map",
        verbose_name="Couche d'activation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    # Poids de resolution : le candidat active de poids MAX gagne.
    weight = models.PositiveIntegerField("Poids de résolution", default=1)

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
            # Plusieurs arbres actifs coexistent (PAN + PAR + ZAR), mais un seul
            # par zone d'activation. En PG/Django 4.2 les NULL sont DISTINCTS
            # dans un index unique : une contrainte composite sur
            # (scope, region_code, activation_map) ne couvre donc PAS les lignes
            # ou activation_map IS NULL (= PAN ET PAR-hors-ZAR). D'ou 3 contraintes.
            #
            # (a) region-avec-map & zar : activation_map NON NULL -> composite fiable.
            models.UniqueConstraint(
                fields=["scope", "region_code", "activation_map"],
                condition=Q(status="active", activation_map__isnull=False),
                name="nitrates_decisiontree_unique_active_map",
            ),
            # (b) National : 1 seul PAN actif (map NULL -> non couvert par (a)).
            models.UniqueConstraint(
                fields=["scope"],
                condition=Q(status="active", scope="national"),
                name="nitrates_decisiontree_unique_active_national",
            ),
            # (c) PAR regional sans couche SIG : 1 seul actif par region.
            models.UniqueConstraint(
                fields=["scope", "region_code"],
                condition=Q(
                    status="active", scope="region", activation_map__isnull=True
                ),
                name="nitrates_decisiontree_unique_active_region_no_map",
            ),
        ]
        indexes = [
            models.Index(fields=["status"]),
        ]
        ordering = ["-activated_at", "-created_at"]
        # Affiche "Arbre de décision" dans l'admin Django (au lieu de
        # "Decision tree" derive du nom de classe). La classe Python reste
        # `DecisionTree` pour ne pas casser les ~45 fichiers qui l'importent.
        verbose_name = "Arbre de décision"
        verbose_name_plural = "Arbres de décision"

    def __str__(self):
        return f"{self.name} ({self.status})"

    def clean(self):
        """Coherence declarative de la zone d'activation.

        Appele par full_clean()/forms admin (pas par save()). Les garanties
        d'unicite, elles, sont assurees par les contraintes DB (cf. Meta).
        """
        super().clean()
        if self.scope == self.SCOPE_NATIONAL:
            if self.region_code or self.activation_map_id is not None:
                raise ValidationError(
                    "Un arbre national (PAN) ne doit avoir ni code région "
                    "ni couche d'activation."
                )
        elif self.scope == self.SCOPE_REGION:
            if not self.region_code:
                raise ValidationError(
                    "Un arbre régional (PAR) doit avoir un code région."
                )
        elif self.scope == self.SCOPE_ZAR:
            if self.activation_map_id is None:
                raise ValidationError(
                    "Un arbre ZAR doit avoir une couche d'activation (SIG)."
                )

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

        Multi-arbres : on n'archive que les actifs de la MEME zone d'activation
        (scope, region_code, activation_map). Activer un PAR Grand Est ne
        touche donc pas le PAN ni le ZAR -- ils restent actifs en parallele.
        """
        now = timezone.now()
        canonical_name = None
        for current_active in DecisionTree.objects.filter(
            status=self.STATUS_ACTIVE,
            scope=self.scope,
            region_code=self.region_code,
            activation_map=self.activation_map,
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
        `source` via `parent`.

        La zone d'activation (scope / region_code / activation_map / weight)
        est HERITEE de la source : un draft de PAR/ZAR reste dans sa zone, pour
        que la preview et l'activation soient coherentes (sinon un draft de ZAR
        deviendrait un PAN a l'activation)."""
        return cls.objects.create(
            name=cls.unique_draft_name(source.name, user=user),
            status=cls.STATUS_DRAFT,
            scope=source.scope,
            region_code=source.region_code,
            activation_map=source.activation_map,
            weight=source.weight,
            contenu=copy.deepcopy(source.contenu),
            contenu_yaml_brut=source.contenu_yaml_brut,
            parent=source,
            created_by=user,
        )

    @classmethod
    def find_or_create_edit_draft(
        cls, user, active: "DecisionTree | None" = None
    ) -> "DecisionTree | None":
        """Trouve le draft d'edition de l'arbre actif `active` pour cet
        utilisateur, ou en cree un nouveau.

        `active` est l'arbre ACTIF de la zone d'activation a editer (PAN, PAR,
        ZAR...). Plusieurs arbres etant actifs simultanement, l'appelant doit
        preciser lequel. Le lock est porte par le draft, donc le verrouillage
        est naturellement PAR ZONE : editer le draft du PAR n'empeche pas
        d'editer celui du PAN.

        Logique : on cherche un draft existant qui satisfait les 3 criteres :
          1. parent = `active`
          2. created_by = user
          3. pas locked par un autre user (lock libre ou expire ou meme user)
        Si aucun match, on clone `active` en nouveau draft.

        Retourne None si `active` est None (aucun arbre actif pour cette zone).
        """
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
            # On memorise l'id de la zone ZV intersectee pour que
            # get_criteria n'ait pas a refaire un ST_Intersects exact sur la
            # geometrie ZV (~2 M points, ~0.5 s). cf. get_criteria.
            catalog["zv_zone_id"] = zv_zone.id if zv_zone else None
            if zv_zone:
                attrs = zv_zone.attributes or {}
                catalog["bassin"] = bassin_code_from_attributes(attrs)
                catalog["bassin_label"] = bassin_label_from_attributes(attrs)
            else:
                catalog["bassin"] = None
                catalog["bassin_label"] = None

            # Zone d'action renforcee (ZAR) : couche SIG du PAR Grand Est.
            # Memo de l'id de zone (PK indexe) pour que select_active_tree
            # selectionne l'arbre ZAR sans refaire un ST_Intersects exact.
            # Couche petite (186 zones) -> cout negligeable, et atteinte
            # uniquement pour des points en ZV (hors ZV, get_criteria renvoie
            # none() donc l'arbre n'est pas evalue).
            zar_zone = (
                Zone.objects.filter(
                    map__map_type=MAP_TYPES.zone_action_renforcee,
                    geometry__intersects=point,
                )
                .only("id")
                .first()
            )
            catalog["en_zar"] = zar_zone is not None
            catalog["zar_zone_id"] = zar_zone.id if zar_zone else None

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
            # Zones Est Grand Est (resolues par code INSEE / departement, cf.
            # zonage_zones_est). Exposees pour le debug : aident a comprendre
            # pourquoi un arbre PAR Grand Est route vers tel sous-cas.
            catalog["zone_grand_est_1"] = est_zone_grand_est_1(code_insee)
            catalog["zone_grand_est_2"] = est_zone_grand_est_2(code_insee)

        return catalog

    def get_criteria(self):
        """Filtre les criteres par intersection avec leur activation_map.

        Le critere `arbre_decision` a la map ZV comme activation_map :
        si le point n'intersecte aucune ZV, le critere n'est pas retourne
        et l'arbre ne tourne pas.

        Perf : on filtre UNIQUEMENT par `intersects`, sans calculer la
        distance exacte. Les criteres nitrates ont `activation_distance=0`
        (activation binaire dans/hors ZV) : un point qui intersecte la zone
        est forcement a distance 0, donc `distance <= activation_distance`
        est toujours vrai et redondant. Or `ST_Distance` exact sur la
        geometrie ZV (~2 M points) coute ~1.3 s par appel -- on l'evite.
        Si un jour un critere nitrates utilise une activation_distance > 0
        (buffer), il faudra reintroduire le filtre distance ici."""
        coords = self.catalog.get("lng_lat")
        criteria = super().get_criteria()
        if coords is None:
            return criteria.none()

        # get_catalog_data a deja resolu la zone ZV intersectee (statut ZV).
        # On reutilise son id pour filtrer par PK plutot que de refaire un
        # ST_Intersects exact sur la geometrie ZV (~2 M points, ~0.5 s).
        # "zv_zone_id" absent du catalog => None par defaut (cle posee a
        # chaque passage de get_catalog_data des qu'on a lng/lat).
        if "zv_zone_id" in self.catalog:
            zone_id = self.catalog["zv_zone_id"]
            if zone_id is None:
                # Hors ZV : aucun critere nitrates ne s'active.
                return criteria.none()
            return criteria.filter(activation_map__zones__id=zone_id).select_related(
                "activation_map"
            )

        # Fallback (catalog incomplet) : intersection geographique directe.
        return criteria.filter(
            activation_map__zones__geometry__intersects=coords
        ).select_related("activation_map")

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
    """Stockage des screenshots Miro / Playwright / YAML sous
    media/nitrates_validation/<regle_id_or_pk>/<filename>.

    On utilise regle_id si dispo (court et lisible), sinon pk. Pas le
    chemin_yaml complet : trop long pour le max_length du ImageField
    apres slugification."""
    # Borne le folder : certains regle_id couvert depassent 60 char et le
    # chemin complet depasse le max_length du storage. Les regle_id CP sont
    # courts, donc inchanges en pratique.
    folder = (instance.regle_id or f"id-{instance.pk or 'new'}")[:60]
    return f"nitrates_validation/{folder}/{filename}"


class BrancheValidation(models.Model):
    """Une ligne de validation manuelle pour une feuille de l'arbre nitrates.

    Cf. issue #28 / sprint MVP-1 fin : Max valide exhaustivement chaque
    feuille `culture_principale` en croisant 5 sources :
      1. PNG Miro juriste (auto-attach depuis snapshot_miro/<branche>.png)
      2. Screenshot admin YAML viewer (uploade par Max, devops local)
      3. Screenshot admin YAML editor (cas tricky type colza Type III)
      4. URL simulateur deeplink avec lat/lng + cascade pre-remplie
      5. Screenshot Playwright du resultat simulateur (uploade par Max)

    Cle naturelle : `chemin_yaml` (path d'IDs YAML, ex
    "n_zvn/q_occupation_sol/q_culture_principale_type/q_colza_fertilisant/r_colza_type_0").
    Stable a travers les re-imports tant que les IDs YAML ne changent pas.
    """

    STATUT_NON_VALIDE = "non_valide"
    STATUT_VALIDE = "valide"
    STATUT_A_CORRIGER = "a_corriger"
    STATUT_CHOICES = [
        (STATUT_NON_VALIDE, "Non validé"),
        (STATUT_VALIDE, "Validé"),
        (STATUT_A_CORRIGER, "À corriger"),
    ]

    # Cle naturelle : path d'ids YAML separes par "/".
    chemin_yaml = models.CharField(
        max_length=1000,
        unique=True,
        help_text="Path d'ids YAML depuis la racine vers la feuille",
    )
    # Ordre d'affichage canonique du Miro juriste (haut en bas).
    # Rempli au seed dans l'ordre d'apparition dans index.yaml. Permet de
    # parcourir la liste de validation dans le meme ordre que le Miro.
    ordre = models.PositiveIntegerField(default=0, db_index=True)
    # Dernier segment du chemin = id de la regle (ou "renvoi_vers:..." si
    # la branche pointe ailleurs sans regle directe).
    regle_id = models.CharField(max_length=200, blank=True)
    branche_label = models.CharField(
        max_length=500,
        help_text="Chemin metier lisible (ex: 'sous_culture=colza / type_fertilisant=type_III')",
    )

    # ─── Source 1 : YAML codé ────────────────────────────────────────────
    yaml_snapshot = models.TextField(
        blank=True,
        help_text="Extrait YAML de la regle au moment du seed (round-trip)",
    )

    # ─── Source 2 : Miro juriste ─────────────────────────────────────────
    branche_miro = models.CharField(
        max_length=200,
        blank=True,
        help_text="Slug branche cote Miro (colza, luzerne, ...)",
    )
    type_fertilisant_miro = models.CharField(max_length=50, blank=True)
    condition_miro = models.CharField(max_length=200, blank=True)
    zonage_miro = models.CharField(max_length=200, blank=True)
    resultat_miro = models.CharField(
        max_length=500,
        blank=True,
        help_text="Texte resultat attendu cote Miro (ex 'Interdit du 15/12 au 15/01')",
    )
    code_pc_miro = models.CharField(max_length=20, blank=True)
    screenshot_miro = models.ImageField(
        upload_to=_branche_screenshot_path,
        blank=True,
        null=True,
        help_text="PNG Miro auto-attache depuis snapshot_miro/.../<branche>.png",
    )

    # ─── Source 3 : Admin YAML viewer / form (uploade manuellement) ──────
    screenshot_yaml_viewer = models.ImageField(
        upload_to=_branche_screenshot_path,
        blank=True,
        null=True,
        help_text="Capture admin YAML viewer scrolle sur la feuille",
    )
    screenshot_yaml_form = models.ImageField(
        upload_to=_branche_screenshot_path,
        blank=True,
        null=True,
        help_text="Capture du form d'edition du noeud (cas tricky)",
    )

    # ─── Source 4 : URL simulateur ───────────────────────────────────────
    url_simulateur = models.CharField(
        max_length=2000,
        blank=True,
        help_text="URL relative du simulateur pre-rempli pour cette feuille",
    )

    # ─── Source 5 : Screenshot Playwright (devops manuel) ────────────────
    screenshot_playwright = models.ImageField(
        upload_to=_branche_screenshot_path,
        blank=True,
        null=True,
        help_text="Capture du resultat simulateur (devops manuel)",
    )
    playwright_run_at = models.DateTimeField(blank=True, null=True)

    # ─── Validation ─────────────────────────────────────────────────────
    # Plusieurs personnes peuvent valider la meme branche. Chaque action
    # (valide / a_corriger / re-non_valide) est enregistree dans
    # BrancheValidationAction. Le statut courant = derniere action en date.
    # On garde un champ statut denormalise sur cette table pour pouvoir
    # filtrer/ordonner en SQL sans join, mais c'est mis a jour par la vue
    # quand une action est ajoutee.
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default=STATUT_NON_VALIDE,
        help_text="Statut courant : derniere action enregistree",
    )

    # ─── Flag « cas special a verifier » (rempli au seed) ────────────────
    # Independant du statut de validation humaine : c'est une note POSEE
    # PAR LE SEED pour attirer l'oeil du valideur sur un point precis
    # (divergence YAML vs board, formulation a trancher, feuille
    # calculatrice sans texte fige a comparer visuellement, ...). Permet
    # de ne pas perdre la trace des cas a regarder lors de la
    # re-validation humaine. Re-rempli a chaque seed (idempotent).
    flag_verif = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Cas special signale au seed, a verifier manuellement",
    )
    note_verif = models.TextField(
        blank=True,
        help_text="Detail du cas a verifier (pose par le seed, pas une action user)",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ordre", "chemin_yaml"]
        verbose_name = "Validation de branche"
        verbose_name_plural = "Validations de branches"

    def __str__(self):
        return f"{self.regle_id or self.chemin_yaml} ({self.get_statut_display()})"

    def derniere_action(self):
        return self.actions.order_by("-created_at").first()

    def actions_par_user(self):
        """Pour chaque user qui a deja valide cette branche, sa derniere
        action. Permet d'afficher 'Max valide le X, Emma valide le Y'.

        Trie en Python (et non en SQL via order_by) pour reutiliser le
        cache du prefetch_related cote vue. Le BrancheValidationAction
        Meta.ordering est ['-created_at'] (DESC), donc on parcourt en sens
        inverse pour avoir l'ordre ASC sans re-query."""
        seen = {}
        for a in sorted(self.actions.all(), key=lambda a: a.created_at):
            seen[a.user_id] = a
        return list(seen.values())


class BrancheValidationAction(models.Model):
    """Une action de validation enregistree pour une BrancheValidation.

    Permet a plusieurs personnes (Max, Emma, Louise...) de valider la meme
    branche independamment. L'historique complet est conserve. Le statut
    courant de la BrancheValidation = statut de la derniere action.
    """

    branche = models.ForeignKey(
        BrancheValidation,
        on_delete=models.CASCADE,
        related_name="actions",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="branches_validation_actions",
    )
    statut = models.CharField(max_length=20, choices=BrancheValidation.STATUT_CHOICES)
    commentaire = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Action de validation"
        verbose_name_plural = "Actions de validation"

    def __str__(self):
        user_disp = self.user.email if self.user_id else "?"
        return f"{user_disp} -> {self.statut} ({self.created_at:%d/%m/%Y %H:%M})"


# ─── Référentiels (cf. carte #61 — migration referentiels.yaml) ───────────────
# Modèles définis dans un module séparé pour la lisibilité ; ré-exportés ici
# pour que Django les enregistre dans l'app nitrates et que les imports
# `from envergo.nitrates.models import X` fonctionnent.

from envergo.nitrates.models_contenu_rich import (  # noqa: E402, F401  (carte #131)
    ContenuRichDSFR,
)
from envergo.nitrates.models_ouverture import (  # noqa: E402, F401  (carte #57)
    DepartementOuverture,
    departement_est_ouvert,
)
from envergo.nitrates.models_referentiels import (  # noqa: E402, F401
    BrancheCulturale,
    CodePrescription,
    Culture,
    EvenementPhenologique,
    Fertilisant,
    GroupeCultureUI,
    NoteReglementaire,
)
