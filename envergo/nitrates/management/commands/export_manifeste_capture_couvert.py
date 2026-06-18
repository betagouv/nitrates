"""Exporte le manifeste JSON des feuilles couvert à capturer en Playwright.

Le spec e2e `e2e/nitrates/capture_couvert.spec.ts` lit ce fichier pour
savoir, par feuille :
  - `pk`        : la BrancheValidation cible (pour nommer le PNG et l'ingest)
  - `regle_id`  : l'id de règle (deeplink YAML viewer `#regle=<id>`)
  - `url`       : le deeplink simulateur pré-rempli
  - `qc`        : les valeurs à donner aux questions complémentaires si le
                  simulateur les pose encore (champ -> valeur, depuis le
                  contexte de la feuille). Le spec ne répond une QC que si
                  elle apparaît dans le DOM ; ce dict est la source de vérité
                  des réponses.

Sortie par défaut : `e2e/nitrates/_capture_couvert_manifeste.json`
(à la racine du repo). Régénérable à tout moment ; non versionné.

Usage :
    python manage.py export_manifeste_capture_couvert
    python manage.py export_manifeste_capture_couvert --out /chemin.json
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from envergo.nitrates.management.commands.seed_branches_validation_couvert import (
    _charger_arbre_national,
)
from envergo.nitrates.models import BrancheValidation
from envergo.nitrates.yaml_tree.feuilles import enumerer_feuilles_couvert_v2

# Champs du contexte feuille qui NE sont PAS des réponses de QC (résolus
# côté serveur / déjà dans l'URL), à ne pas pousser comme réponses QC.
NON_QC = {
    "en_zone_vulnerable",
    "occupation_sol",
    "sous_culture",
    "type_fertilisant",
    "zone_note_5",
}


def _stringify(v):
    if v is True:
        return "True"
    if v is False:
        return "False"
    return str(v)


class Command(BaseCommand):
    help = "Exporte le manifeste JSON des feuilles couvert pour la capture e2e."

    def add_arguments(self, parser):
        parser.add_argument(
            "--out",
            default=str(
                Path(".") / "e2e" / "nitrates" / "_capture_couvert_manifeste.json"
            ),
        )
        parser.add_argument(
            "--only-courte",
            action="store_true",
            help="Ne garde que les feuilles couvert COURTE (cie/cine courte).",
        )

    def handle(self, *args, **opts):
        arbre, _ = _charger_arbre_national()
        feuilles = enumerer_feuilles_couvert_v2(arbre)
        if opts["only_courte"]:
            feuilles = [
                f for f in feuilles if "courte" in "/".join(f["chemin_ids"]).lower()
            ]
        # index chemin_yaml -> pk
        pk_par_chemin = {
            b.chemin_yaml: b.pk
            for b in BrancheValidation.objects.filter(
                chemin_yaml__contains="q_couvert_sous_culture"
            ).only("pk", "chemin_yaml")
        }

        manifeste = []
        manquantes = 0
        for f in feuilles:
            chemin = "/".join(f["chemin_ids"])
            pk = pk_par_chemin.get(chemin)
            if pk is None:
                manquantes += 1
                continue
            b = BrancheValidation.objects.only("url_simulateur").get(pk=pk)
            qc = {k: _stringify(v) for k, v in f["contexte"].items() if k not in NON_QC}
            manifeste.append(
                {
                    "pk": pk,
                    "regle_id": f["regle_id"] or "",
                    "url": b.url_simulateur,
                    "qc": qc,
                }
            )

        out = Path(opts["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(manifeste, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        msg = f"{len(manifeste)} feuilles -> {out}"
        if manquantes:
            msg += f" ({manquantes} sans BrancheValidation, ignorées — re-seeder ?)"
        self.stdout.write(self.style.SUCCESS(msg))
