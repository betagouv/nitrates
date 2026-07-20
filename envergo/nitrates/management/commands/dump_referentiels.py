"""Dump des referentiels DB vers la fixture canonique (GitOps, #50).

Pendant miroir de `seed_referentiels` : dumpe les tables referentiel en
CLES NATURELLES (pas les PK auto-incrementees, non portables entre DB) vers
`fixtures/initial_referentiels.json`. Le repo devient la source de verite ;
ce dump reflete l'etat DB actif dans le repo.

Portabilite (condition de correction du GitOps, cf. spike #50) : on serialise
avec `--natural-primary-key --natural-foreign` pour qu'un `seed_referentiels`
(loaddata) sur une AUTRE base resolve chaque objet par sa cle stable
(`identifiant` / `cle`) et ses FK par cle naturelle, pas par un id qui differe
d'un environnement a l'autre.

Contrairement aux arbres (edition continue -> hook temps-reel), les referentiels
sont edites rarement : pas de hook, juste un `--check` en CI qui echoue si la
fixture du repo differe de la DB active (la PR doit re-dumper avant merge).

Usage :
    # Rafraichit la fixture
    python manage.py dump_referentiels

    # Garde-fou CI : n'ecrit rien, exit != 0 si la fixture differe de la DB
    python manage.py dump_referentiels --check
"""

import io
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

# 8 modeles suivis par le GitOps (7 referentiels + ContenuRichDSFR standalone).
# Ordre = dependances FK pour un loaddata rejouable (parents avant enfants).
_MODELS = [
    "nitrates.GroupeCultureUI",
    "nitrates.BrancheCulturale",
    "nitrates.Culture",
    "nitrates.Fertilisant",
    "nitrates.NoteReglementaire",
    "nitrates.CodePrescription",
    "nitrates.EvenementPhenologique",
    "nitrates.ContenuRichDSFR",
]

_DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "initial_referentiels.json"
)


def dump_fixture() -> str:
    """Serialise les 8 modeles en JSON, cles naturelles, indent 2."""
    buf = io.StringIO()
    call_command(
        "dumpdata",
        *_MODELS,
        format="json",
        indent=2,
        use_natural_foreign_keys=True,
        use_natural_primary_keys=True,
        stdout=buf,
    )
    text = buf.getvalue()
    # dumpdata n'ajoute pas de newline final ; on en met un pour un diff git propre.
    return text if text.endswith("\n") else text + "\n"


class Command(BaseCommand):
    help = "Dumpe les referentiels DB vers initial_referentiels.json en cles naturelles (GitOps #50)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check",
            action="store_true",
            help=(
                "N'ecrit rien. Exit != 0 si la fixture du repo differe de la DB "
                "active (garde-fou CI : fixture perimee)."
            ),
        )
        parser.add_argument(
            "--fixture",
            default=None,
            help="Chemin de sortie (defaut: fixtures/initial_referentiels.json).",
        )

    def handle(self, *args, **options):
        check = options["check"]
        path = Path(options["fixture"] or _DEFAULT_FIXTURE)

        new_fixture = dump_fixture()

        if check:
            if not path.exists():
                raise CommandError(f"Fixture absente du repo : {path}")
            current = path.read_text(encoding="utf-8")
            if current != new_fixture:
                raise CommandError(
                    f"Fixture referentiels perimee vs DB active : {path.name}\n"
                    "-> lancer `python manage.py dump_referentiels` puis committer."
                )
            self.stdout.write(
                self.style.SUCCESS("OK : fixture referentiels a jour vs DB active.")
            )
            return

        previous = path.read_text(encoding="utf-8") if path.exists() else None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_fixture, encoding="utf-8")
        etat = "inchangee" if previous == new_fixture else "ecrite"
        self.stdout.write(self.style.SUCCESS(f"Fixture referentiels {etat} : {path}"))
