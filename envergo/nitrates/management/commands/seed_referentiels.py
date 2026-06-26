"""Commande de seed idempotente : populle les 7 tables référentiel
depuis `envergo/nitrates/specs/referentiels.yaml` (cf. carte #61).

Idempotente : utilisable au déploiement, en local pour reset, en CI.
Chaque entité est créée ou mise à jour via `update_or_create` sur
l'identifiant slug.

Usage :
    python manage.py seed_referentiels
    python manage.py seed_referentiels --yaml /chemin/vers/autre.yaml
    python manage.py seed_referentiels --dry-run    # n'écrit rien

Comportement :
  1. GroupeCultureUI (depuis `categories_cultures` du YAML legacy)
  2. BrancheCulturale (déduit depuis `mapping_sous_culture_vers_branche`)
  3. Culture (depuis `sous_cultures` + `mapping_sous_culture_vers_branche`)
  4. Fertilisant (depuis `sous_fertilisants` + `categories_fertilisants`
     + `mapping_sous_fertilisant_vers_type`)
  5. NoteReglementaire (depuis `notes`)
  6. CodePrescription (depuis `codes_prescription`, avec FK vers Notes)
  7. EvenementPhenologique (depuis `evenements_phenologiques`)

Note : le doublon `brunissement_soies` / `brunissement_des_soies` est
résolu en gardant uniquement `brunissement_des_soies` (le slug
référencé dans l'arbre).
"""

from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from envergo.nitrates.models import (
    BrancheCulturale,
    CodePrescription,
    Culture,
    EvenementPhenologique,
    Fertilisant,
    GroupeCultureUI,
    NoteReglementaire,
)


class Command(BaseCommand):
    help = "Seed idempotent des référentiels DB depuis referentiels.yaml"

    def add_arguments(self, parser):
        parser.add_argument(
            "--yaml",
            type=str,
            default=None,
            help="Chemin vers referentiels.yaml (defaut: NITRATES_SPECS_DIR).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche ce qui serait fait sans écrire en base.",
        )

    def handle(self, *args, **options):
        yaml_path = options.get("yaml") or (
            Path(settings.NITRATES_SPECS_DIR) / "referentiels.yaml"
        )
        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            self.stderr.write(self.style.ERROR(f"YAML introuvable : {yaml_path}"))
            return

        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)

        dry_run = options.get("dry_run", False)

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — aucune écriture."))

        # On enveloppe dans une transaction pour atomicité.
        with transaction.atomic():
            stats = self._seed(data)
            if dry_run:
                transaction.set_rollback(True)

        for entity, (created, updated) in stats.items():
            self.stdout.write(f"{entity}: {created} créé(s), {updated} mis à jour")
        self.stdout.write(self.style.SUCCESS("Seed terminé."))

    def _seed(self, data: dict) -> dict[str, tuple[int, int]]:
        """Retourne un dict {entity_name: (created_count, updated_count)}."""
        stats = {}

        # 1. Catégories de culture
        stats["GroupeCultureUI"] = self._seed_categories_culture(data)
        # 2. Branches culturales (déduit du mapping)
        stats["BrancheCulturale"] = self._seed_branches_culturales(data)
        # 3. Cultures (avec FK GroupeCultureUI + BrancheCulturale)
        stats["Culture"] = self._seed_cultures(data)
        # 4. Fertilisants (catégorie en choices, type depuis mapping)
        stats["Fertilisant"] = self._seed_fertilisants(data)
        # 5. Notes réglementaires
        stats["NoteReglementaire"] = self._seed_notes(data)
        # 6. Codes prescription (avec FK Note optionnelle)
        stats["CodePrescription"] = self._seed_codes_prescription(data)
        # 7. Événements phénologiques
        stats["EvenementPhenologique"] = self._seed_evenements_phenologiques(data)

        return stats

    # ─── 1. Catégories de culture ────────────────────────────────────────────

    def _seed_categories_culture(self, data: dict) -> tuple[int, int]:
        created = updated = 0
        for idx, (identifiant, meta) in enumerate(
            (data.get("categories_cultures") or {}).items()
        ):
            defaults = {
                "libelle_public": meta.get("libelle_public", identifiant),
                "ordre_affichage": idx,
            }
            # cas particulier sol_non_cultive : pré-remplit occupation_sol
            if identifiant == "sol_non_cultive":
                defaults["champs_prefill"] = {"occupation_sol": "sol_non_cultive"}
            obj, was_created = GroupeCultureUI.objects.update_or_create(
                identifiant=identifiant, defaults=defaults
            )
            if was_created:
                created += 1
            else:
                updated += 1
        return created, updated

    # ─── 2. Branches culturales (déduit) ─────────────────────────────────────

    def _seed_branches_culturales(self, data: dict) -> tuple[int, int]:
        """Les BrancheCulturale ne sont pas listées explicitement dans le YAML
        actuel. On les déduit de `mapping_sous_culture_vers_branche` :
        chaque valeur unique de `sous_culture` (niveau 2 arbre) devient une
        BrancheCulturale.

        Depuis l'aplatissement des couverts (spec_refactor_couverts_remontee_branches),
        les variantes cie/cine sont directement la valeur `sous_culture` du
        mapping — plus de dérivation via `flags.sous_culture_couvert`.
        """
        mapping = data.get("mapping_sous_culture_vers_branche") or {}
        identifiants = set()
        for entry in mapping.values():
            sc = entry.get("sous_culture")
            if sc:
                identifiants.add(sc)

        created = updated = 0
        for idx, ident in enumerate(sorted(identifiants)):
            obj, was_created = BrancheCulturale.objects.update_or_create(
                identifiant=ident,
                defaults={
                    "libelle_court": ident.replace("_", " "),
                    "ordre_affichage": idx,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
        return created, updated

    # ─── 3. Cultures ─────────────────────────────────────────────────────────

    def _seed_cultures(self, data: dict) -> tuple[int, int]:
        sous_cultures = data.get("sous_cultures") or {}
        mapping = data.get("mapping_sous_culture_vers_branche") or {}
        categories_cultures = data.get("categories_cultures") or {}

        # Pour chaque sous-culture, trouver sa catégorie parent (clé inversée)
        # depuis `categories_cultures[cat].sous_cultures`.
        sc_to_cat = {}
        cat_ordre = {}
        for cat_id, cat_meta in categories_cultures.items():
            for sc_id in cat_meta.get("sous_cultures") or []:
                sc_to_cat[sc_id] = cat_id
                cat_ordre[sc_id] = (cat_meta.get("sous_cultures") or []).index(sc_id)

        created = updated = 0
        for ident, meta in sous_cultures.items():
            cat_id = sc_to_cat.get(ident)
            if not cat_id:
                self.stderr.write(
                    self.style.WARNING(
                        f"Culture {ident} sans catégorie parent dans "
                        f"categories_cultures — skip"
                    )
                )
                continue
            cat = GroupeCultureUI.objects.get(identifiant=cat_id)

            # Mapping vers branche d'arbre + flags
            map_entry = mapping.get(ident, {})
            sc_branche_ident = map_entry.get("sous_culture", ident)
            occupation_sol = map_entry.get("occupation_sol", "culture_principale")
            flags = map_entry.get("flags") or {}

            # Construction champs_prefill (les flags)
            champs_prefill = {}
            for k, v in flags.items():
                champs_prefill[k] = v

            try:
                branche = BrancheCulturale.objects.get(identifiant=sc_branche_ident)
            except BrancheCulturale.DoesNotExist:
                # Cas rare : la branche n'a pas été créée (sous_culture
                # absent du mapping). On la crée à la volée.
                branche = BrancheCulturale.objects.create(
                    identifiant=sc_branche_ident,
                    libelle_court=sc_branche_ident.replace("_", " "),
                )

            obj, was_created = Culture.objects.update_or_create(
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
            if was_created:
                created += 1
            else:
                updated += 1
        return created, updated

    # ─── 4. Fertilisants ─────────────────────────────────────────────────────

    def _seed_fertilisants(self, data: dict) -> tuple[int, int]:
        sous_fertilisants = data.get("sous_fertilisants") or {}
        categories_fertilisants = data.get("categories_fertilisants") or {}
        mapping = data.get("mapping_sous_fertilisant_vers_type") or {}

        # Pour chaque sous-fertilisant, trouver sa catégorie (clé inversée).
        # NB : un sous-fertilisant peut être listé dans plusieurs catégories
        # dans le YAML (cf. compost_fractions_solides_digestats). On prend la
        # 1re catégorie rencontrée (ordre du fichier).
        sf_to_cat = {}
        sf_ordre = {}
        for cat_id, cat_meta in categories_fertilisants.items():
            for idx, sf_id in enumerate(cat_meta.get("sous_fertilisants") or []):
                if sf_id not in sf_to_cat:
                    sf_to_cat[sf_id] = cat_id
                    sf_ordre[sf_id] = idx

        created = updated = 0
        for ident, meta in sous_fertilisants.items():
            cat_id = sf_to_cat.get(ident)
            if not cat_id:
                self.stderr.write(
                    self.style.WARNING(
                        f"Fertilisant {ident} sans catégorie parent — skip"
                    )
                )
                continue
            type_reg = mapping.get(ident)
            if not type_reg:
                self.stderr.write(
                    self.style.WARNING(
                        f"Fertilisant {ident} sans type réglementaire mappé — skip"
                    )
                )
                continue
            obj, was_created = Fertilisant.objects.update_or_create(
                identifiant=ident,
                defaults={
                    "libelle_public": meta.get("libelle_public", ident),
                    "description": meta.get("description", "").strip(),
                    "categorie": cat_id,
                    "champs_prefill": meta.get("flags") or {},
                    "type_reglementaire": type_reg,
                    "ordre_affichage": sf_ordre.get(ident, 0),
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
        return created, updated

    # ─── 5. Notes ────────────────────────────────────────────────────────────

    def _seed_notes(self, data: dict) -> tuple[int, int]:
        created = updated = 0
        for idx, (ident, meta) in enumerate((data.get("notes") or {}).items()):
            codes_geo = meta.get("codes_geographiques") or {}
            obj, was_created = NoteReglementaire.objects.update_or_create(
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
            if was_created:
                created += 1
            else:
                updated += 1
        return created, updated

    # ─── 6. Codes prescription ───────────────────────────────────────────────

    def _charger_pc_blocs(self) -> dict:
        """Charge le contenu riche des PC (carte #136) depuis pc_blocs.yaml,
        indexé par identifiant. Fichier optionnel : absent -> {} (pas de blocs
        seedés, les PC gardent leur texte legacy)."""
        from pathlib import Path

        from django.conf import settings

        chemin = Path(settings.NITRATES_SPECS_DIR) / "pc_blocs.yaml"
        if not chemin.exists():
            return {}
        with chemin.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("codes_prescription_blocs", {}) or {}

    def _seed_codes_prescription(self, data: dict) -> tuple[int, int]:
        created = updated = 0
        pc_blocs = self._charger_pc_blocs()
        for idx, (ident, meta) in enumerate(
            (data.get("codes_prescription") or {}).items()
        ):
            note = None
            note_ident = meta.get("note_reglementaire")
            if note_ident:
                try:
                    note = NoteReglementaire.objects.get(identifiant=note_ident)
                except NoteReglementaire.DoesNotExist:
                    self.stderr.write(
                        self.style.WARNING(
                            f"CodePrescription {ident} référence note "
                            f"{note_ident} introuvable — note=None"
                        )
                    )

            obj, was_created = CodePrescription.objects.update_or_create(
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
            # Contenu riche (#136) : on pose les blocs transcrits SEULEMENT si le
            # PC n'en a pas déjà -> un re-seed n'écrase pas une édition juriste
            # faite dans l'admin. Le champ texte legacy reste intact dans tous
            # les cas (fallback).
            blocs_source = pc_blocs.get(ident)
            existant = (
                obj.blocs.get("blocs") if isinstance(obj.blocs, dict) else obj.blocs
            )
            if blocs_source and not existant:
                obj.blocs = blocs_source
                obj.save(update_fields=["blocs"])
            if was_created:
                created += 1
            else:
                updated += 1
        return created, updated

    # ─── 7. Événements phénologiques ─────────────────────────────────────────

    def _seed_evenements_phenologiques(self, data: dict) -> tuple[int, int]:
        """Le YAML actuel contient un doublon `brunissement_soies` /
        `brunissement_des_soies`. On garde le slug avec `des` (référencé
        dans l'arbre)."""
        evts = (data.get("evenements_phenologiques") or {}).copy()
        # Suppression du doublon historique
        if "brunissement_soies" in evts and "brunissement_des_soies" in evts:
            evts.pop("brunissement_soies", None)

        created = updated = 0
        for ident, meta in evts.items():
            obj, was_created = EvenementPhenologique.objects.update_or_create(
                identifiant=ident,
                defaults={
                    "libelle_public": meta.get("libelle_public", ident),
                    "date_calendrier": meta.get("date_calendrier", "01/01"),
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
        return created, updated
