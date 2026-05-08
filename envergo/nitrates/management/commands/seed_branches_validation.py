"""Seed des `BrancheValidation` a partir de l'arbre actif.

Pour chaque feuille atteignable sous `culture_principale`, cree (ou met
a jour) une ligne `BrancheValidation` avec :
  - `regle_id` (cle naturelle stable)
  - `branche_label` (chemin metier lisible)
  - `url_simulateur` (deeplink avec lat/lng test + cascade contexte)
  - `yaml_snapshot` (extrait YAML de la regle, round-trip ruamel)

N'ecrase PAS les champs de validation (`statut`, `commentaire`,
`screenshot_miro`) si la ligne existe deja. Ainsi on peut re-run le seed
apres une modification de l'arbre sans perdre le travail de validation.

Usage :
    python manage.py seed_branches_validation
    python manage.py seed_branches_validation --dry-run
"""

import io
from urllib.parse import urlencode

import yaml
from django.core.management.base import BaseCommand
from ruamel.yaml import YAML

from envergo.nitrates.models import BrancheValidation
from envergo.nitrates.yaml_tree.feuilles import enumerer_feuilles_culture_principale
from envergo.nitrates.yaml_tree.loader_db import load_active_tree, load_active_tree_raw

# Coords par defaut pour les deeplinks : centre Marne, en zone vulnerable.
# Le cas par defaut sert quand le parcours ne demande pas un INSEE specifique.
LAT_DEFAULT = 49.2583
LNG_DEFAULT = 4.0345

# Cas particuliers : feuilles dont la branche depend d'un INSEE specifique
# (zone_montagne, zone_note_5, etc.). Pour celles-ci, on devrait choisir
# une commune dont les zonages SIG sont coherents avec le contexte attendu.
# Pour le MVP on laisse la coord par defaut (Marne) -- les feuilles qui
# necessitent un autre INSEE auront un screenshot Playwright "no-match"
# qu'il faudra ajuster manuellement plus tard.

CASCADE_TO_FORM_KEY = {
    "occupation_sol": "occupation_sol",
    "sous_culture": "sous_culture",
    "culture_irriguee": "culture_irriguee",
    "culture_irriguee_type": "culture_irriguee_type",
    "type_fertilisant": "type_fertilisant",
    "couvert_duree": "couvert_duree",
    "fertilisant_iaa": "fertilisant_iaa",
    # zone_* sont SIG (resolus serveur) : pas dans l'URL.
}


def _build_url(
    contexte: dict, lat: float = LAT_DEFAULT, lng: float = LNG_DEFAULT
) -> str:
    """Construit l'URL deeplink simulateur a partir du contexte cascade.

    Filtre uniquement les cles cascade pertinentes (cf CASCADE_TO_FORM_KEY)
    pour eviter de poluer l'URL avec les champs SIG (zone_montagne,
    zone_note_5...) qui sont resolus cote serveur.
    """
    params = {"lat": lat, "lng": lng}
    for k, v in contexte.items():
        if k not in CASCADE_TO_FORM_KEY:
            continue
        if isinstance(v, bool):
            v = "True" if v else "False"
        params[CASCADE_TO_FORM_KEY[k]] = str(v)
    return "/simulateur/?" + urlencode(params)


def _yaml_snapshot(arbre: dict, regle_id: str) -> str:
    """Trouve la regle par id dans l'arbre et renvoie son YAML round-trip.

    Si pas trouvee, renvoie chaine vide.
    """
    if not regle_id:
        return ""
    found = _find_regle(arbre, regle_id)
    if not found:
        return ""
    yaml_rt = YAML()
    yaml_rt.indent(mapping=2, sequence=4, offset=2)
    yaml_rt.width = 120
    buf = io.StringIO()
    yaml_rt.dump({"regle": found}, buf)
    return buf.getvalue()


def _find_regle(arbre: dict, regle_id: str) -> dict | None:
    """Walk recursif pour trouver la regle par id."""
    if not isinstance(arbre, dict):
        return None
    if "regle" in arbre and isinstance(arbre["regle"], dict):
        if arbre["regle"].get("id") == regle_id:
            return arbre["regle"]
    for v in arbre.values():
        if isinstance(v, dict):
            r = _find_regle(v, regle_id)
            if r:
                return r
        elif isinstance(v, list):
            for it in v:
                r = _find_regle(it, regle_id)
                if r:
                    return r
    return None


class Command(BaseCommand):
    help = "Seed les BrancheValidation a partir de l'arbre actif."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="N'ecrit rien en DB, affiche juste le plan.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Supprime les BrancheValidation existantes avant le seed.",
        )

    def handle(self, *args, **opts):
        arbre = load_active_tree()
        feuilles = enumerer_feuilles_culture_principale(arbre)

        # Re-parse le YAML brut pour garder les commentaires dans les snapshots.
        try:
            raw = load_active_tree_raw()
            arbre_rt = yaml.safe_load(raw) if raw else arbre
        except Exception:
            arbre_rt = arbre

        if opts["reset"] and not opts["dry_run"]:
            n = BrancheValidation.objects.all().delete()
            self.stdout.write(f"Reset : {n[0]} BrancheValidation supprimees.")

        crees = 0
        mis_a_jour = 0
        for label, contexte, regle_id in feuilles:
            if not regle_id:
                # renvoi_vers non resolu : on skip (rare, a traiter
                # manuellement)
                continue
            url = _build_url(contexte)
            snapshot = _yaml_snapshot(arbre_rt, regle_id)

            if opts["dry_run"]:
                self.stdout.write(f"[dry-run] {regle_id} | {label[:80]}")
                continue

            obj, created = BrancheValidation.objects.update_or_create(
                regle_id=regle_id,
                defaults={
                    "branche_label": label[:500],
                    "url_simulateur": url[:2000],
                    "yaml_snapshot": snapshot,
                },
            )
            if created:
                crees += 1
            else:
                mis_a_jour += 1

        if opts["dry_run"]:
            self.stdout.write(f"\n[dry-run] {len(feuilles)} feuilles enumerees.")
        else:
            self.stdout.write(
                f"OK : {crees} crees, {mis_a_jour} mis a jour "
                f"(total {BrancheValidation.objects.count()})."
            )
