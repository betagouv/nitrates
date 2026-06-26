"""Seed des `BrancheValidation` pour les feuilles « couvert d'interculture ».

Pendant couvert du seed `seed_branches_validation` (culture principale).
Pour chaque feuille atteignable sous `occupation_sol = couvert_intercultures`
du YAML actif (renvoi_vers résolus), crée/met à jour une `BrancheValidation`
avec UNIQUEMENT les champs **factuels et sûrs**, dérivés du YAML :

  - `chemin_yaml`    (clé naturelle, path d'IDs)
  - `branche_label`  (chemin métier lisible)
  - `url_simulateur` (deeplink pré-rempli : couvert + type fertilisant +
                      complément ICPE/IAA + zonage note 5)
  - `yaml_snapshot`  (extrait YAML de la règle, round-trip ruamel)
  - `branche_miro`   (slug sous_culture, factuel)
  - `type_fertilisant_miro` (type fertilisant, factuel)
  - `ordre`          (tri canonique, couvert empilé après la CP)

VOLONTAIREMENT LAISSÉS VIDES (saisie 100 % manuelle par le validateur) :
  `resultat_miro`, `miro_widget_id`, `screenshot_miro`, `code_pc_miro`,
  `flag_verif`, `note_verif`.

Décision carte #140 : le board Miro couvert est trop ambigu vis-à-vis du
YAML (mêmes libellés dupliqués jusqu'à 10×, feuilles calculatrices sans
texte figé, type III « après 01/01 » absent du board) pour un
rapprochement texte/widget automatique fiable. Plutôt qu'un mapping auto
douteux, le validateur colle lui-même, par feuille :
  - le `miro_widget_id` (depuis « Copy link to widget » du board → l'app
    fabrique le deeplink `?moveToWidget=<id>`), et/ou
  - un screenshot Miro scopé à la main.
L'ancien rapprochement heuristique (couvert_reference_svg.json + flags) est
abandonné ; le snapshot SVG du board (widgets.json) reste comme référence
pour retrouver les ids à la main.

N'écrase PAS les champs de validation (statut, screenshots, miro_widget_id,
resultat_miro, code_pc_miro saisis à la main) si la ligne existe déjà : le
re-seed ne pose que des `defaults` sur create, et ne met à jour QUE les
champs dérivés du YAML (label, url, snapshot, ordre, slugs) — voir
`CHAMPS_DERIVES`. Ne touche PAS aux lignes culture principale.

Usage :
    python manage.py seed_branches_validation_couvert
    python manage.py seed_branches_validation_couvert --dry-run
    python manage.py seed_branches_validation_couvert --reset   # couvert only
"""

from urllib.parse import urlencode

import yaml
from django.core.management.base import BaseCommand

from envergo.nitrates.management.commands.seed_branches_validation import (
    POINT_REIMS,
    POINT_TOULOUSE,
    TYPE_FERTILISANT_RESOLU_VERS_FORM,
    _yaml_snapshot,
)
from envergo.nitrates.models import BrancheValidation, DecisionTree
from envergo.nitrates.yaml_tree.feuilles import enumerer_feuilles_couvert_v2
from envergo.nitrates.yaml_tree.loader_db import load_active_tree, load_active_tree_raw


def _charger_arbre_national():
    """Charge l'arbre NATIONAL (PAN), même quand plusieurs arbres sont
    actifs en DB partagée (national + PAR + ZAR Grand Est). Le couvert que
    ce seed provisionne est celui du PAN ; on cible donc explicitement
    l'arbre national par son nom, au lieu de `load_active_tree()` qui fait
    un `.get(status='active')` ambigu et lève MultipleObjectsReturned.

    Retourne (contenu_json, yaml_brut). Fallback sur le loader standard
    quand un seul arbre est actif (comportement historique inchangé).
    """
    actifs = DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE)
    nat = actifs.filter(name__icontains="national").first()
    if nat is not None:
        return nat.contenu, (nat.contenu_yaml_brut or "")
    # Un seul arbre actif (ou aucun « national ») : loader standard.
    raw = ""
    try:
        raw = load_active_tree_raw()
    except Exception:
        pass
    return load_active_tree(), raw


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

# Champs DERIVES du YAML : recalcules a chaque seed, ecrases meme sur une
# ligne existante (ils refletent l'arbre, pas une saisie humaine). Tout le
# reste (validation + saisie Miro manuelle) est preserve sur update.
CHAMPS_DERIVES = (
    "branche_label",
    "url_simulateur",
    "yaml_snapshot",
    "branche_miro",
    "type_fertilisant_miro",
    "ordre",
)


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
        arbre, raw = _charger_arbre_national()
        feuilles = enumerer_feuilles_couvert_v2(arbre)

        try:
            arbre_rt = yaml.safe_load(raw) if raw else arbre
        except Exception:
            arbre_rt = arbre

        if opts["reset"] and not opts["dry_run"]:
            qs = BrancheValidation.objects.filter(
                chemin_yaml__contains="q_couvert_sous_culture"
            )
            n = qs.count()
            qs.delete()
            self.stdout.write(f"Reset couvert : {n} lignes supprimees.")

        crees = mis_a_jour = 0
        for feuille in feuilles:
            chemin_yaml = "/".join(feuille["chemin_ids"])
            sous_culture = feuille["contexte"].get("sous_culture", "")

            derives = {
                "branche_label": feuille["label"][:500],
                "url_simulateur": _build_url(feuille)[:2000],
                "yaml_snapshot": _yaml_snapshot(arbre_rt, feuille["regle_id"]),
                "branche_miro": sous_culture[:200],
                "type_fertilisant_miro": (
                    feuille["contexte"].get("type_fertilisant") or ""
                )[:50],
            }
            try:
                derives["ordre"] = (
                    ORDRE_OFFSET
                    + ORDRE_SOUS_CULTURE.index(sous_culture) * 1000
                    + feuilles.index(feuille)
                )
            except ValueError:
                derives["ordre"] = 9999

            if opts["dry_run"]:
                self.stdout.write(
                    f"[dry-run] {chemin_yaml[-70:]:70} "
                    f"{sous_culture}/{derives['type_fertilisant_miro']}"
                )
                continue

            obj = BrancheValidation.objects.filter(chemin_yaml=chemin_yaml).first()
            if obj is None:
                # Create : pose les derives. Les champs Miro/validation
                # gardent leurs defauts modele (vides) -> saisie manuelle.
                BrancheValidation.objects.create(
                    chemin_yaml=chemin_yaml,
                    regle_id=feuille["regle_id"] or "",
                    nature=BrancheValidation.NATURE_COUVERT,
                    **derives,
                )
                crees += 1
            else:
                # Update : ne touche QUE les derives YAML, preserve toute
                # la saisie humaine (miro_widget_id, resultat_miro,
                # screenshots, statut, code_pc, flags).
                for champ in CHAMPS_DERIVES:
                    setattr(obj, champ, derives[champ])
                obj.regle_id = feuille["regle_id"] or ""
                obj.nature = BrancheValidation.NATURE_COUVERT
                obj.save(
                    update_fields=list(CHAMPS_DERIVES)
                    + ["regle_id", "nature", "updated_at"]
                )
                mis_a_jour += 1

        if opts["dry_run"]:
            self.stdout.write(f"\n[dry-run] {len(feuilles)} feuilles couvert.")
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"OK couvert : {crees} crees, {mis_a_jour} mis a jour "
                    f"(champs Miro laisses vides, saisie manuelle). "
                    f"Total BrancheValidation {BrancheValidation.objects.count()}."
                )
            )
