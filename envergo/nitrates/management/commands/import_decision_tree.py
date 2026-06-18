"""Import d'un arbre de decision YAML vers la table DecisionTree.

Lit un fichier YAML, le valide via `validate_arbre()`, et cree un
`DecisionTree` en base. Mode controle si le tree devient actif (et
archive le precedent) ou reste en draft.

Modes :
    auto          : si table vide, importe en active. Sinon, en draft.
    draft (defaut): importe en draft. Echoue si aucun actif n'existe (rien a
                    referencer comme parent). Pour le tout 1er import,
                    utiliser auto ou force-active.
    force-active  : importe en draft puis appelle activate(). L'actif
                    courant passe en archive.

Zone d'activation (defaut = PAN national) : --scope / --region-code /
--activation-map / --weight permettent d'importer un arbre PAR ou ZAR scope.
Tout (mode, parent, unicite de l'actif) raisonne alors PAR ZONE.

Usage :
    # PAN national (defaut)
    docker compose run --rm django python manage.py import_decision_tree \\
        /specs/arbre_decision_national.yaml --mode auto

    docker compose run --rm django python manage.py import_decision_tree \\
        /specs/arbre_decision_national.yaml --mode force-active --name pan_v2

    # PAR Grand Est hors ZAR
    docker compose run --rm django python manage.py import_decision_tree \\
        /specs/par_grand_est.yaml --scope region --region-code 44 \\
        --mode auto --name par_ge

    # PAR Grand Est en ZAR (couche SIG par nom ou pk)
    docker compose run --rm django python manage.py import_decision_tree \\
        /specs/par_grand_est_zar.yaml --scope zar --region-code 44 \\
        --activation-map zar_par7_grand_est --mode auto --name zar_ge
"""

from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from envergo.geodata.models import Map
from envergo.nitrates.models import DecisionTree
from envergo.nitrates.yaml_admin.catalogue_refs import CATALOGUE_RESOLVERS
from envergo.nitrates.yaml_tree.loader import load_referentiels
from envergo.nitrates.yaml_tree.validator import (
    ValidationError,
    collect_references_sig,
    validate_arbre,
)


class Command(BaseCommand):
    help = "Importe un arbre de decision YAML dans la table DecisionTree."

    def add_arguments(self, parser):
        parser.add_argument(
            "yaml_path",
            type=Path,
            help="Chemin vers le fichier YAML de l'arbre.",
        )
        parser.add_argument(
            "--name",
            default="arbre_decision_national",
            help="Nom logique du tree (defaut: arbre_decision_national).",
        )
        parser.add_argument(
            "--mode",
            choices=["auto", "draft", "force-active"],
            default="draft",
            help=(
                "auto: 1er tree DE LA ZONE -> active, sinon -> draft. "
                "draft (defaut): cree un draft, echoue si pas d'actif dans la "
                "zone. force-active: cree puis active (archive l'actif de la "
                "meme zone)."
            ),
        )
        # ─── Zone d'activation (defaut = PAN national) ─────────────────────
        parser.add_argument(
            "--scope",
            choices=[
                DecisionTree.SCOPE_NATIONAL,
                DecisionTree.SCOPE_REGION,
                DecisionTree.SCOPE_ZAR,
            ],
            default=DecisionTree.SCOPE_NATIONAL,
            help="Perimetre d'activation (defaut: national = PAN).",
        )
        parser.add_argument(
            "--region-code",
            default="",
            help="Code region INSEE (ex 44). Requis si --scope region/zar.",
        )
        parser.add_argument(
            "--activation-map",
            default=None,
            help=(
                "Couche SIG d'activation : pk ou nom de la Map. "
                "Requis si --scope zar."
            ),
        )
        parser.add_argument(
            "--weight",
            type=int,
            default=None,
            help=(
                "Poids de resolution (le plus eleve gagne). Defaut selon le "
                "scope : national=1, region=10, zar=20."
            ),
        )

    def _resolve_activation_map(self, value):
        """Resout une Map par pk (si numerique) ou par nom. None si non fourni."""
        if not value:
            return None
        if str(value).isdigit():
            try:
                return Map.objects.get(pk=int(value))
            except Map.DoesNotExist as e:
                raise CommandError(f"Couche d'activation pk={value} introuvable") from e
        try:
            return Map.objects.get(name=value)
        except Map.DoesNotExist as e:
            raise CommandError(
                f"Couche d'activation nommee {value!r} introuvable"
            ) from e

    def handle(self, *args, **options):
        yaml_path: Path = options["yaml_path"]
        name: str = options["name"]
        mode: str = options["mode"]

        # ─── Zone d'activation ─────────────────────────────────────────────
        scope: str = options["scope"]
        region_code: str = options["region_code"] or ""
        activation_map = self._resolve_activation_map(options["activation_map"])
        weight = options["weight"]
        if weight is None:
            weight = DecisionTree.DEFAULT_WEIGHT_BY_SCOPE.get(scope, 1)

        # Coherence declarative (meme regle que DecisionTree.clean()).
        if scope == DecisionTree.SCOPE_NATIONAL:
            if region_code or activation_map is not None:
                raise CommandError(
                    "--scope national : ni --region-code ni --activation-map."
                )
        elif scope == DecisionTree.SCOPE_REGION:
            if not region_code:
                raise CommandError("--scope region exige --region-code.")
        elif scope == DecisionTree.SCOPE_ZAR:
            if not region_code:
                raise CommandError("--scope zar exige --region-code.")
            if activation_map is None:
                raise CommandError("--scope zar exige --activation-map.")

        if not yaml_path.exists():
            raise CommandError(f"Fichier YAML introuvable : {yaml_path}")

        text = yaml_path.read_text(encoding="utf-8")
        try:
            arbre = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise CommandError(f"YAML invalide : {e}") from e

        # Validation structurelle + semantique. On charge les referentiels
        # depuis le fichier (referentiels.yaml n'est pas migre en DB).
        try:
            referentiels = load_referentiels()
        except FileNotFoundError:
            referentiels = None
            self.stdout.write(
                self.style.WARNING(
                    "referentiels.yaml introuvable -- validation des "
                    "references (codes_prescription, notes, evenements) "
                    "ignoree. Verifier NITRATES_SPECS_DIR."
                )
            )

        # Warning non-bloquant : references SIG utilisees par l'arbre mais
        # pas encore implementees cote backend (dataset Map+Zone manquant).
        # Le runtime affichera "non disponible" sur ces branches ; ici on
        # liste juste les trous pour traque.
        refs_sig = collect_references_sig(arbre)
        # Le backend resoud les references SIG via le registre
        # `catalogue_refs.CATALOGUE_RESOLVERS` (PostGIS, mapping commune
        # INSEE, etc., suivant le resolveur).
        refs_supportees = {r.reference for r in CATALOGUE_RESOLVERS}
        non_supportees = sorted(
            {ref for _, ref in refs_sig if ref not in refs_supportees}
        )
        if non_supportees:
            self.stdout.write(
                self.style.WARNING(
                    "References SIG utilisees par l'arbre mais non supportees "
                    "par le backend (resolveur a ajouter dans "
                    "catalogue_refs.CATALOGUE_RESOLVERS) :\n  - "
                    + "\n  - ".join(non_supportees)
                )
            )

        try:
            validate_arbre(arbre, referentiels, scope=scope)
        except ValidationError as e:
            raise CommandError(
                "Arbre invalide :\n  - " + "\n  - ".join(e.errors)
            ) from e

        with transaction.atomic():
            # L'actif courant servant de parent est l'actif de LA MEME zone
            # d'activation (scope, region_code, activation_map) -- un import de
            # PAR Grand Est se rattache au PAR Grand Est actif, pas au PAN.
            zone_filter = dict(
                status=DecisionTree.STATUS_ACTIVE,
                scope=scope,
                region_code=region_code,
                activation_map=activation_map,
            )
            actif_courant = DecisionTree.objects.filter(**zone_filter).first()

            if mode == "auto":
                # "1er tree de la zone" : on regarde s'il existe deja un arbre
                # (tous statuts) sur cette zone, pas dans toute la table.
                deja_dans_zone = DecisionTree.objects.filter(
                    scope=scope,
                    region_code=region_code,
                    activation_map=activation_map,
                ).exists()
                target_status = (
                    DecisionTree.STATUS_DRAFT
                    if deja_dans_zone
                    else DecisionTree.STATUS_ACTIVE
                )
            elif mode == "draft":
                if actif_courant is None:
                    raise CommandError(
                        "Pas d'arbre actif pour cette zone d'activation. "
                        "Utiliser --mode auto (ou --mode force-active) pour le "
                        "1er import de la zone."
                    )
                target_status = DecisionTree.STATUS_DRAFT
            else:  # force-active
                target_status = DecisionTree.STATUS_DRAFT  # active() apres

            tree = DecisionTree.objects.create(
                name=name,
                status=target_status,
                scope=scope,
                region_code=region_code,
                activation_map=activation_map,
                weight=weight,
                contenu=arbre,
                contenu_yaml_brut=text,
                parent=actif_courant,
            )

            if mode == "force-active":
                tree.activate()
            elif mode == "auto" and target_status == DecisionTree.STATUS_ACTIVE:
                # Pas d'archive a faire (table vide), on remplit juste activated_at.
                tree.activate()

        tree.refresh_from_db()
        zone = tree.scope
        if tree.region_code:
            zone += f" {tree.region_code}"
        if tree.activation_map_id:
            zone += f" / map={tree.activation_map_id}"
        self.stdout.write(
            self.style.SUCCESS(
                f"Tree #{tree.id} ({tree.name}) cree -- status: {tree.status} "
                f"-- zone: {zone} (poids {tree.weight})"
            )
        )
