"""Provisionne les déclinaisons Hauts-de-France des PC « suivi reliquats »
(#467 / #254).

L'arbre PAR HdF n'explicite que pc11 : tout le reste vient du PAN. Les PC
qui surfacent réellement en HdF dans la famille « dispositif de suivi des
reliquats » sont pc1, pc3, pc4, pc10 et les fusions pc1_pc12, pc1_pc13,
pc2_pc12, pc2_pc13 (pc2 seule ne sort jamais, et les fusions pc1_pc14/16,
pc2_pc14 sont propres à l'arbre Grand Est). On ne crée QUE celles-là.

Chaque déclinaison = clone des blocs de la PC de base + lien syndiqué vers
l'annexe 1 du PAR HdF (LienReference), inséré en parenthèse sur les items
« dispositif de surveillance/suivi ... », comme côté Grand Est. Résolution
runtime automatique via variante_de + scope region + region_code 32.

Idempotent : une déclinaison existante n'est pas retouchée.

Usage :
    python manage.py provisionner_pc_hdf_467
    python manage.py provisionner_pc_hdf_467 --dry-run
"""

import copy
import re

from django.core.management.base import BaseCommand

REF_ANNEXE_HDF = "par-hdf-annexe1-reliquats"
LIEN_HDF = {
    "url": "/static/nitrates/documents/par-hdf-annexe1-reliquats-et-definitions.pdf",
    "libelle": "consultez l'annexe 1 du PAR Hauts-de-France (PDF)",
    "description": (
        "Annexe 1 du PAR Hauts-de-France : modalités de réalisation et de "
        "transmission des reliquats azotés + définitions des notes 1, 2, 3 "
        "et 12 du calendrier PAN. Référencée par les PC 1-4 et 10 déclinées "
        "HdF (#467/#254)."
    ),
}

BASES = [
    "pc1",
    "pc3",
    "pc4",
    "pc10",
    "pc1_pc12",
    "pc1_pc13",
    "pc2_pc12",
    "pc2_pc13",
]

REGION_HDF = "32"

# Items porteurs du dispositif : on leur accroche la parenthèse + lien.
_MOTIF_DISPOSITIF = re.compile(
    r"dispositif de (surveillance|suivi) des "
    r"(teneurs en azote nitrique et ammoniacal|reliquats azotés)"
)

_PREFIXE_PARENTHESE = (
    " (pour connaître le dispositif de suivi à mettre en place " "en Hauts-de-France, "
)


def _inserer_lien(texte):
    """string d'item -> segments avec lien HdF, ou None si pas concerné."""
    if not _MOTIF_DISPOSITIF.search(texte):
        return None
    corps, point = texte, ""
    if corps.rstrip().endswith("."):
        corps = corps.rstrip()[:-1]
        point = "."
    return [
        {"texte": corps + _PREFIXE_PARENTHESE},
        {"texte": LIEN_HDF["libelle"], "lien_ref": REF_ANNEXE_HDF},
        {"texte": ")" + point},
    ]


def _walk(obj):
    compteur = 0
    if isinstance(obj, dict):
        texte = obj.get("texte")
        if isinstance(texte, str):
            segments = _inserer_lien(texte)
            if segments:
                obj["texte"] = segments
                compteur += 1
        # Ne pas redescendre dans `texte` : les segments qu'on vient de poser
        # contiennent encore le motif et re-matcheraient à l'infini.
        for cle, valeur in obj.items():
            if cle != "texte":
                compteur += _walk(valeur)
    elif isinstance(obj, list):
        for element in obj:
            compteur += _walk(element)
    return compteur


class Command(BaseCommand):
    help = "Crée les PC déclinées Hauts-de-France avec lien annexe 1 (#467/#254)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        from envergo.nitrates.constants import SCOPE_REGION
        from envergo.nitrates.models import CodePrescription, LienReference

        dry_run = options.get("dry_run", False)
        prefix = "[dry-run] " if dry_run else ""

        if not dry_run:
            _, cree = LienReference.objects.get_or_create(
                identifiant=REF_ANNEXE_HDF, defaults=LIEN_HDF
            )
            if cree:
                self.stdout.write(f"LienReference {REF_ANNEXE_HDF} : créé")

        for base_ident in BASES:
            variante_ident = f"{base_ident}_hdf"
            if CodePrescription.objects.filter(identifiant=variante_ident).exists():
                self.stdout.write(f"{prefix}{variante_ident} : existe déjà, ignoré")
                continue
            try:
                base = CodePrescription.objects.get(identifiant=base_ident)
            except CodePrescription.DoesNotExist:
                self.stderr.write(
                    self.style.ERROR(f"{prefix}PC de base absente : {base_ident}")
                )
                continue
            blocs = copy.deepcopy(base.blocs)
            inseres = _walk(blocs)
            if inseres == 0:
                self.stderr.write(
                    self.style.ERROR(
                        f"{prefix}{variante_ident} : aucun item « dispositif de "
                        f"suivi » trouvé dans {base_ident}, non créée"
                    )
                )
                continue
            if not dry_run:
                CodePrescription.objects.create(
                    identifiant=variante_ident,
                    mots_cles=base.mots_cles,
                    texte_court=base.texte_court,
                    texte_redaction_initiale=base.texte_redaction_initiale,
                    blocs=blocs,
                    toujours_affiche=base.toujours_affiche,
                    plafond=base.plafond,
                    ordre_affichage=base.ordre_affichage,
                    note_reglementaire=base.note_reglementaire,
                    scope=SCOPE_REGION,
                    region_code=REGION_HDF,
                    variante_de=base,
                )
            self.stdout.write(
                f"{prefix}{variante_ident} : créée ({inseres} lien(s) inséré(s))"
            )
        self.stdout.write(self.style.SUCCESS(f"{prefix}Terminé."))
