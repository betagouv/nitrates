# Data migration #147 : remplit la zone d'application des CodePrescription
# existants en parsant leurs identifiants, et normalise la casse.
#
# Conventions constatées en base (import staging, rédactions juristes) :
#   - suffixe `_zar_ge`  -> déclinaison ZAR Grand Est   (scope=zar,    region=44)
#   - suffixe `_ge`      -> déclinaison PAR Grand Est   (scope=region, region=44)
#   - suffixe `_hdf`     -> déclinaison PAR Hauts-de-Fr (scope=region, region=32)
#   - motif `pcA_pcB...` -> fusion des PC composants (pc1_pc12 = pc1 + pc12)
#   - casse incohérente (PC11_ge, PC1_PC12_ZAR_GE...) -> tout en minuscules
#
# `variante_de` n'est posé que si la PC de base (identifiant sans suffixe)
# existe : une PC régionale SANS équivalent national (ex pc_ge, plafond 30 kg
# PAR GE) reste une PC autonome de scope régional, référençable directement
# par une feuille d'arbre régional.
#
# Rejouable et tolérante aux bases vides (CI, envs neufs post-fixture).

import re

from django.db import migrations

# Ordre important : `_zar_ge` AVANT `_ge` (endswith les matche tous les deux).
_SUFFIXES = [
    ("_zar_ge", "zar", "44"),
    ("_ge", "region", "44"),
    ("_hdf", "region", "32"),
]

_FUSION_RE = re.compile(r"^pc\d+(?:_pc\d+)+$")


def remplir_zone_application(apps, schema_editor):
    CodePrescription = apps.get_model("nitrates", "CodePrescription")

    # 1. Normalisation de la casse. L'identifiant est la clef naturelle du
    # seed et la clef du dict référentiel consommé par les templates : on
    # refuse toute collision plutôt que d'écraser silencieusement.
    for pc in CodePrescription.objects.all():
        lower = pc.identifiant.lower()
        if lower == pc.identifiant:
            continue
        if CodePrescription.objects.filter(identifiant=lower).exists():
            raise RuntimeError(
                f"Normalisation impossible : '{pc.identifiant}' et '{lower}' "
                f"coexistent. Fusionner les deux lignes avant de migrer."
            )
        pc.identifiant = lower
        pc.save(update_fields=["identifiant"])

    rows = {pc.identifiant: pc for pc in CodePrescription.objects.all()}

    # 2. Déclinaisons géographiques (suffixe) + rattachement à la base.
    for ident, pc in rows.items():
        for suffix, scope, region_code in _SUFFIXES:
            if not ident.endswith(suffix):
                continue
            pc.scope = scope
            pc.region_code = region_code
            stem = ident[: -len(suffix)]
            base = rows.get(stem)
            # Garde-fou chaîne : si la "base" est elle-même une déclinaison
            # (impossible avec les conventions actuelles), on ne pointe pas.
            if base is not None and base.variante_de_id is None and base is not pc:
                pc.variante_de = base
            pc.save(update_fields=["scope", "region_code", "variante_de"])
            break

    # 3. Fusions : les PC de base au motif pcA_pcB portent leurs composants.
    # Les déclinaisons de fusion (pc1_pc12_ge...) passent par variante_de,
    # posé à l'étape 2 (stem = la fusion de base).
    for ident, pc in rows.items():
        if not _FUSION_RE.match(ident):
            continue
        parts = ident.split("_")
        if any(part not in rows for part in parts):
            # Composant manquant en base : on ne pose pas une fusion partielle.
            continue
        pc.composants_fusion.set([rows[part] for part in parts])


def noop(apps, schema_editor):
    # La normalisation de casse et le remplissage ne sont pas inversés : les
    # champs disparaissent avec la migration de schéma, et la casse d'origine
    # n'a pas de valeur métier.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("nitrates", "0029_codeprescription_zone_application"),
    ]

    operations = [
        migrations.RunPython(remplir_zone_application, noop),
    ]
