"""Exporte le manifeste JSON des feuilles ZAR Grand Est à capturer (Playwright).

Pendant de `export_manifeste_capture_couvert`, mais cible l'arbre ZAR Grand
Est : enumere les feuilles culture principale ET couvert de l'arbre ZAR,
indexe les BrancheValidation par `scope=zar_grand_est`, et ajoute le tree_id
ZAR pour le deeplink YAML viewer (sinon le viewer ouvre l'arbre national).

Sortie : `e2e/nitrates/_capture_zar_manifeste.json`.

Chaque entree :
  - `pk`       : BrancheValidation ZAR (nommage PNG + ingest par pk)
  - `regle_id` : id de regle (deeplink viewer `?tree_id=<pk>#regle=<id>`)
  - `url`      : deeplink simulateur pre-rempli
  - `tree_id`  : pk de l'arbre ZAR (viewer)
  - `qc`       : valeurs des questions complementaires (champ -> valeur),
                 derivees du contexte de la feuille + `en_zar=True` (la
                 resolution GPS peut poser la QC ZAR explicitement).

Usage :
    python manage.py export_manifeste_capture_zar
    python manage.py export_manifeste_capture_zar --out /chemin.json
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from envergo.nitrates.models import BrancheValidation, DecisionTree
from envergo.nitrates.yaml_tree.feuilles import (
    enumerer_feuilles_couvert_v2,
    enumerer_feuilles_culture_principale_v2,
)

# Champs du contexte qui ne sont PAS des reponses de QC (resolus serveur /
# deja dans l'URL).
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


def _charger_tree_zar():
    zar = (
        DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE)
        .filter(name__icontains="ZAR")
        .order_by("-pk")
        .first()
    )
    if zar is None:
        raise CommandError("Aucun arbre actif 'ZAR'.")
    return zar


class Command(BaseCommand):
    help = "Exporte le manifeste JSON des feuilles ZAR Grand Est pour la capture e2e."

    def add_arguments(self, parser):
        parser.add_argument(
            "--out",
            default=str(Path(".") / "e2e" / "nitrates" / "_capture_zar_manifeste.json"),
        )

    def handle(self, *args, **opts):
        tree = _charger_tree_zar()
        arbre = tree.contenu
        feuilles = enumerer_feuilles_culture_principale_v2(
            arbre
        ) + enumerer_feuilles_couvert_v2(arbre)

        pk_par_chemin = {
            b.chemin_yaml: b.pk
            for b in BrancheValidation.objects.filter(
                scope=BrancheValidation.SCOPE_ZAR_GRAND_EST
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
            # La resolution GPS d'un point ZAR peut poser la QC `en_zar`.
            qc.setdefault("en_zar", "True")
            manifeste.append(
                {
                    "pk": pk,
                    "regle_id": f["regle_id"] or "",
                    "url": b.url_simulateur,
                    "tree_id": tree.pk,
                    "qc": qc,
                }
            )

        out = Path(opts["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(manifeste, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        msg = f"{len(manifeste)} feuilles ZAR -> {out}"
        if manquantes:
            msg += f" ({manquantes} sans BrancheValidation, ignorees — re-seeder ?)"
        self.stdout.write(self.style.SUCCESS(msg))
