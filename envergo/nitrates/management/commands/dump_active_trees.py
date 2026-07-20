"""Dump des arbres de decision ACTIFS vers leurs fichiers canoniques (GitOps, #50).

Pendant miroir de `import_decision_tree` : la DB active est dumpee dans des
fichiers YAML canoniques versionnes, un par ZONE d'activation. Le repo devient
la source de verite ; ce dump reflete l'etat actif de la base dans le repo.

Convention de nommage (identite = (scope, region) UNIQUEMENT, cf. spike #50) :

    specs/arbres_actifs/national.yaml            scope national
    specs/arbres_actifs/region_<code>.yaml       scope region  (ex region_44)
    specs/arbres_actifs/zar_<code>.yaml          scope zar     (ex zar_44)

Le nom de l'arbre, son weight et son activation_map ne font PAS partie de
l'identite : ils se deduisent (le CD `import_decision_tree` les reconstruit par
convention). Plusieurs arbres actifs pour une meme zone est impossible
(contrainte unique partielle) ; le fichier reflete l'unique actif de la zone.

Le YAML est normalise via le meme dump ruamel que l'editeur admin
(`yaml_admin.editor._dump_yaml`, width=4096, preserve_quotes) : round-trip
stable (teste 2026-07-20), donc redump idempotent et diffs git minimaux.

Usage :
    # Ecrit/rafraichit tous les fichiers canoniques
    python manage.py dump_active_trees

    # Garde-fou CI : n'ecrit RIEN, exit != 0 si un fichier du repo differe de
    # la DB active (fixture arbre perimee -> la PR doit re-dumper avant merge).
    python manage.py dump_active_trees --check
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from envergo.nitrates.models import DecisionTree
from envergo.nitrates.yaml_admin.editor import _dump_yaml

# Sous-repertoire miroir dedie : le hook/gate n'autorise le force-push QUE la.
ARBRES_ACTIFS_SUBDIR = "arbres_actifs"


def canonical_filename(scope: str, region_code: str) -> str:
    """Nom de fichier canonique deduit de la seule identite (scope, region)."""
    if scope == DecisionTree.SCOPE_NATIONAL:
        return "national.yaml"
    if scope == DecisionTree.SCOPE_REGION:
        return f"region_{region_code}.yaml"
    if scope == DecisionTree.SCOPE_ZAR:
        return f"zar_{region_code}.yaml"
    raise CommandError(f"Scope inconnu : {scope!r}")


def canonical_yaml(tree: DecisionTree) -> str:
    """YAML normalise de l'arbre (meme dump ruamel que l'editeur admin).

    On repart de `contenu` (le dict parse) plutot que de `contenu_yaml_brut`
    (le texte importe tel quel) : le dump normalise est la source canonique
    (decision #3 du spike), pas le brut. Round-trip stable verifie.
    """
    return _dump_yaml(tree.contenu)


class Command(BaseCommand):
    help = "Dumpe les arbres de decision actifs vers specs/arbres_actifs/ (GitOps #50)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check",
            action="store_true",
            help=(
                "N'ecrit rien. Exit != 0 si un fichier canonique du repo differe "
                "de la DB active (garde-fou CI : fixture perimee)."
            ),
        )
        parser.add_argument(
            "--dir",
            default=None,
            help=(
                "Repertoire specs (defaut: NITRATES_SPECS_DIR). Les fichiers sont "
                f"ecrits dans <dir>/{ARBRES_ACTIFS_SUBDIR}/."
            ),
        )

    def handle(self, *args, **options):
        check = options["check"]
        specs_dir = Path(options["dir"] or settings.NITRATES_SPECS_DIR)
        out_dir = specs_dir / ARBRES_ACTIFS_SUBDIR

        actifs = list(
            DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE).order_by(
                "scope", "region_code"
            )
        )
        if not actifs:
            self.stdout.write(self.style.WARNING("Aucun arbre actif en base."))
            return

        drift = []  # (fichier, raison) pour --check
        written = []

        if not check:
            out_dir.mkdir(parents=True, exist_ok=True)

        seen = set()
        for tree in actifs:
            fname = canonical_filename(tree.scope, tree.region_code or "")
            if fname in seen:
                # Deux actifs pour la meme zone : ne devrait pas arriver
                # (contrainte unique partielle). Signale plutot que d'ecraser.
                raise CommandError(
                    f"Deux arbres actifs pour la meme zone -> fichier {fname}. "
                    "Incoherence DB (contrainte unique partielle violee ?)."
                )
            seen.add(fname)

            path = out_dir / fname
            new_yaml = canonical_yaml(tree)

            if check:
                if not path.exists():
                    drift.append((fname, "absent du repo"))
                else:
                    current = path.read_text(encoding="utf-8")
                    if current != new_yaml:
                        drift.append((fname, "differe de la DB active"))
            else:
                previous = path.read_text(encoding="utf-8") if path.exists() else None
                if previous != new_yaml:
                    path.write_text(new_yaml, encoding="utf-8")
                    written.append(fname)
                self.stdout.write(
                    f"  {fname:22s} <- {tree.scope}/{tree.region_code or '-'} "
                    f"({tree.name})"
                    + ("  [ecrit]" if previous != new_yaml else "  [inchange]")
                )

        if check:
            if drift:
                lignes = "\n".join(f"  - {f} : {r}" for f, r in drift)
                raise CommandError(
                    "Fichiers canoniques d'arbres perimes vs DB active :\n"
                    + lignes
                    + "\n-> lancer `python manage.py dump_active_trees` puis committer."
                )
            self.stdout.write(
                self.style.SUCCESS(
                    f"OK : {len(actifs)} arbre(s) actif(s), fichiers canoniques a jour."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dump termine : {len(written)} fichier(s) ecrit(s) / "
                    f"{len(actifs)} arbre(s) actif(s)."
                )
            )
