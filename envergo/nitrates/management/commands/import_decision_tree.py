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

Usage :
    docker compose run --rm django python manage.py import_decision_tree \\
        /specs/arbre_decision_national.yaml --mode auto

    docker compose run --rm django python manage.py import_decision_tree \\
        /specs/arbre_decision_national.yaml --mode force-active --name pan_v2
"""

from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from envergo.nitrates.models import DecisionTree
from envergo.nitrates.regulations.arbre_decision import REFERENCE_TO_MAP_TYPE
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
                "auto: 1er tree -> active, sinon -> draft. "
                "draft (defaut): cree un draft, echoue si pas d'actif. "
                "force-active: cree puis active (archive l'actif courant)."
            ),
        )

    def handle(self, *args, **options):
        yaml_path: Path = options["yaml_path"]
        name: str = options["name"]
        mode: str = options["mode"]

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
        non_supportees = sorted(
            {ref for _, ref in refs_sig if ref not in REFERENCE_TO_MAP_TYPE}
        )
        if non_supportees:
            self.stdout.write(
                self.style.WARNING(
                    "References SIG utilisees par l'arbre mais non supportees "
                    "par le backend (dataset Map+Zone manquant ou mapping a "
                    "ajouter dans REFERENCE_TO_MAP_TYPE) :\n  - "
                    + "\n  - ".join(non_supportees)
                )
            )

        try:
            validate_arbre(arbre, referentiels)
        except ValidationError as e:
            raise CommandError(
                "Arbre invalide :\n  - " + "\n  - ".join(e.errors)
            ) from e

        with transaction.atomic():
            actif_courant = DecisionTree.objects.filter(
                status=DecisionTree.STATUS_ACTIVE
            ).first()

            if mode == "auto":
                if DecisionTree.objects.exists():
                    target_status = DecisionTree.STATUS_DRAFT
                else:
                    target_status = DecisionTree.STATUS_ACTIVE
            elif mode == "draft":
                if actif_courant is None:
                    raise CommandError(
                        "Pas d'arbre actif en base. Utiliser --mode auto "
                        "(ou --mode force-active) pour le 1er import."
                    )
                target_status = DecisionTree.STATUS_DRAFT
            else:  # force-active
                target_status = DecisionTree.STATUS_DRAFT  # active() apres

            tree = DecisionTree.objects.create(
                name=name,
                status=target_status,
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
        self.stdout.write(
            self.style.SUCCESS(
                f"Tree #{tree.id} ({tree.name}) cree -- status: {tree.status}"
            )
        )
