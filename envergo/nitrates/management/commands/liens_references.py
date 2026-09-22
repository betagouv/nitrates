"""Inventaire des liens syndiqués (LienReference, #467).

Liste les liens et, avec --usages, scanne les blocs riches (CodePrescription
et ContenuRichDSFR) pour dire qui référence quoi — y compris les lien_ref
orphelins (référencés dans un bloc mais absents de la table).

Usage :
    python manage.py liens_references
    python manage.py liens_references --usages
"""

from django.core.management.base import BaseCommand


def _collecter_refs(obj, refs):
    if isinstance(obj, dict):
        ref = obj.get("lien_ref")
        if ref:
            refs.add(ref)
        for valeur in obj.values():
            _collecter_refs(valeur, refs)
    elif isinstance(obj, list):
        for element in obj:
            _collecter_refs(element, refs)


class Command(BaseCommand):
    help = "Liste les LienReference et leurs usages dans les blocs riches"

    def add_arguments(self, parser):
        parser.add_argument(
            "--usages",
            action="store_true",
            help="Scanne les blocs riches pour lister les objets référents.",
        )

    def handle(self, *args, **options):
        from envergo.nitrates.models import (
            CodePrescription,
            ContenuRichDSFR,
            LienReference,
        )

        liens = {lr.identifiant: lr for lr in LienReference.objects.all()}
        if not options.get("usages"):
            for lr in liens.values():
                self.stdout.write(f"{lr.identifiant} → {lr.url}")
            self.stdout.write(self.style.SUCCESS(f"{len(liens)} lien(s)."))
            return

        usages = {}  # identifiant lien -> [labels des objets référents]
        sources = [
            ("PC", CodePrescription.objects.exclude(blocs__isnull=True)),
            ("ContenuRich", ContenuRichDSFR.objects.all()),
        ]
        for genre, qs in sources:
            for obj in qs:
                refs = set()
                _collecter_refs(obj.blocs, refs)
                for ref in refs:
                    label = getattr(obj, "identifiant", None) or getattr(
                        obj, "cle", obj.pk
                    )
                    usages.setdefault(ref, []).append(f"{genre}:{label}")

        for ident, lr in liens.items():
            referents = sorted(usages.pop(ident, []))
            etat = ", ".join(referents) if referents else "AUCUN USAGE"
            self.stdout.write(f"{ident} → {lr.url}\n    {etat}")
        for ident, referents in sorted(usages.items()):
            self.stdout.write(
                self.style.ERROR(
                    f"{ident} → ORPHELIN (absent de LienReference)\n"
                    f"    {', '.join(sorted(referents))}"
                )
            )
        self.stdout.write(self.style.SUCCESS(f"{len(liens)} lien(s)."))
