"""Seed initial historique des référentiels au déploiement.

Best-effort : si la source de seed est introuvable, on log et on no-op.
Cette migration a été appliquée sur les bases existantes (prod/staging/dev)
quand elle lisait `referentiels.yaml`. Depuis #226 ce YAML a été supprimé
au profit d'une fixture (`fixtures/initial_referentiels.json`) chargée par
la commande `seed_referentiels`. Sur une base à jour cette migration ne se
rejoue pas ; sur une base neuve elle no-op (YAML absent) et le seed se fait
via `python manage.py seed_referentiels`. Le corps est laissé intact (avec
son garde `exists()`) pour ne pas altérer l'historique de migration.
"""

import sys
from pathlib import Path

import yaml
from django.conf import settings
from django.db import migrations


def forwards(apps, schema_editor):
    """Appelle la logique de seed via les modèles historiques.

    On ne peut pas importer la commande directement (elle utilise les
    modèles "courants" qui pourraient avoir évolué), donc on reproduit
    la logique minimale ici en s'appuyant sur `apps.get_model`.
    """
    yaml_path = Path(settings.NITRATES_SPECS_DIR) / "referentiels.yaml"
    if not yaml_path.exists():
        sys.stderr.write(
            f"[migration nitrates 0012] {yaml_path} introuvable (attendu "
            f"depuis #226), seed initial sauté. Peupler via "
            f"`python manage.py seed_referentiels` (fixture).\n"
        )
        return

    with yaml_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    CategorieCulture = apps.get_model("nitrates", "CategorieCulture")
    BrancheCulturale = apps.get_model("nitrates", "BrancheCulturale")
    Culture = apps.get_model("nitrates", "Culture")
    Fertilisant = apps.get_model("nitrates", "Fertilisant")
    NoteReglementaire = apps.get_model("nitrates", "NoteReglementaire")
    CodePrescription = apps.get_model("nitrates", "CodePrescription")
    EvenementPhenologique = apps.get_model("nitrates", "EvenementPhenologique")

    # 1. Catégories de culture
    for idx, (ident, meta) in enumerate(
        (data.get("categories_cultures") or {}).items()
    ):
        defaults = {
            "libelle_public": meta.get("libelle_public", ident),
            "ordre_affichage": idx,
        }
        if ident == "sol_non_cultive":
            defaults["champs_prefill"] = {"occupation_sol": "sol_non_cultive"}
        CategorieCulture.objects.update_or_create(identifiant=ident, defaults=defaults)

    # 2. Branches culturales (déduit du mapping)
    mapping = data.get("mapping_sous_culture_vers_branche") or {}
    identifiants = set()
    for entry in mapping.values():
        sc = entry.get("sous_culture")
        if sc:
            identifiants.add(sc)
        flags = entry.get("flags") or {}
        scc = flags.get("sous_culture_couvert")
        if scc:
            identifiants.add(scc)
    for idx, ident in enumerate(sorted(identifiants)):
        BrancheCulturale.objects.update_or_create(
            identifiant=ident,
            defaults={
                "libelle_court": ident.replace("_", " "),
                "ordre_affichage": idx,
            },
        )

    # 3. Cultures
    sous_cultures = data.get("sous_cultures") or {}
    categories_cultures = data.get("categories_cultures") or {}
    sc_to_cat = {}
    cat_ordre = {}
    for cat_id, cat_meta in categories_cultures.items():
        for sc_id in cat_meta.get("sous_cultures") or []:
            sc_to_cat[sc_id] = cat_id
            cat_ordre[sc_id] = (cat_meta.get("sous_cultures") or []).index(sc_id)
    for ident, meta in sous_cultures.items():
        cat_id = sc_to_cat.get(ident)
        if not cat_id:
            continue
        cat = CategorieCulture.objects.get(identifiant=cat_id)
        map_entry = mapping.get(ident, {})
        sc_branche_ident = map_entry.get("sous_culture", ident)
        occupation_sol = map_entry.get("occupation_sol", "culture_principale")
        flags = map_entry.get("flags") or {}
        champs_prefill = dict(flags)

        branche, _ = BrancheCulturale.objects.get_or_create(
            identifiant=sc_branche_ident,
            defaults={"libelle_court": sc_branche_ident.replace("_", " ")},
        )
        Culture.objects.update_or_create(
            identifiant=ident,
            defaults={
                "libelle_public": meta.get("libelle_public", ident),
                "categorie": cat,
                "branche_culturale": branche,
                "occupation_sol": occupation_sol,
                "champs_prefill": champs_prefill,
                "ordre_affichage": cat_ordre.get(ident, 0),
            },
        )

    # 4. Fertilisants
    sous_fertilisants = data.get("sous_fertilisants") or {}
    categories_fertilisants = data.get("categories_fertilisants") or {}
    mapping_sf = data.get("mapping_sous_fertilisant_vers_type") or {}
    sf_to_cat = {}
    sf_ordre = {}
    for cat_id, cat_meta in categories_fertilisants.items():
        for idx, sf_id in enumerate(cat_meta.get("sous_fertilisants") or []):
            if sf_id not in sf_to_cat:
                sf_to_cat[sf_id] = cat_id
                sf_ordre[sf_id] = idx
    for ident, meta in sous_fertilisants.items():
        cat_id = sf_to_cat.get(ident)
        type_reg = mapping_sf.get(ident)
        if not cat_id or not type_reg:
            continue
        Fertilisant.objects.update_or_create(
            identifiant=ident,
            defaults={
                "libelle_public": meta.get("libelle_public", ident),
                "description": (meta.get("description") or "").strip(),
                "categorie": cat_id,
                "type_reglementaire": type_reg,
                "ordre_affichage": sf_ordre.get(ident, 0),
            },
        )

    # 5. Notes
    for idx, (ident, meta) in enumerate((data.get("notes") or {}).items()):
        codes_geo = meta.get("codes_geographiques") or {}
        NoteReglementaire.objects.update_or_create(
            identifiant=ident,
            defaults={
                "libelle_court": meta.get("libelle_court", ident),
                "condition_declenchement": (
                    meta.get("condition_declenchement") or ""
                ).strip(),
                "regions_concernees": codes_geo.get("regions") or [],
                "departements_concernes": codes_geo.get("departements") or [],
                "ordre_affichage": idx,
            },
        )

    # 6. Codes prescription
    for idx, (ident, meta) in enumerate(
        (data.get("codes_prescription") or {}).items()
    ):
        note = None
        note_ident = meta.get("note_reglementaire")
        if note_ident:
            note = NoteReglementaire.objects.filter(identifiant=note_ident).first()
        CodePrescription.objects.update_or_create(
            identifiant=ident,
            defaults={
                "mots_cles": meta.get("mots_cles", ""),
                "texte_court": (meta.get("texte_court") or "").strip(),
                "texte_redaction_initiale": (
                    meta.get("texte_redaction_initiale") or ""
                ).strip(),
                "toujours_affiche": meta.get("toujours_affiche", False),
                "note_reglementaire": note,
                "ordre_affichage": idx,
            },
        )

    # 7. Événements phénologiques (dédoublonnage brunissement)
    evts = (data.get("evenements_phenologiques") or {}).copy()
    if "brunissement_soies" in evts and "brunissement_des_soies" in evts:
        evts.pop("brunissement_soies", None)
    for ident, meta in evts.items():
        EvenementPhenologique.objects.update_or_create(
            identifiant=ident,
            defaults={
                "libelle_public": meta.get("libelle_public", ident),
                "date_calendrier": meta.get("date_calendrier", "01/01"),
            },
        )


def reverse(apps, schema_editor):
    """Suppression complète au reverse (les modèles sont conservés)."""
    for model_name in (
        "EvenementPhenologique",
        "CodePrescription",
        "NoteReglementaire",
        "Fertilisant",
        "Culture",
        "BrancheCulturale",
        "CategorieCulture",
    ):
        apps.get_model("nitrates", model_name).objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("nitrates", "0011_referentiels_db"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse),
    ]
