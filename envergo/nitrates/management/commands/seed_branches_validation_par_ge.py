"""Seed des `BrancheValidation` pour l'arbre PAR Grand Est (pk actif).

Pendant régional du seed national : parcourt l'arbre **PAR Grand Est**
(Programme d'Actions Régional) actif en DB, énumère TOUTES les feuilles
atteignables sous `culture_principale` ET `couvert_intercultures`, et
crée/met à jour une `BrancheValidation` par feuille avec :

  - `scope = par_grand_est`  (filtre le dashboard, isole du PAN et du ZAR)
  - `nature` = culture_principale | couvert
  - `chemin_yaml`    (clé naturelle, path d'IDs YAML)
  - `branche_label`  (chemin métier lisible)
  - `url_simulateur` (deeplink pré-rempli : point GE + cascade contexte)
  - `yaml_snapshot`  (extrait YAML de la règle, round-trip ruamel)
  - `branche_miro` / `type_fertilisant_miro` (slugs factuels, dérivés YAML)

VOLONTAIREMENT LAISSÉS VIDES (saisie / ingest séparé) :
  `resultat_miro`, `miro_widget_id`, `screenshot_miro`, `code_pc_miro`,
  `screenshot_playwright`, `screenshot_yaml_viewer`, `flag_verif`,
  `note_verif`, `statut`.

Le re-seed ne met à jour QUE les champs dérivés du YAML sur une ligne
existante (cf. `CHAMPS_DERIVES`), il préserve toute la saisie humaine et
les screenshots ingérés. Idempotent. Ne touche JAMAIS aux lignes
`scope=national` ni `scope=zar_grand_est`.

Réutilise les helpers du seed national (`_build_url`, `_yaml_snapshot`)
quand le contexte s'y prête, et l'énumérateur généralisé
`enumerer_feuilles_*_v2` (détection racine ZV par champ, pas par id).

Usage :
    python manage.py seed_branches_validation_par_ge
    python manage.py seed_branches_validation_par_ge --dry-run
    python manage.py seed_branches_validation_par_ge --reset   # PAR scope only
"""

import yaml
from django.core.management.base import BaseCommand

from envergo.nitrates.management.commands.seed_branches_validation import (
    _build_url,
    _yaml_snapshot,
)
from envergo.nitrates.models import BrancheValidation, DecisionTree
from envergo.nitrates.yaml_tree.feuilles import (
    enumerer_feuilles_couvert_v2,
    enumerer_feuilles_culture_principale_v2,
)

SCOPE = BrancheValidation.SCOPE_PAR_GRAND_EST

# Champs dérivés du YAML : recalculés à chaque seed, écrasés même sur une
# ligne existante. Tout le reste (validation + saisie / ingest Miro,
# screenshots) est préservé sur update.
CHAMPS_DERIVES = (
    "branche_label",
    "url_simulateur",
    "yaml_snapshot",
    "branche_miro",
    "type_fertilisant_miro",
    "ordre",
)


def _charger_arbre_par() -> tuple[dict, str]:
    """Charge l'arbre PAR Grand Est actif, même quand plusieurs arbres sont
    actifs en DB partagée (national + PAR + ZAR). On cible explicitement le
    PAR par son nom (équivalent régional de `_charger_arbre_national`), au
    lieu d'un `.get(status='active')` ambigu qui lèverait
    MultipleObjectsReturned.

    Retourne (contenu_json, yaml_brut).
    """
    par = (
        DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE)
        .filter(name__icontains="PAR")
        .order_by("-pk")
        .first()
    )
    if par is None:
        raise RuntimeError("Aucun arbre actif « PAR » trouvé en DB.")
    return par.contenu, (par.contenu_yaml_brut or "")


class Command(BaseCommand):
    help = "Seed BrancheValidation pour l'arbre PAR Grand Est (scope=par_grand_est)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Supprime d'abord les BrancheValidation scope=par_grand_est.",
        )

    def handle(self, *args, **opts):
        arbre, raw = _charger_arbre_par()

        try:
            arbre_rt = yaml.safe_load(raw) if raw else arbre
        except Exception:
            arbre_rt = arbre

        cp = enumerer_feuilles_culture_principale_v2(arbre)
        co = enumerer_feuilles_couvert_v2(arbre)
        # Liste (feuille, nature) ordonnée : CP d'abord, couvert ensuite.
        feuilles = [(f, BrancheValidation.NATURE_CULTURE_PRINCIPALE) for f in cp] + [
            (f, BrancheValidation.NATURE_COUVERT) for f in co
        ]

        if opts["reset"] and not opts["dry_run"]:
            qs = BrancheValidation.objects.filter(scope=SCOPE)
            n = qs.count()
            qs.delete()
            self.stdout.write(f"Reset PAR : {n} lignes supprimées.")

        crees = mis_a_jour = 0
        for ordre, (feuille, nature) in enumerate(feuilles):
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
            }

            if opts["dry_run"]:
                self.stdout.write(
                    f"[dry-run] {nature[:3]} {chemin_yaml[-70:]:70} "
                    f"{sous_culture}/{derives['type_fertilisant_miro']}"
                )
                continue

            # Clé naturelle = (scope, chemin_yaml) : un même chemin_yaml peut
            # exister dans plusieurs arbres ; on isole par scope.
            obj = BrancheValidation.objects.filter(
                scope=SCOPE, chemin_yaml=chemin_yaml
            ).first()
            if obj is None:
                BrancheValidation.objects.create(
                    scope=SCOPE,
                    chemin_yaml=chemin_yaml,
                    regle_id=feuille["regle_id"] or "",
                    nature=nature,
                    **derives,
                )
                crees += 1
            else:
                for champ in CHAMPS_DERIVES:
                    setattr(obj, champ, derives[champ])
                obj.regle_id = feuille["regle_id"] or ""
                obj.nature = nature
                obj.save(
                    update_fields=list(CHAMPS_DERIVES)
                    + ["regle_id", "nature", "updated_at"]
                )
                mis_a_jour += 1

        if opts["dry_run"]:
            self.stdout.write(
                f"\n[dry-run] PAR : {len(cp)} CP + {len(co)} couvert "
                f"= {len(feuilles)} feuilles."
            )
        else:
            total_par = BrancheValidation.objects.filter(scope=SCOPE).count()
            self.stdout.write(
                self.style.SUCCESS(
                    f"OK PAR : {crees} créées, {mis_a_jour} mises à jour. "
                    f"Total scope=par_grand_est : {total_par} "
                    f"({len(cp)} CP + {len(co)} couvert)."
                )
            )
