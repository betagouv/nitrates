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

# Points GPS test choisis pour que la resolution PostGIS donne la bonne
# combinaison (en_zone_vulnerable, zone_note_5, zone_montagne, region).
# Chaque point a ete verifie en DB (intersect ZV + departement). Cf.
# .playwright-mcp/validation_screens/_diff_urls.py pour l'audit.
POINT_REIMS = {  # default : ZV, hors note_5, hors montagne (Marne)
    "lat": 49.2583,
    "lng": 4.0345,
    "code_insee": "51454",
}
POINT_TOULOUSE = {  # ZV + Occitanie -> note_5=True, hors montagne
    "lat": 43.6047,
    "lng": 1.4442,
    "code_insee": "31555",
}
POINT_FOIX = {  # ZV + Occitanie + montagne -> note_7 elargie & pyrenees_atl
    "lat": 42.9667,
    "lng": 1.6044,
    "code_insee": "09122",
}
POINT_CUSSET = {  # ZV + Auv-RhAlpes + montagne -> montagne hors note_7
    "lat": 46.1340,
    "lng": 3.4567,
    "code_insee": "03095",
}


def _choisir_point_gps(contexte: dict) -> dict:
    """Choisit lat/lng/code_insee selon les flags geo du contexte de
    feuille. Garantit que la resolution serveur produit le bon zonage."""
    # Priorite : flags montagne d'abord (plus contraignants).
    zonage_prairie = contexte.get("zonage_prairie_III")
    zonage_montagne_reg = contexte.get("zonage_montagne_regional")
    zone_montagne_d113 = contexte.get("zone_montagne_d113_14")
    zone_note_5 = contexte.get("zone_note_5")

    if zonage_prairie == "montagne_note_7" or zonage_montagne_reg == "note_7":
        return POINT_FOIX
    if zonage_prairie == "montagne_note_6" or zonage_montagne_reg == "note_6":
        return POINT_CUSSET
    if zone_montagne_d113 is True:
        # variante luzerne : on tombe ici si la regle veut juste montagne sans
        # prefer le sous-zonage. Privilegie Foix (couvre note_7).
        return POINT_FOIX
    if zone_note_5 is True:
        return POINT_TOULOUSE
    return POINT_REIMS


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

# Ordre d'affichage canonique dans la mini-app de validation (Max 2026-05-11).
# Sert a parcourir le tableau dans le meme ordre que la lecture Miro
# (haut en bas). Le `index.yaml` du snapshot ne respecte pas forcement cet
# ordre (le snapshot suit l'ordre d'export juriste), donc on le re-impose
# au seed.
ORDRE_BRANCHES_MIRO = [
    "culture_hiver_autre_que_colza",
    "colza",
    "culture_de_printemps",
    "prairies_implantees_plus_de_6_mois",
    "luzerne",
    "autres_cultures",
]

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

# Mapping type_I -> (type_Ia, type_Ib) : l'arbre groupe parfois Ia+Ib sous
# `type_I` (cf. spec metier 2026-04, fallback parcours). Pour pre-remplir
# le form on choisit Ia comme representant.
TYPE_I_FALLBACK = "type_Ia"

# Categorie de culture par defaut quand le mapping referentiel ne tranche
# pas (le referentiel attache sous_culture_form -> sous_culture, mais pas
# sous_culture_form -> categorie_culture). On code en dur les categories
# parce qu'elles sont structurelles du formulaire, pas du parcours.
SOUS_CULTURE_FORM_VERS_CATEGORIE = {
    "colza": "culture_hiver",
    "culture_principale_hiver_autre_que_colza": "culture_hiver",
    "mais": "culture_printemps",
    "culture_principale_printemps_autre_que_mais": "culture_printemps",
    "luzerne": "prairies_ou_luzerne",
    "prairie_plus_6_mois": "prairies_ou_luzerne",
    "prairie_permanente": "prairies_ou_luzerne",
    "prairie_moins_6_mois_printemps": "prairies_ou_luzerne",
    "prairie_moins_6_mois_automne": "prairies_ou_luzerne",
    "cultures_florales_aromatiques": "autres_cultures_principales",
    "cultures_maraicheres_legumieres": "autres_cultures_principales",
    "cultures_porte_graines": "autres_cultures_principales",
    "cultures_perennes_vergers_vignes": "autres_cultures_principales",
}


def _build_form_mapping_from_referentiel() -> tuple[dict, dict]:
    """Derive deux dicts depuis `referentiels.yaml` (source de verite) :

    - `sous_culture_vers_form` : { sous_culture_resolu: (categorie, form) }
      Choisit le premier sous_culture_form qui resout en ce sous_culture.
    - `type_fertilisant_vers_form` : { type: (categorie, sous_fertilisant) }
      Choisit le premier (categorie, sous_fertilisant) qui resout vers ce type
      via `mapping_sous_fertilisant_vers_type`.

    Avantage : si le referentiel change, le seed s'adapte automatiquement.
    Pas de couples inventes (le bug du seed precedent etait des couples
    hardcodes qui resolvaient en fait vers un autre type).
    """
    from envergo.nitrates.yaml_tree.loader import load_referentiels

    ref = load_referentiels()

    sous_culture_vers_form: dict[str, tuple[str, str]] = {}
    for form_key, target in (
        ref.get("mapping_sous_culture_vers_branche") or {}
    ).items():
        # On ne s'interesse qu'aux clefs qui mappent sur culture_principale
        # avec un `sous_culture` direct ; le pre-remplissage couvert/luzerne
        # passe par les memes champs.
        if not isinstance(target, dict):
            continue
        if target.get("occupation_sol") != "culture_principale":
            continue
        sous_culture = target.get("sous_culture")
        if not sous_culture:
            continue
        categorie = SOUS_CULTURE_FORM_VERS_CATEGORIE.get(form_key)
        if not categorie:
            continue
        # Preferer un form_key SANS flags (= cas "neutre" pour l'utilisateur).
        # Sinon le premier mappage avec flags contamine le pre-remplissage
        # (cas mais qui force culture_irriguee_type=mais).
        existing = sous_culture_vers_form.get(sous_culture)
        has_flags = bool(target.get("flags"))
        if existing is None:
            sous_culture_vers_form[sous_culture] = (categorie, form_key)
        elif has_flags:
            # On garde l'existant (premier sans flag, ou premier wins de toutes
            # facons).
            continue
        else:
            # Le nouveau n'a pas de flag : prend la priorite seulement si
            # l'actuel en avait.
            existing_form_key = existing[1]
            existing_target = ref["mapping_sous_culture_vers_branche"].get(
                existing_form_key, {}
            )
            if existing_target.get("flags"):
                sous_culture_vers_form[sous_culture] = (categorie, form_key)

    # autres_cultures : on prefere `cultures_maraicheres_legumieres` comme
    # representant (parle plus a un utilisateur agri). Le first-wins du
    # mapping referentiel choisirait `cultures_florales_aromatiques` qui
    # est moins commun. Override explicite.
    sous_culture_vers_form["autres_cultures"] = (
        "autres_cultures_principales",
        "cultures_maraicheres_legumieres",
    )

    # Inverse mapping fertilisant : pour chaque type, trouver un couple
    # (categorie, sous_fertilisant) qui resout vers ce type via le mapping
    # officiel. On parcourt categories_fertilisants pour garder le couple
    # categorie + sous_fertilisant valide.
    type_vers_form: dict[str, tuple[str, str]] = {}
    mapping = ref.get("mapping_sous_fertilisant_vers_type") or {}
    categories = ref.get("categories_fertilisants") or {}
    for cat_slug, cat_data in categories.items():
        if cat_slug == "autre":
            # On evite "autre" comme representant : peu lisible cote screenshot.
            continue
        for sf in cat_data.get("sous_fertilisants") or []:
            type_resolu = mapping.get(sf)
            if not type_resolu:
                continue
            if type_resolu in type_vers_form:
                continue
            type_vers_form[type_resolu] = (cat_slug, sf)

    # Compatibilite type_I (l'arbre l'utilise comme regroupement Ia+Ib mais
    # le mapping referentiel ne genere que les variantes precises).
    if "type_I" not in type_vers_form and TYPE_I_FALLBACK in type_vers_form:
        type_vers_form["type_I"] = type_vers_form[TYPE_I_FALLBACK]

    return sous_culture_vers_form, type_vers_form


SOUS_CULTURE_RESOLU_VERS_FORM, TYPE_FERTILISANT_RESOLU_VERS_FORM = (
    _build_form_mapping_from_referentiel()
)


def _build_url(contexte: dict, lat=None, lng=None) -> str:
    from urllib.parse import urlencode

    point = _choisir_point_gps(contexte)
    params = {
        "lat": lat if lat is not None else point["lat"],
        "lng": lng if lng is not None else point["lng"],
        "code_insee": point["code_insee"],
    }
    for k, v in contexte.items():
        if k not in CASCADE_TO_FORM_KEY:
            continue
        if isinstance(v, bool):
            v = "True" if v else "False"
        params[CASCADE_TO_FORM_KEY[k]] = str(v)

    # Enrichit avec les champs FORM (categorie_culture, sous_culture_form,
    # categorie_fertilisant, sous_fertilisant) pour que la cascade JS
    # pre-remplisse les radios du formulaire au load. Sans ces champs, le
    # form reste vide bien qu'on ait le resultat correct cote serveur.
    sous_culture = contexte.get("sous_culture")
    form_culture = SOUS_CULTURE_RESOLU_VERS_FORM.get(sous_culture or "")
    # Cas special : si l'arbre est descendu via culture_irriguee_type=mais
    # (cf. mapping_sous_culture_vers_branche.mais.flags), le form doit
    # presenter "mais" comme sous_culture_form pour preserver le sens
    # utilisateur (sinon il voit "culture de printemps autre que mais"
    # alors que la regle parle bien du mais).
    if contexte.get("culture_irriguee_type") == "mais":
        form_culture = ("culture_printemps", "mais")
    if form_culture:
        params["categorie_culture"] = form_culture[0]
        params["sous_culture_form"] = form_culture[1]

    type_fert = contexte.get("type_fertilisant")
    form_fert = TYPE_FERTILISANT_RESOLU_VERS_FORM.get(type_fert or "")
    if form_fert:
        params["categorie_fertilisant"] = form_fert[0]
        params["sous_fertilisant"] = form_fert[1]

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
    -> liste de feuilles Miro. Permet de matcher une feuille YAML par signature.

    L'`ordre_miro` est attribue par compteur global qui suit l'ordre
    d'apparition dans index.yaml (i.e. l'ordre canonique du juriste,
    haut en bas dans le Miro). Permet de trier les BrancheValidation
    dans le tableau de validation selon le meme ordre."""
    lookup: dict[tuple, list] = {}
    ordre = 0
    # Re-trie les branches Miro selon ORDRE_BRANCHES_MIRO (haut en bas
    # dans la mini-app de validation). Branches inconnues -> a la fin.
    branches_miro = miro.get("branches", []) or []
    branches_miro_par_nom = {b.get("branche", ""): b for b in branches_miro}
    branches_triees = [
        branches_miro_par_nom[n]
        for n in ORDRE_BRANCHES_MIRO
        if n in branches_miro_par_nom
    ]
    # Ajoute les branches absentes de la liste canonique (au cas ou).
    for b in branches_miro:
        if b not in branches_triees:
            branches_triees.append(b)
    for b in branches_triees:
        branche_miro = b.get("branche", "")
        branche_yaml = BRANCHE_MIRO_TO_YAML.get(branche_miro)
        screenshot = b.get("screenshot")
        if not branche_yaml:
            continue
        for f in b.get("feuilles", []) or []:
            ordre += 1
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
                    "ordre_miro": ordre,
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
                # Sans match Miro : ordre 9999 (a la fin du tableau).
                "ordre": 9999,
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
                        "ordre": miro_match["ordre_miro"],
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
