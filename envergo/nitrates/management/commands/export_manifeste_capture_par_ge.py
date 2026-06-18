"""Exporte le manifeste JSON des feuilles PAR Grand Est à capturer (Playwright).

Variante régionale de `export_manifeste_capture_couvert` : couvre TOUTES les
feuilles PAR (culture principale ET couvert), filtrées par
`scope=par_grand_est`. Le spec e2e `capture_couvert.spec.ts` lit le même
format de manifeste (pk, regle_id, url, qc).

Sortie par défaut : `e2e/nitrates/_capture_par_ge_manifeste.json`.

Usage :
    python manage.py export_manifeste_capture_par_ge
    python manage.py export_manifeste_capture_par_ge --out /chemin.json
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from envergo.nitrates.management.commands.seed_branches_validation_par_ge import (
    _charger_arbre_par,
)
from envergo.nitrates.models import BrancheValidation
from envergo.nitrates.yaml_tree.feuilles import (
    enumerer_feuilles_couvert_v2,
    enumerer_feuilles_culture_principale_v2,
)

SCOPE = BrancheValidation.SCOPE_PAR_GRAND_EST

# Champs du contexte feuille qui NE sont PAS des réponses de QC (résolus
# côté serveur / déjà dans l'URL), à ne pas pousser comme réponses QC.
NON_QC = {
    "en_zone_vulnerable",
    "occupation_sol",
    "sous_culture",
    "type_fertilisant",
    "zone_note_5",
    "zone_grand_est_1",
    "zone_grand_est_2",
}


def _stringify(v):
    if v is True:
        return "True"
    if v is False:
        return "False"
    return str(v)


class Command(BaseCommand):
    help = (
        "Exporte le manifeste JSON des feuilles PAR (CP + couvert) pour la capture e2e."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--out",
            default=str(
                Path(".") / "e2e" / "nitrates" / "_capture_par_ge_manifeste.json"
            ),
        )

    def handle(self, *args, **opts):
        from envergo.nitrates.models import DecisionTree

        par_tree = (
            DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE)
            .filter(name__icontains="PAR")
            .order_by("-pk")
            .first()
        )
        tree_pk = par_tree.pk if par_tree else None

        arbre, _ = _charger_arbre_par()
        feuilles = enumerer_feuilles_culture_principale_v2(
            arbre
        ) + enumerer_feuilles_couvert_v2(arbre)

        # index chemin_yaml -> pk (scope PAR uniquement).
        pk_par_chemin = {
            b.chemin_yaml: b.pk
            for b in BrancheValidation.objects.filter(scope=SCOPE).only(
                "pk", "chemin_yaml"
            )
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
            regle_id = f["regle_id"] or ""
            # YAML viewer scopé à l'arbre PAR : il y a 3 arbres actifs en DB,
            # le viewer sans tree_id retombe sur le 1er actif (potentiellement
            # national ou ZAR). On force tree_id=<pk PAR> pour que `#regle=`
            # déplie bien le nœud dans le BON arbre.
            yaml_url = ""
            if regle_id and tree_pk:
                yaml_url = (
                    f"/admin/nitrates/arbre-decision/?tree_id={tree_pk}"
                    f"#regle={regle_id}"
                )
            manifeste.append(
                {
                    "pk": pk,
                    "regle_id": regle_id,
                    "url": b.url_simulateur,
                    "yaml_url": yaml_url,
                    "qc": qc,
                }
            )

        out = Path(opts["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(manifeste, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        msg = f"{len(manifeste)} feuilles PAR -> {out}"
        if manquantes:
            msg += f" ({manquantes} sans BrancheValidation, ignorées — re-seeder ?)"
        self.stdout.write(self.style.SUCCESS(msg))
