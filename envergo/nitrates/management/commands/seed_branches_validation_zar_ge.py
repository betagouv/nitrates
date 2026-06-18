"""Seed des `BrancheValidation` pour l'arbre ZAR Grand Est (carte #140).

Symetrique des seeds PAN (`seed_branches_validation` /
`seed_branches_validation_couvert`), mais cible l'arbre regional ZAR Grand
Est (Zone d'Actions Renforcees) au lieu du national.

Specificites ZAR :
  - L'arbre actif est desambigue par `name__icontains="ZAR"` (la DB
    partagee multi-agents a plusieurs arbres actifs : national + PAR + ZAR
    → `load_active_tree()` leverait `MultipleObjectsReturned`).
  - La racine de l'arbre ZAR n'est PAS `n_zvn` (national) mais une porte
    « en zone vulnerable » regionale (`n_en_zone_vulnerable`). L'enumerateur
    `feuilles.py` a ete generalise (`_descendre_porte_zvn`) pour la franchir
    quel que soit son id.
  - Pose `scope=zar_grand_est` sur TOUTES les lignes, et la bonne `nature`
    (culture_principale / couvert) selon l'enumeration. Ne touche JAMAIS aux
    lignes national (`scope=national`) ni PAR (`scope=par_grand_est`).

Pour chaque feuille atteignable (culture principale + couvert), cree ou met
a jour une `BrancheValidation` avec UNIQUEMENT les champs derives du YAML :
  - `chemin_yaml`    (cle naturelle, path d'IDs YAML ; prefixe par la racine
                      ZAR donc disjoint des chemins PAN/PAR)
  - `branche_label`  (chemin metier lisible)
  - `url_simulateur` (deeplink pre-rempli, point GPS Grand Est)
  - `yaml_snapshot`  (extrait YAML de la regle, round-trip ruamel)
  - `branche_miro` / `type_fertilisant_miro` (slugs factuels)
  - `ordre`          (tri canonique, CP puis couvert)
  - `scope` / `nature`

VOLONTAIREMENT LAISSES VIDES (saisie / ingest dedie) :
  `resultat_miro`, `miro_widget_id`, `screenshot_miro`, `code_pc_miro`,
  `flag_verif`, `note_verif`, `screenshot_yaml_viewer`,
  `screenshot_playwright`.

N'ECRASE PAS la saisie humaine ni les screenshots sur une ligne existante :
re-runable. Seuls les champs DERIVES (label, url, snapshot, slugs, ordre,
scope, nature) sont recalcules sur update.

Usage :
    python manage.py seed_branches_validation_zar_ge
    python manage.py seed_branches_validation_zar_ge --dry-run
    python manage.py seed_branches_validation_zar_ge --reset
"""

import yaml
from django.core.management.base import BaseCommand, CommandError

from envergo.nitrates.management.commands.seed_branches_validation import (
    _build_url,
    _yaml_snapshot,
)
from envergo.nitrates.models import BrancheValidation, DecisionTree
from envergo.nitrates.yaml_tree.feuilles import (
    enumerer_feuilles_couvert_v2,
    enumerer_feuilles_culture_principale_v2,
)

SCOPE = BrancheValidation.SCOPE_ZAR_GRAND_EST

# Offset d'ordre pour que les lignes ZAR ne collisionnent pas en tri avec le
# PAN. Les chemins_yaml sont deja disjoints (racine ZAR differente), donc
# c'est purement cosmetique pour le tableau.
ORDRE_OFFSET_CP = 2000
ORDRE_OFFSET_COUVERT = 2100


def _charger_arbre_zar():
    """Charge l'arbre ZAR Grand Est par son nom, meme en DB partagee multi
    arbres actifs. Retourne (contenu_json, yaml_brut)."""
    zar = (
        DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE)
        .filter(name__icontains="ZAR")
        .order_by("-pk")
        .first()
    )
    if zar is None:
        raise CommandError(
            "Aucun arbre actif dont le nom contient 'ZAR'. "
            "Active l'arbre ZAR Grand Est avant le seed."
        )
    return zar.contenu, (zar.contenu_yaml_brut or "")


class Command(BaseCommand):
    help = "Seed BrancheValidation pour l'arbre ZAR Grand Est (scope=zar_grand_est)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Supprime d'abord les BrancheValidation ZAR (scope=zar_grand_est).",
        )

    def handle(self, *args, **opts):
        arbre, raw = _charger_arbre_zar()
        try:
            arbre_rt = yaml.safe_load(raw) if raw else arbre
        except Exception:
            arbre_rt = arbre

        feuilles_cp = enumerer_feuilles_culture_principale_v2(arbre)
        feuilles_cv = enumerer_feuilles_couvert_v2(arbre)

        if opts["reset"] and not opts["dry_run"]:
            qs = BrancheValidation.objects.filter(scope=SCOPE)
            n = qs.count()
            qs.delete()
            self.stdout.write(f"Reset ZAR : {n} lignes supprimees.")

        crees = mis_a_jour = 0
        lignes = [
            (feuilles_cp, BrancheValidation.NATURE_CULTURE_PRINCIPALE, ORDRE_OFFSET_CP),
            (feuilles_cv, BrancheValidation.NATURE_COUVERT, ORDRE_OFFSET_COUVERT),
        ]
        for feuilles, nature, ordre_offset in lignes:
            for i, feuille in enumerate(feuilles):
                crees, mis_a_jour = self._upsert(
                    feuille,
                    nature,
                    ordre_offset + i,
                    arbre_rt,
                    opts,
                    crees,
                    mis_a_jour,
                )

        if opts["dry_run"]:
            self.stdout.write(
                f"\n[dry-run] ZAR : {len(feuilles_cp)} culture principale "
                f"+ {len(feuilles_cv)} couvert = "
                f"{len(feuilles_cp) + len(feuilles_cv)} feuilles."
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"OK ZAR : {crees} crees, {mis_a_jour} mis a jour "
                    f"(scope=zar_grand_est, {len(feuilles_cp)} CP + "
                    f"{len(feuilles_cv)} couvert). "
                    f"Total BrancheValidation {BrancheValidation.objects.count()}."
                )
            )

    def _upsert(self, feuille, nature, ordre, arbre_rt, opts, crees, mis_a_jour):
        chemin_yaml = "/".join(feuille["chemin_ids"])
        sous_culture = feuille["contexte"].get("sous_culture", "") or ""
        derives = {
            "branche_label": feuille["label"][:500],
            "url_simulateur": _build_url(feuille["contexte"])[:2000],
            "yaml_snapshot": _yaml_snapshot(arbre_rt, feuille["regle_id"]),
            "branche_miro": sous_culture[:200],
            "type_fertilisant_miro": (
                feuille["contexte"].get("type_fertilisant") or ""
            )[:50],
            "ordre": ordre,
            "scope": SCOPE,
            "nature": nature,
        }

        if opts["dry_run"]:
            self.stdout.write(
                f"[dry-run] {nature:18} {chemin_yaml[-70:]:70} "
                f"{sous_culture}/{derives['type_fertilisant_miro']}"
            )
            return crees, mis_a_jour

        obj = BrancheValidation.objects.filter(chemin_yaml=chemin_yaml).first()
        if obj is None:
            BrancheValidation.objects.create(
                chemin_yaml=chemin_yaml,
                regle_id=feuille["regle_id"] or "",
                **derives,
            )
            return crees + 1, mis_a_jour

        for champ, val in derives.items():
            setattr(obj, champ, val)
        obj.regle_id = feuille["regle_id"] or ""
        obj.save(update_fields=list(derives.keys()) + ["regle_id", "updated_at"])
        return crees, mis_a_jour + 1
