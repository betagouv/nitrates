"""Charge les arbres canoniques (specs/arbres_actifs/) en DB — reload du CD (#50).

Pendant load du `dump_active_trees` : chaque fichier canonique est (re)chargé
en base via le lifecycle draft->active (JAMAIS un override in-place), exactement
comme si un humain avait empile une version dans l'editeur YAML.

Cette commande est la 3e etape de la sequence de deploiement d'une merge request
sur un environnement (cf. spike #50) :
    1. dump_active_trees   -> capture l'etat ACTIF de la DB target dans le repo
    2. merge git           -> la PR est mergee par-dessus cette capture (ff/conflit)
    3. load_arbres_actifs  -> recharge le resultat merge en DB (draft->active)

Le scope/region est DEDUIT du nom de fichier (identite = (scope, region)) ; le
name/weight/activation_map se deduisent (convention). Delegue a
`import_decision_tree` pour la validation (referentiels + scope) et l'activation.

Idempotent : recharger un arbre identique a l'actif ne cree pas de bruit
(import_decision_tree cree un draft puis active ; si le contenu est identique,
c'est une nouvelle version identique — voir --skip-si-identique pour l'eviter).

Usage :
    python manage.py load_arbres_actifs                 # charge tous les fichiers
    python manage.py load_arbres_actifs --only region_44
    python manage.py load_arbres_actifs --dir /chemin/specs
    python manage.py load_arbres_actifs --skip-si-identique
"""

from pathlib import Path

import yaml
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from envergo.nitrates.management.commands.dump_active_trees import (
    ARBRES_ACTIFS_SUBDIR,
    canonical_yaml,
)
from envergo.nitrates.management.commands.validate_arbres_actifs import (
    scope_from_filename,
)
from envergo.nitrates.models import DecisionTree


class Command(BaseCommand):
    help = "Charge les arbres canoniques specs/arbres_actifs/ en DB (reload CD #50)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir",
            default=None,
            help="Répertoire specs (défaut: NITRATES_SPECS_DIR).",
        )
        parser.add_argument(
            "--only",
            default=None,
            help="Ne charger qu'un fichier précis (ex 'region_44' ou 'region_44.yaml').",
        )
        parser.add_argument(
            "--skip-si-identique",
            action="store_true",
            help=(
                "Ne recharge pas un arbre dont le contenu canonique est déjà "
                "identique à l'actif en base (évite une version-doublon)."
            ),
        )

    def _actif_identique(self, scope, region_code, yaml_text) -> bool:
        """True si l'actif de la zone a déjà exactement ce contenu canonique."""
        actif = DecisionTree.objects.filter(
            status=DecisionTree.STATUS_ACTIVE,
            scope=scope,
            region_code=region_code,
        ).first()
        if actif is None:
            return False
        return canonical_yaml(actif) == yaml_text

    def handle(self, *args, **options):
        specs_dir = Path(options["dir"] or settings.NITRATES_SPECS_DIR)
        arbres_dir = specs_dir / ARBRES_ACTIFS_SUBDIR
        only = options["only"]
        skip_identique = options["skip_si_identique"]

        if not arbres_dir.is_dir():
            raise CommandError(f"Répertoire introuvable : {arbres_dir}")

        if only:
            only_name = only if only.endswith(".yaml") else f"{only}.yaml"
            fichiers = [arbres_dir / only_name]
            if not fichiers[0].exists():
                raise CommandError(f"Fichier introuvable : {fichiers[0]}")
        else:
            fichiers = sorted(arbres_dir.glob("*.yaml"))
            if not fichiers:
                raise CommandError(f"Aucun fichier .yaml dans {arbres_dir}.")

        charges, skips = [], []
        for f in fichiers:
            coords = scope_from_filename(f.name)
            if coords is None:
                raise CommandError(
                    f"{f.name} : nom hors convention "
                    "(national.yaml / region_<code>.yaml / zar_<code>.yaml)."
                )
            scope, region_code = coords

            if skip_identique:
                text = f.read_text(encoding="utf-8")
                # On compare le dump normalisé de l'actif au contenu du fichier ;
                # si identique, inutile de créer une nouvelle version.
                try:
                    parsed = yaml.safe_load(text)
                    from envergo.nitrates.yaml_admin.editor import _dump_yaml

                    normalized = _dump_yaml(parsed)
                except Exception:
                    normalized = text
                if self._actif_identique(scope, region_code, normalized):
                    skips.append(f.name)
                    self.stdout.write(f"  {f.name:22s} [skip — identique à l'actif]")
                    continue

            # Délègue à import_decision_tree : validation (referentiels + scope)
            # + création draft + activate() (archive l'actif de la zone).
            # yaml_path est POSITIONNEL (pas d'option string) -> passé à part.
            import_kwargs = dict(
                mode="force-active",
                scope=scope,
                region_code=region_code,
                name=f.stem,  # nom libre, non identitaire (déductible du fichier)
            )
            # L'activation_map d'un ZAR se déduit : import_decision_tree l'exige.
            # Pour un ZAR, on la résout depuis l'actif courant de la zone si absent.
            if scope == DecisionTree.SCOPE_ZAR:
                actif = DecisionTree.objects.filter(
                    status=DecisionTree.STATUS_ACTIVE,
                    scope=scope,
                    region_code=region_code,
                ).first()
                if actif and actif.activation_map_id:
                    import_kwargs["activation_map"] = str(actif.activation_map_id)
                else:
                    raise CommandError(
                        f"{f.name} : ZAR sans activation_map déductible "
                        "(aucun actif de la zone en base pour la déduire). "
                        "Fournir la couche SIG via un premier import manuel."
                    )

            self.stdout.write(
                f"  {f.name:22s} -> {scope}/{region_code or '-'} [force-active]"
            )
            call_command("import_decision_tree", str(f), **import_kwargs)
            charges.append(f.name)

        self.stdout.write(
            self.style.SUCCESS(
                f"Reload terminé : {len(charges)} chargé(s), {len(skips)} skip(s)."
            )
        )
