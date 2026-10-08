"""Provisionne les PC du PAR Bretagne modifié (arrêté du 28/08/2026).

Source : `specs/pc_bretagne.json`, exporté de la base où les PC ont été
rédigées. Deux familles, toutes en scope region / region_code 53 :

  - déclinaisons de PC nationales (`variante_de`) : pc6_bzh (note 2 de
    l'annexe 6), pc7_bzh (note 3) ; résolues automatiquement à la place de
    pc6 / pc7 pour une parcelle bretonne, y compris sur une feuille du PAN ;
  - PC régionales autonomes, référencées directement par l'arbre région 53 :
    pc_bzh_derobees, pc_bzh_prairie_aut_sept, pc_bzh_cine_type_i,
    pc_bzh_mais_semis, pc_bzh_mais_z1, pc_bzh_mais_z2.

Sans effet hors Bretagne. Avec l'import de l'arbre en revue
`specs/arbres_en_revue/region_53.yaml`, c'est ce qui allume le PAR Bretagne
sur un environnement :

    python manage.py provisionner_pc_bretagne
    python manage.py import_decision_tree \
        envergo/nitrates/specs/arbres_en_revue/region_53.yaml \
        --scope region --region-code 53 --mode force-active --name "PAR Bretagne"

Ni le déploiement de code, ni seed_referentiels, ni load_arbres_actifs (CI,
e2e) ne le font : le PAR Bretagne ne pèse sur aucun autre environnement tant
qu'il est en revue. Le promouvoir = déplacer l'arbre dans arbres_actifs/ et
les PC dans la fixture référentiels.

Idempotent : une PC existante n'est pas retouchée (les juristes peuvent la
réécrire dans l'admin), sauf avec --maj.

Usage :
    python manage.py provisionner_pc_bretagne --dry-run
    python manage.py provisionner_pc_bretagne
    python manage.py provisionner_pc_bretagne --maj
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from envergo.nitrates.models_referentiels import CodePrescription

SOURCE = "pc_bretagne.json"
CHAMPS = (
    "scope",
    "region_code",
    "plafond",
    "mots_cles",
    "texte_court",
    "texte_redaction_initiale",
    "blocs",
)


class Command(BaseCommand):
    help = "Crée les PC du PAR Bretagne modifié (scope region 53)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--maj",
            action="store_true",
            help="Met aussi à jour les PC déjà présentes (écrase les retouches admin).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        chemin = Path(settings.NITRATES_SPECS_DIR) / SOURCE
        if not chemin.exists():
            raise CommandError(f"Source introuvable : {chemin}")
        pcs = json.loads(chemin.read_text(encoding="utf-8"))

        crees = maj = inchangees = 0
        for pc in pcs:
            base = pc.get("variante_de")
            variante_de = None
            if base:
                variante_de = CodePrescription.objects.filter(identifiant=base).first()
                if variante_de is None:
                    raise CommandError(
                        f"{pc['identifiant']} : PC de base {base} absente."
                    )
            valeurs = {k: pc[k] for k in CHAMPS}
            valeurs["variante_de"] = variante_de

            existante = CodePrescription.objects.filter(
                identifiant=pc["identifiant"]
            ).first()
            if existante and not options["maj"]:
                inchangees += 1
                self.stdout.write(f"  = {pc['identifiant']} (déjà présente)")
                continue
            if options["dry_run"]:
                self.stdout.write(
                    f"  {'~' if existante else '+'} {pc['identifiant']} (dry-run)"
                )
                continue
            CodePrescription.objects.update_or_create(
                identifiant=pc["identifiant"], defaults=valeurs
            )
            if existante:
                maj += 1
                self.stdout.write(f"  ~ {pc['identifiant']} mise à jour")
            else:
                crees += 1
                self.stdout.write(f"  + {pc['identifiant']} créée")

        self.stdout.write(
            self.style.SUCCESS(
                f"PC Bretagne : {crees} créée(s), {maj} mise(s) à jour, "
                f"{inchangees} inchangée(s). Redémarrer le web (cache référentiels)."
            )
        )
