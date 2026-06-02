"""Seed des `BrancheValidation` pour les feuilles « couvert d'interculture ».

Pendant couvert (sprint 2) du seed `seed_branches_validation` (culture
principale). Pour chaque feuille atteignable sous
`occupation_sol = couvert_intercultures` du YAML actif (renvoi_vers
resolus), cree/met a jour une `BrancheValidation` avec :
  - `chemin_yaml` (cle naturelle, path d'IDs)
  - `branche_label` (chemin metier lisible)
  - `url_simulateur` (deeplink pre-rempli : couvert + type fertilisant +
    complement ICPE/IAA + zonage note 5)
  - `yaml_snapshot` (extrait YAML de la regle, round-trip ruamel)
  - `resultat_miro` = texte attendu **derive du SVG/CSV** (board Miro
    arbre complet 2026-05-30) quand un rapprochement existe ; sinon le
    texte YAML de la regle.

Le rapprochement YAML <-> SVG est pre-calcule dans
`snapshot_miro/arbre_complet/2026-05-30/couvert_reference_svg.json`
(genere par l'analyse SVG + CSV, cf. `cross_validation_couvert.md`).
Si le fichier est absent, on retombe sur le texte YAML seul.

N'ecrase PAS les champs de validation (statut, screenshots) si la ligne
existe deja. Ne touche PAS aux 41 lignes culture principale.

ATTENTION : `flag_verif` / `note_verif` SONT re-ecrits a chaque seed
(ce sont des notes POSEES PAR LE SEED, pas une saisie humaine). Si Max
leve un flag manuellement dans l'app puis re-seede, le flag revient.
C'est voulu : la source des flags = l'analyse de seed. Pour lever un
flag durablement, retirer la regle de FLAGS_PAR_REGLE ou ajuster la
logique `_flag_pour_feuille`.

Usage :
    python manage.py seed_branches_validation_couvert
    python manage.py seed_branches_validation_couvert --dry-run
    python manage.py seed_branches_validation_couvert --reset   # couvert only
"""

import json
from pathlib import Path
from urllib.parse import urlencode

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand

from envergo.nitrates.management.commands.seed_branches_validation import (
    POINT_REIMS,
    POINT_TOULOUSE,
    TYPE_FERTILISANT_RESOLU_VERS_FORM,
    _yaml_snapshot,
)
from envergo.nitrates.models import BrancheValidation
from envergo.nitrates.yaml_tree.feuilles import enumerer_feuilles_couvert_v2
from envergo.nitrates.yaml_tree.loader_db import load_active_tree, load_active_tree_raw

# sous_culture (slug arbre) -> (categorie_culture UI, sous_culture_form UI).
# Permet de pre-remplir la cascade du formulaire pour atterrir sur la
# bonne feuille couvert. Les form keys viennent de
# `categories_cultures.couvert_intercultures_{longue,courte}` du
# referentiel ; on les code ici parce que le mapping inverse
# sous_culture -> form key n'est pas trivialement derivable (plusieurs
# form keys, on choisit le representant canonique).
COUVERT_SOUS_CULTURE_VERS_FORM = {
    "cie_avant_3112": (
        "couvert_intercultures_longue",
        "couvert_recolte_plus_en_place_apres_3112",
    ),
    "cie_apres_0101": (
        "couvert_intercultures_longue",
        "couvert_recolte_toujours_en_place_apres_0101",
    ),
    "cine_avant_3112": (
        "couvert_intercultures_longue",
        "couvert_non_recolte_plus_en_place_apres_3112",
    ),
    "cine_apres_0101": (
        "couvert_intercultures_longue",
        "couvert_non_recolte_toujours_en_place_apres_0101",
    ),
    "cie_courte": (
        "couvert_intercultures_courte",
        "couvert_courte_recolte",
    ),
    "cine_courte": (
        "couvert_intercultures_courte",
        "couvert_courte_non_recolte",
    ),
}

# Ordre d'affichage canonique du couvert dans la mini-app (lecture board
# haut->bas : longue avant courte, recolte avant non-recolte).
ORDRE_SOUS_CULTURE = [
    "cie_apres_0101",
    "cine_apres_0101",
    "cie_avant_3112",
    "cine_avant_3112",
    "cie_courte",
    "cine_courte",
]

# Offset d'ordre pour empiler le couvert APRES les 41 feuilles culture
# principale dans le tableau de validation (qui s'arretent vers ordre 41).
ORDRE_OFFSET = 100

# Champs complement passes en query param brut (lus par l'evaluator).
CHAMPS_COMPLEMENT = (
    "plan_epandage",
    "fertilisant_iaa",
    "effluent_peu_charge",
    "icpe_ed",
)

# ─── Cas speciaux a verifier (flag pose au seed) ──────────────────────────
# Notes posees PAR LE SEED (pas une action user) pour que Max ne perde pas
# la trace des points a regarder lors de la re-validation humaine. Cf.
# snapshot_miro/.../cross_validation_couvert.md pour le detail.
# Clef = regle_id ; appliquee a TOUTES les feuilles atteignant cette regle.
FLAGS_PAR_REGLE = {
    "r_cine_avant_3112_type_III": (
        "DIVERGENCE board : le YAML dit « Apport interdit toute l'année » "
        "(01/07→30/06), alors que le board montre des motifs datés "
        "(15/10 ou 15/11 → 15/01). À confirmer juriste."
    ),
    "r_cine_avant_3112_type_0_icpe_a": (
        "FORMULATION à trancher : période affichée OK (15/12→15/01, = board), "
        "mais la condition dit « conditions de la note 1 » que le board ne "
        "formule pas. Vérifier le libellé de condition (pas un bug de routage)."
    ),
    "r_cie_courte_type_III": (
        "FORMULATION : le YAML exprime en positif (« apports possibles… entre "
        "le semis et les 15 j ») ce que le board exprime en négatif "
        "(« apports interdits sauf… »). Même périmètre, à harmoniser."
    ),
    # Les 6 feuilles courte 0/I/II : bug renvoi_vers regles_partagees corrigé
    # pendant ce sprint -> re-vérifier qu'elles rendent bien le bon résultat.
    "r_cie_courte_types_0_I_II": (
        "EX-BUG corrigé (renvoi_vers regles_partagees non indexé → "
        "ParcoursError). Re-vérifier le rendu : « Apport autorisé » [PC15]."
    ),
    "r_cine_courte_types_0_I_II": (
        "EX-BUG corrigé (renvoi_vers regles_partagees non indexé → "
        "ParcoursError). Re-vérifier le rendu : « Apport autorisé » [PC13]."
    ),
}

# Seuil de rapprochement SVG en dessous duquel on flague la feuille comme
# « texte board incertain » (le seed n'a pas su matcher le texte YAML a une
# feuille-resultat du board avec confiance).
SCORE_FLAG_SEUIL = 0.5


def _ref_svg() -> dict:
    """Charge le rapprochement YAML<->SVG pre-calcule (keyed par
    chemin_yaml). Renvoie {} si le fichier n'est pas la."""
    path = (
        Path(settings.NITRATES_SPECS_DIR)
        / "snapshot_miro"
        / "arbre_complet"
        / "2026-05-30"
        / "couvert_reference_svg.json"
    )
    if not path.exists():
        return {}
    with path.open() as f:
        data = json.load(f)
    return {row["chemin_yaml"]: row for row in data}


def _build_url(feuille: dict) -> str:
    contexte = feuille["contexte"]
    params = {
        "lat": POINT_REIMS["lat"],
        "lng": POINT_REIMS["lng"],
        "code_insee": POINT_REIMS["code_insee"],
        "occupation_sol": "couvert_intercultures",
    }
    # zone_note_5 : si la feuille discrimine dessus, choisir un point GPS
    # coherent (Toulouse = note 5 True) pour que la resolution serveur
    # tombe sur la bonne branche.
    note5 = contexte.get("zone_note_5")
    if note5 is True:
        params["lat"] = POINT_TOULOUSE["lat"]
        params["lng"] = POINT_TOULOUSE["lng"]
        params["code_insee"] = POINT_TOULOUSE["code_insee"]

    sous_culture = contexte.get("sous_culture")
    if sous_culture:
        params["sous_culture"] = sous_culture
        form = COUVERT_SOUS_CULTURE_VERS_FORM.get(sous_culture)
        if form:
            params["categorie_culture"] = form[0]
            params["sous_culture_form"] = form[1]

    type_fert = contexte.get("type_fertilisant")
    if type_fert:
        params["type_fertilisant"] = type_fert
        form_fert = TYPE_FERTILISANT_RESOLU_VERS_FORM.get(type_fert)
        if form_fert:
            params["categorie_fertilisant"] = form_fert[0]
            params["sous_fertilisant"] = form_fert[1]

    for champ in CHAMPS_COMPLEMENT:
        if champ in contexte:
            v = contexte[champ]
            params[champ] = "True" if v is True else ("False" if v is False else str(v))

    return "/simulateur/?" + urlencode(params)


def _flag_pour_feuille(regle_id: str, row: dict) -> tuple[bool, str]:
    """Determine si la feuille merite un flag « a verifier » et sa note.

    Priorite :
      1. note explicite par regle_id (divergences/formulations/ex-bugs) ;
      2. feuille calculatrice sans texte fige -> comparaison visuelle ;
      3. rapprochement SVG faible (score < seuil) -> texte board incertain.

    Renvoie ("", False) si rien a signaler."""
    note_explicite = FLAGS_PAR_REGLE.get(regle_id)
    if note_explicite:
        return True, note_explicite

    if not row:
        # Pas de ligne de reference : on ne sait pas rapprocher, a verifier.
        return True, (
            "Aucun rapprochement board pour cette feuille (absente de la "
            "référence SVG). À vérifier manuellement."
        )

    yaml_texte = (row.get("yaml_texte") or "").strip()
    if not yaml_texte:
        return True, (
            "Feuille calculatrice sans texte figé : le résultat dépend des "
            "dates (semis/destruction). Comparer visuellement le calendrier "
            "au board (pas de rapprochement texte possible)."
        )

    score = row.get("match_score")
    if isinstance(score, (int, float)) and score < SCORE_FLAG_SEUIL:
        return True, (
            f"Rapprochement board incertain (score {score}). Le texte YAML "
            "n'a pas été matché avec confiance à une feuille-résultat du "
            "board — vérifier que le résultat correspond bien."
        )

    return False, ""


class Command(BaseCommand):
    help = "Seed BrancheValidation pour les feuilles couvert d'interculture."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Supprime d'abord les BrancheValidation couvert (pas la CP).",
        )

    def handle(self, *args, **opts):
        arbre = load_active_tree()
        feuilles = enumerer_feuilles_couvert_v2(arbre)

        try:
            raw = load_active_tree_raw()
            arbre_rt = yaml.safe_load(raw) if raw else arbre
        except Exception:
            arbre_rt = arbre

        ref = _ref_svg()
        if not ref:
            self.stdout.write(
                self.style.WARNING(
                    "Reference SVG absente : resultat_miro = texte YAML seul."
                )
            )

        if opts["reset"] and not opts["dry_run"]:
            qs = BrancheValidation.objects.filter(
                chemin_yaml__contains="q_couvert_sous_culture"
            )
            n = qs.count()
            qs.delete()
            self.stdout.write(f"Reset couvert : {n} lignes supprimees.")

        crees = mis_a_jour = avec_ref = flags = 0
        for feuille in feuilles:
            chemin_yaml = "/".join(feuille["chemin_ids"])
            url = _build_url(feuille)
            snapshot = _yaml_snapshot(arbre_rt, feuille["regle_id"])
            sous_culture = feuille["contexte"].get("sous_culture", "")

            row = ref.get(chemin_yaml, {})
            svg_attendu = row.get("svg_attendu")
            score = row.get("match_score")
            # resultat_miro : texte attendu cote board. Priorite au texte SVG
            # rapproche avec confiance (score >= 0.5) ; sinon le texte derive
            # (texte YAML, ou periodes pour les regles calculatrice sans
            # `texte` fige). Pour ces dernieres, le rapprochement se fait
            # visuellement via Playwright + screenshot Miro, pas par texte.
            resultat = svg_attendu or row.get("derived") or ""
            if svg_attendu:
                avec_ref += 1

            flag, note = _flag_pour_feuille(feuille["regle_id"], row)
            if flag:
                flags += 1

            try:
                ordre = (
                    ORDRE_OFFSET
                    + ORDRE_SOUS_CULTURE.index(sous_culture) * 1000
                    + feuilles.index(feuille)
                )
            except ValueError:
                ordre = 9999

            if opts["dry_run"]:
                tag = (
                    f"[SVG {score}] {svg_attendu[:50]}"
                    if svg_attendu
                    else "[pas de match SVG]"
                )
                flag_tag = " ⚑VERIF" if flag else ""
                self.stdout.write(f"[dry-run] {chemin_yaml[-70:]:70} {tag}{flag_tag}")
                continue

            defaults = {
                "regle_id": feuille["regle_id"] or "",
                "branche_label": feuille["label"][:500],
                "url_simulateur": url[:2000],
                "yaml_snapshot": snapshot,
                "branche_miro": sous_culture[:200],
                "type_fertilisant_miro": (
                    feuille["contexte"].get("type_fertilisant") or ""
                )[:50],
                "resultat_miro": resultat[:500],
                "ordre": ordre,
                "flag_verif": flag,
                "note_verif": note,
            }
            _, created = BrancheValidation.objects.update_or_create(
                chemin_yaml=chemin_yaml,
                defaults=defaults,
            )
            if created:
                crees += 1
            else:
                mis_a_jour += 1

        if opts["dry_run"]:
            self.stdout.write(
                f"\n[dry-run] {len(feuilles)} feuilles couvert, "
                f"{avec_ref} avec resultat SVG, {flags} flaggees a verifier."
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"OK couvert : {crees} crees, {mis_a_jour} mis a jour, "
                    f"{avec_ref} avec resultat SVG, {flags} flaggees a verifier "
                    f"(total BrancheValidation {BrancheValidation.objects.count()})."
                )
            )
