"""Aplatissement des couverts d'interculture (spec_refactor_couverts_remontee_branches).

Avant : les 6 Cultures couvert (couvert_recolte_*, couvert_courte_*) pointaient
vers les BrancheCulturale `interculture_longue` / `interculture_courte`, et la
variante reelle (cie/cine x avant/apres) vivait dans `Culture.champs_prefill`
sous la cle `sous_culture_couvert`.

Apres : `Culture.branche_culturale` pointe directement vers la variante
(cie_avant_3112, cie_apres_0101, cine_avant_3112, cine_apres_0101, cie_courte,
cine_courte), `champs_prefill` vide. Les BrancheCulturale `interculture_*`
deviennent orphelines et sont supprimees, ainsi que d'eventuels doublons de
Culture dont l'identifiant est un slug de variante (artefacts d'experimentation).

Idempotent : rejouable sans effet de bord (update_or_create + filtrage).
Best-effort : si le YAML referentiels est introuvable (CI sans bind-mount),
on no-op proprement -- la commande `seed_referentiels` re-tentera.

Le mapping cible est lu depuis referentiels.yaml (deja aplati) pour rester
la source unique, plutot que de hardcoder ici.
"""

import sys
from pathlib import Path

import yaml
from django.conf import settings
from django.db import migrations

# Identifiants des BrancheCulturale parasites a supprimer en fin de migration.
BRANCHES_OBSOLETES = ["interculture_longue", "interculture_courte"]


def forwards(apps, schema_editor):
    Culture = apps.get_model("nitrates", "Culture")
    BrancheCulturale = apps.get_model("nitrates", "BrancheCulturale")

    yaml_path = Path(settings.NITRATES_SPECS_DIR) / "referentiels.yaml"
    if not yaml_path.exists():
        sys.stderr.write(
            f"[migration nitrates 0015] {yaml_path} introuvable, "
            f"aplatissement couverts saute. Lancer "
            f"`python manage.py seed_referentiels` puis nettoyer manuellement.\n"
        )
        return

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    mapping = data.get("mapping_sous_culture_vers_branche") or {}

    # 1. Remap des Cultures couvert vers la variante (sous_culture du mapping
    #    aplati), champs_prefill vide. On ne touche que les couverts.
    for ident, target in mapping.items():
        if not isinstance(target, dict):
            continue
        if target.get("occupation_sol") != "couvert_intercultures":
            continue
        variante = target.get("sous_culture")
        if not variante:
            continue
        branche, _ = BrancheCulturale.objects.get_or_create(
            identifiant=variante,
            defaults={"libelle_court": variante.replace("_", " ")},
        )
        # update_or_create : si la Culture descriptive existe, on la remappe ;
        # sinon (DB jamais seedee) on ne la cree pas ici (c'est le role du seed).
        Culture.objects.filter(identifiant=ident).update(
            branche_culturale=branche, champs_prefill={}
        )

    # 2. Suppression des Cultures doublons dont l'identifiant EST un slug de
    #    variante (cie_avant_3112, etc.) -- artefacts ou la Culture portait le
    #    meme id que sa branche. Les vraies Cultures gardent l'id descriptif.
    variantes = {
        t.get("sous_culture")
        for t in mapping.values()
        if isinstance(t, dict)
        and t.get("occupation_sol") == "couvert_intercultures"
        and t.get("sous_culture")
    }
    Culture.objects.filter(
        identifiant__in=variantes, occupation_sol="couvert_intercultures"
    ).delete()

    # 3. Suppression des BrancheCulturale obsoletes (orphelines apres remap).
    for ident in BRANCHES_OBSOLETES:
        BrancheCulturale.objects.filter(identifiant=ident).delete()


def backwards(apps, schema_editor):
    """Pas de rollback : l'ancien schema (flag sous_culture_couvert) est
    deprecie. No-op."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("nitrates", "0014_alter_decisiontree_options"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
