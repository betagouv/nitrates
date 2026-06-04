"""Chargement des YAML depuis NITRATES_SPECS_DIR.

Cache lru pour eviter de relire le fichier a chaque appel. En dev avec
runserver_plus, le reload du serveur invalide le cache au reload du module.
Pour invalider manuellement : `load_arbre.cache_clear()`.

Note : `load_referentiels()` a ete migre depuis YAML vers la DB en
phase 4 de la carte #61. La fonction reste exposee avec la meme
signature pour back-compat des appelants (views, templatetag, validator,
admin), mais lit les modeles ORM. Le YAML referentiels.yaml n'est plus
consulte en runtime — il sert uniquement de source de seed (cf.
`seed_referentiels` management command et migration 0012).
"""

from functools import lru_cache
from pathlib import Path

import yaml
from django.conf import settings


def _specs_dir() -> Path:
    return Path(settings.NITRATES_SPECS_DIR)


def _load_yaml(filename: str) -> dict:
    path = _specs_dir() / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Fichier YAML introuvable : {path}. "
            f"Verifier NITRATES_SPECS_DIR (actuel : {settings.NITRATES_SPECS_DIR})."
        )
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=8)
def load_arbre(name: str = "arbre_decision_national") -> dict:
    """Charge un arbre de decision (national ou PAR).

    name peut etre :
      - "arbre_decision_national" (defaut)
      - "arbre_decision_par_R44" pour une region
      - n'importe quel autre nom de fichier YAML present dans specs/
    """
    return _load_yaml(f"{name}.yaml")


def _build_referentiels() -> dict:
    """Construit le dict referentiel a la shape historique YAML, depuis
    la DB (cf. carte #61 phase 4).

    Cette fonction reste exposee pour back-compat des appelants : views,
    templatetags, validator, admin yaml editor consomment toujours un
    dict en mode "shape YAML d'origine" :

      {
        "types_fertilisants": {...},
        "occupations_sol": {...},
        "categories_cultures": {cat_id: {libelle_public, sous_cultures: [...]}},
        "sous_cultures": {sc_id: {libelle_public, description?}},
        "mapping_sous_culture_vers_branche": {sc_id: {occupation_sol, sous_culture, flags?}},
        "statut_icpe": {...},
        "codes_prescription": {pc_id: {mots_cles, texte_court, ...}},
        "notes": {note_id: {libelle_court, condition_declenchement, codes_geographiques?}},
        "regions": {R11: "Île-de-France", ...},
        "evenements_phenologiques": {ev_id: {libelle_public, date_calendrier}},
        "categories_fertilisants": {cat_id: {libelle_public, sous_fertilisants: [...]}},
        "sous_fertilisants": {sf_id: {libelle_public, description?, flags?}},
        "mapping_sous_fertilisant_vers_type": {sf_id: type_reglementaire},
      }

    Choices figes (TypeFertilisant, OccupationSol, StatutICPE, REGIONS_FR)
    sont injectes depuis `constants.py`.
    """
    # Import retardé pour eviter les cycles (loader est importe tôt).
    from envergo.nitrates.constants import (
        REGIONS_FR,
        CategorieFertilisant,
        OccupationSol,
        StatutICPE,
        TypeFertilisant,
    )
    from envergo.nitrates.models import (
        CodePrescription,
        Culture,
        EvenementPhenologique,
        Fertilisant,
        GroupeCultureUI,
        NoteReglementaire,
    )

    # 1. types_fertilisants : choices figes (libellés courts uniquement).
    types_fertilisants = {
        choice.value: {
            "libelle_court": choice.label,
            "libelle_public": choice.label,
        }
        for choice in TypeFertilisant
    }

    # 2. occupations_sol : choices figes.
    occupations_sol = {
        choice.value: {"libelle_public": choice.label} for choice in OccupationSol
    }

    # 3. statut_icpe : choices figes.
    statut_icpe = {
        choice.value: {"libelle_public": choice.label} for choice in StatutICPE
    }

    # 4. regions : dict fige.
    regions = dict(REGIONS_FR)

    # 5. categories_cultures + sous_cultures + mapping
    categories_cultures = {}
    sous_cultures = {}
    mapping_sous_culture_vers_branche = {}

    for cat in GroupeCultureUI.objects.prefetch_related("cultures").all():
        sc_ids = list(cat.cultures.all().values_list("identifiant", flat=True))
        categories_cultures[cat.identifiant] = {
            "libelle_public": cat.libelle_public,
            "sous_cultures": sc_ids,
        }

    for culture in Culture.objects.select_related("branche_culturale").all():
        sous_cultures[culture.identifiant] = {
            "libelle_public": culture.libelle_public,
        }
        # Mapping : reconstruit le dict {occupation_sol, sous_culture, flags?}
        # qu'attendaient les appelants. `flags` regroupe les
        # `champs_prefill` autre que les 2 clés explicites.
        entry = {
            "occupation_sol": culture.occupation_sol,
            "sous_culture": culture.branche_culturale.identifiant,
        }
        if culture.champs_prefill:
            entry["flags"] = dict(culture.champs_prefill)
        mapping_sous_culture_vers_branche[culture.identifiant] = entry

    # 6. codes_prescription
    codes_prescription = {}
    for pc in CodePrescription.objects.select_related("note_reglementaire").all():
        entry = {
            "mots_cles": pc.mots_cles,
            "texte_court": pc.texte_court,
            "texte_redaction_initiale": pc.texte_redaction_initiale,
        }
        if pc.note_reglementaire_id:
            entry["note_reglementaire"] = pc.note_reglementaire.identifiant
        if pc.toujours_affiche:
            entry["toujours_affiche"] = True
        codes_prescription[pc.identifiant] = entry

    # 7. notes
    notes = {}
    for note in NoteReglementaire.objects.all():
        entry = {
            "libelle_court": note.libelle_court,
            "condition_declenchement": note.condition_declenchement,
        }
        if note.regions_concernees or note.departements_concernes:
            entry["codes_geographiques"] = {
                "regions": list(note.regions_concernees or []),
                "departements": list(note.departements_concernes or []),
            }
        notes[note.identifiant] = entry

    # 8. evenements_phenologiques
    evenements_phenologiques = {
        ev.identifiant: {
            "libelle_public": ev.libelle_public,
            "date_calendrier": ev.date_calendrier,
        }
        for ev in EvenementPhenologique.objects.all()
    }

    # 9. categories_fertilisants + sous_fertilisants + mapping
    categories_fertilisants = {}
    sous_fertilisants = {}
    mapping_sous_fertilisant_vers_type = {}

    # Regroupement par categorie en utilisant les choices.
    for choice in CategorieFertilisant:
        sf_ids = list(
            Fertilisant.objects.filter(categorie=choice.value)
            .order_by("ordre_affichage", "libelle_public")
            .values_list("identifiant", flat=True)
        )
        categories_fertilisants[choice.value] = {
            "libelle_public": choice.label,
            "sous_fertilisants": sf_ids,
        }

    # Iteration dans l'ordre des choices `CategorieFertilisant` (fumiers,
    # lisiers, composts, ...) puis par `ordre_affichage` interne pour
    # preserver l'ordre attendu par les call sites qui font un mapping
    # inverse (cf. preview._find_sous_fertilisant qui retourne le PREMIER
    # sous_fertilisant qui mappe vers un type donne).
    for choice in CategorieFertilisant:
        for fert in Fertilisant.objects.filter(categorie=choice.value).order_by(
            "ordre_affichage", "libelle_public"
        ):
            sf_entry = {"libelle_public": fert.libelle_public}
            if fert.description:
                sf_entry["description"] = fert.description
            # Flags de pre-remplissage (ex effluent_peu_charge) : poussés en
            # hidden inputs par la cascade JS pour auto-résoudre des questions
            # complémentaires de l'arbre. Cf. cascade.js resoudreTypeFertilisant.
            if fert.champs_prefill:
                sf_entry["flags"] = dict(fert.champs_prefill)
            sous_fertilisants[fert.identifiant] = sf_entry
            mapping_sous_fertilisant_vers_type[fert.identifiant] = (
                fert.type_reglementaire
            )

    return {
        "types_fertilisants": types_fertilisants,
        "occupations_sol": occupations_sol,
        "categories_cultures": categories_cultures,
        "sous_cultures": sous_cultures,
        "mapping_sous_culture_vers_branche": mapping_sous_culture_vers_branche,
        "statut_icpe": statut_icpe,
        "codes_prescription": codes_prescription,
        "notes": notes,
        "regions": regions,
        "evenements_phenologiques": evenements_phenologiques,
        "categories_fertilisants": categories_fertilisants,
        "sous_fertilisants": sous_fertilisants,
        "mapping_sous_fertilisant_vers_type": mapping_sous_fertilisant_vers_type,
    }


# ─── Cache process-local du referentiel ──────────────────────────────────────
#
# `_build_referentiels()` fait ~27 requetes SQL (toute la DB referentiel).
# Sans cache, les vues qui l'appellent en boucle (editeur d'arbre : un appel
# par date d'evenement phenologique a rendre dans le calendrier) explosent :
# ~600 appels => ~16 000 requetes => ~18 s de rendu. cf. perf carte non-critical.
#
# Le referentiel ne change qu'au seed ou a l'edition admin d'un modele
# referentiel. On cache donc le dict materialise et on invalide explicitement
# sur ecriture (signaux post_save/post_delete, cf. apps.NitratesConfig.ready).
# `maxsize=1` : un seul snapshot, pas de clef.


@lru_cache(maxsize=1)
def _load_referentiels_cached() -> dict:
    return _build_referentiels()


def load_referentiels() -> dict:
    """Retourne le dict referentiel (shape YAML historique), depuis un cache
    process-local. Invalide automatiquement quand un modele referentiel est
    cree / modifie / supprime (cf. invalider_cache_referentiels)."""
    return _load_referentiels_cached()


def invalider_cache_referentiels(*args, **kwargs) -> None:
    """Vide le cache du referentiel. Branche sur les signaux post_save /
    post_delete des modeles referentiel (signature *args/**kwargs pour etre
    utilisable directement comme receiver de signal)."""
    _load_referentiels_cached.cache_clear()
