"""Seed des `BrancheValidation` a partir de l'arbre actif + snapshot Miro.

Pour chaque feuille atteignable sous `culture_principale` du YAML codé,
cree (ou met a jour) une ligne `BrancheValidation` avec :
  - `chemin_yaml` (cle naturelle, path d'IDs YAML)
  - `branche_label` (chemin metier lisible)
  - `url_simulateur` (deeplink avec lat/lng test + cascade contexte)
  - `yaml_snapshot` (extrait YAML de la regle, round-trip ruamel)
  - enrichissements Miro (resultat_miro, code_pc_miro, screenshot_miro
    auto-attache depuis snapshot_miro/.../<branche>.png) si match trouve

Le matching YAML <-> Miro se base sur (branche, type_fertilisant,
presence de condition, presence de zonage). Pas exact sur le texte
condition/zonage (libelles Miro en francais libre vs slugs YAML).

N'ecrase PAS les champs de validation (`statut`, `commentaire`,
`screenshot_yaml_viewer`, `screenshot_yaml_form`, `screenshot_playwright`)
si la ligne existe deja. Re-runable apres modif arbre.

Usage :
    python manage.py seed_branches_validation
    python manage.py seed_branches_validation --dry-run
    python manage.py seed_branches_validation --reset
"""

import io
from pathlib import Path

import yaml
from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand
from ruamel.yaml import YAML

from envergo.nitrates.models import BrancheValidation
from envergo.nitrates.yaml_tree.feuilles import enumerer_feuilles_culture_principale_v2
from envergo.nitrates.yaml_tree.loader_db import load_active_tree, load_active_tree_raw

LAT_DEFAULT = 49.2583
LNG_DEFAULT = 4.0345

CASCADE_TO_FORM_KEY = {
    "occupation_sol": "occupation_sol",
    "sous_culture": "sous_culture",
    "culture_irriguee": "culture_irriguee",
    "culture_irriguee_type": "culture_irriguee_type",
    "type_fertilisant": "type_fertilisant",
    "couvert_duree": "couvert_duree",
    "fertilisant_iaa": "fertilisant_iaa",
    "plan_epandage": "plan_epandage",
    "effluent_peu_charge": "effluent_peu_charge",
    "fertirrigation": "fertirrigation",
}

# Libelles branche Miro -> slug YAML.
BRANCHE_MIRO_TO_YAML = {
    "colza": "colza",
    "culture_hiver_autre_que_colza": "culture_hiver_hors_colza",
    "culture_de_printemps": "culture_printemps",
    "prairies_implantees_plus_de_6_mois": "prairie_plus_6_mois",
    "luzerne": "luzerne",
    "autres_cultures": "autres_cultures",
}

# Libelles type_fertilisant Miro -> slug YAML.
TYPE_FERTILISANT_MIRO_TO_YAML = {
    "Type 0": "type_0",
    "Type I": "type_I",
    "Type Ia": "type_Ia",
    "Type Ib": "type_Ib",
    "Type II": "type_II",
    "Type III": "type_III",
    # Cas special "autres_cultures" : une seule feuille couvre tous les types.
    "Types 0, Ia, Ib, II et III": "*",
}


def _build_url(contexte: dict, lat=LAT_DEFAULT, lng=LNG_DEFAULT) -> str:
    from urllib.parse import urlencode

    params = {"lat": lat, "lng": lng}
    for k, v in contexte.items():
        if k not in CASCADE_TO_FORM_KEY:
            continue
        if isinstance(v, bool):
            v = "True" if v else "False"
        params[CASCADE_TO_FORM_KEY[k]] = str(v)
    return "/simulateur/?" + urlencode(params)


def _yaml_snapshot(arbre_rt: dict, regle_id: str | None) -> str:
    if not regle_id:
        return ""
    found = _find_regle(arbre_rt, regle_id)
    if not found:
        return ""
    yaml_rt = YAML()
    yaml_rt.indent(mapping=2, sequence=4, offset=2)
    yaml_rt.width = 120
    buf = io.StringIO()
    yaml_rt.dump({"regle": found}, buf)
    return buf.getvalue()


def _find_regle(arbre: dict, regle_id: str) -> dict | None:
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


def _load_miro_index() -> dict:
    """Charge le dernier snapshot Miro disponible. Renvoie {} si pas
    de snapshot (l'enrichissement Miro est skip)."""
    miro_dir = Path(settings.NITRATES_SPECS_DIR).parent / "specs" / "snapshot_miro"
    # Le NITRATES_SPECS_DIR pointe vers .../specs/, donc snapshot_miro est sous lui :
    miro_dir = Path(settings.NITRATES_SPECS_DIR) / "snapshot_miro"
    cp_dir = miro_dir / "culture_principale"
    if not cp_dir.exists():
        return {}
    # Prend la sous-dir datee la plus recente.
    dated = sorted([d for d in cp_dir.iterdir() if d.is_dir()], reverse=True)
    if not dated:
        return {}
    latest = dated[0]
    idx_path = latest / "index.yaml"
    if not idx_path.exists():
        return {}
    with idx_path.open() as f:
        data = yaml.safe_load(f) or {}
    data["__path__"] = latest
    return data


def _build_miro_lookup(miro: dict) -> dict:
    """Construit un dict keye sur (branche_yaml, type_fert_yaml, has_cond, has_zonage)
    -> liste de feuilles Miro. Permet de matcher une feuille YAML par signature."""
    lookup: dict[tuple, list] = {}
    for b in miro.get("branches", []) or []:
        branche_miro = b.get("branche", "")
        branche_yaml = BRANCHE_MIRO_TO_YAML.get(branche_miro)
        screenshot = b.get("screenshot")
        if not branche_yaml:
            continue
        for f in b.get("feuilles", []) or []:
            type_miro = f.get("type_fertilisant", "")
            type_yaml = TYPE_FERTILISANT_MIRO_TO_YAML.get(type_miro)
            if not type_yaml:
                continue
            has_cond = bool(f.get("condition"))
            has_zonage = bool(f.get("zonage"))
            key = (branche_yaml, type_yaml, has_cond, has_zonage)
            lookup.setdefault(key, []).append(
                {
                    "branche_miro": branche_miro,
                    "type_miro": type_miro,
                    "condition": f.get("condition") or "",
                    "zonage": f.get("zonage") or "",
                    "resultat": f.get("resultat") or "",
                    "code_pc": f.get("code_pc") or "",
                    "screenshot": screenshot,
                }
            )
    return lookup


def _match_miro(feuille_yaml: dict, lookup: dict, used: set) -> dict | None:
    """Matche une feuille YAML avec une feuille Miro. used : set des
    indexes Miro (key + position dans la liste) deja consommes pour eviter
    les doublons."""
    type_fert = feuille_yaml.get("type_fertilisant") or ""
    branche = feuille_yaml.get("branche_valeur") or ""
    has_cond = bool(feuille_yaml.get("condition"))
    has_zonage = bool(feuille_yaml.get("zonage"))

    # Tentative 1 : match exact branche + type + presence cond + presence zonage.
    key = (branche, type_fert, has_cond, has_zonage)
    if key in lookup:
        for i, candidat in enumerate(lookup[key]):
            if (key, i) in used:
                continue
            used.add((key, i))
            return candidat

    # Tentative 2 : match avec branche + type "*" (cas autres_cultures)
    key2 = (branche, "*", has_cond, has_zonage)
    if key2 in lookup:
        for i, candidat in enumerate(lookup[key2]):
            if (key2, i) in used:
                continue
            used.add((key2, i))
            return candidat

    # Tentative 3 : relax progressivement les contraintes presence
    # condition/zonage pour matcher meme quand cote Miro c'est dans
    # condition et cote YAML dans zonage (ou inverse). Les 3 prairies
    # Type III sont dans ce cas.
    for relax_cond, relax_zonage in [
        (has_cond, not has_zonage),  # flip zonage
        (not has_cond, has_zonage),  # flip condition
        (not has_cond, not has_zonage),  # flip les deux
    ]:
        key3 = (branche, type_fert, relax_cond, relax_zonage)
        if key3 in lookup:
            for i, candidat in enumerate(lookup[key3]):
                if (key3, i) in used:
                    continue
                used.add((key3, i))
                return candidat

    return None


class Command(BaseCommand):
    help = (
        "Seed BrancheValidation a partir du YAML actif + enrichissement "
        "snapshot Miro."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--reset", action="store_true")

    def handle(self, *args, **opts):
        arbre = load_active_tree()
        feuilles = enumerer_feuilles_culture_principale_v2(arbre)

        try:
            raw = load_active_tree_raw()
            arbre_rt = yaml.safe_load(raw) if raw else arbre
        except Exception:
            arbre_rt = arbre

        miro = _load_miro_index()
        miro_lookup = _build_miro_lookup(miro) if miro else {}
        miro_path = miro.get("__path__")
        used_miro_keys: set = set()

        if opts["reset"] and not opts["dry_run"]:
            n = BrancheValidation.objects.all().delete()
            self.stdout.write(f"Reset : {n[0]} BrancheValidation supprimees.")

        crees = 0
        mis_a_jour = 0
        match_miro = 0
        for feuille in feuilles:
            chemin_yaml = "/".join(feuille["chemin_ids"])
            url = _build_url(feuille["contexte"])
            snapshot = _yaml_snapshot(arbre_rt, feuille["regle_id"])

            miro_match = _match_miro(feuille, miro_lookup, used_miro_keys)

            if opts["dry_run"]:
                miro_tag = (
                    f"[Miro: {miro_match['type_miro']} | {miro_match['resultat'][:40]}]"
                    if miro_match
                    else "[Miro: NO MATCH]"
                )
                self.stdout.write(f"[dry-run] {chemin_yaml[-80:]:80} {miro_tag}")
                if miro_match:
                    match_miro += 1
                continue

            defaults = {
                "regle_id": feuille["regle_id"] or "",
                "branche_label": feuille["label"][:500],
                "url_simulateur": url[:2000],
                "yaml_snapshot": snapshot,
            }
            if miro_match:
                defaults.update(
                    {
                        "branche_miro": miro_match["branche_miro"][:200],
                        "type_fertilisant_miro": miro_match["type_miro"][:50],
                        "condition_miro": miro_match["condition"][:200],
                        "zonage_miro": miro_match["zonage"][:200],
                        "resultat_miro": miro_match["resultat"][:500],
                        "code_pc_miro": miro_match["code_pc"][:20],
                    }
                )

            obj, created = BrancheValidation.objects.update_or_create(
                chemin_yaml=chemin_yaml,
                defaults=defaults,
            )

            # Attach screenshot Miro (PNG packagé) si pas deja attache.
            if (
                miro_match
                and miro_path
                and miro_match.get("screenshot")
                and not obj.screenshot_miro
            ):
                png_path = miro_path / miro_match["screenshot"]
                if png_path.exists():
                    with png_path.open("rb") as f:
                        obj.screenshot_miro.save(
                            miro_match["screenshot"], File(f), save=True
                        )

            if created:
                crees += 1
            else:
                mis_a_jour += 1
            if miro_match:
                match_miro += 1

        if opts["dry_run"]:
            self.stdout.write(
                f"\n[dry-run] {len(feuilles)} feuilles enumerees, "
                f"{match_miro} matches Miro."
            )
        else:
            self.stdout.write(
                f"OK : {crees} crees, {mis_a_jour} mis a jour, "
                f"{match_miro} enrichies Miro "
                f"(total {BrancheValidation.objects.count()})."
            )
