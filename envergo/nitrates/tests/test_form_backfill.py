"""Tests de la reconstruction des champs front de cascade (#175).

`backfill_form_fields` reconstruit categorie_culture / sous_culture_form /
categorie_fertilisant a partir des champs backend d'un lien direct, quand c'est
non ambigu. Ces tests couvrent :
  - le cas du bug (couvert : sous_culture -> form + categorie) ;
  - le fertilisant (sous_fertilisant -> categorie) ;
  - la non-regression : on n'ecrase jamais une valeur fournie ;
  - l'ambiguite : on ne devine pas quand plusieurs formes resolvent pareil ;
  - on ne fabrique jamais sous_fertilisant depuis le seul type_fertilisant.
"""

import pytest

from envergo.nitrates.form_backfill import backfill_form_fields

# Referentiel minimal reproduisant la structure reelle (mapping culture +
# categories fertilisants). Suffisant pour les cas testes, sans DB.
REFERENTIELS = {
    # categorie_culture derive de categories_cultures (source de verite).
    "categories_cultures": {
        "prairies_ou_luzerne": {"sous_cultures": ["luzerne"]},
        "culture_printemps": {
            "sous_cultures": ["mais", "culture_principale_printemps_autre_que_mais"]
        },
        "couvert_intercultures_longue": {
            "sous_cultures": [
                "couvert_non_recolte_plus_en_place_apres_3112",
                "couvert_non_recolte_toujours_en_place_apres_0101",
            ]
        },
    },
    "mapping_sous_culture_vers_branche": {
        # couvert : 1 seule forme -> sous_culture (non ambigu)
        "couvert_non_recolte_toujours_en_place_apres_0101": {
            "occupation_sol": "couvert_intercultures",
            "sous_culture": "cine_apres_0101",
        },
        "couvert_non_recolte_plus_en_place_apres_3112": {
            "occupation_sol": "couvert_intercultures",
            "sous_culture": "cine_avant_3112",
        },
        "luzerne": {
            "occupation_sol": "culture_principale",
            "sous_culture": "luzerne",
        },
        # culture_printemps : 2 formes -> meme sous_culture (AMBIGU)
        "mais": {
            "occupation_sol": "culture_principale",
            "sous_culture": "culture_printemps",
            "flags": {"culture_irriguee_type": "mais"},
        },
        "culture_principale_printemps_autre_que_mais": {
            "occupation_sol": "culture_principale",
            "sous_culture": "culture_printemps",
        },
    },
    "categories_fertilisants": {
        "fumiers": {
            "sous_fertilisants": [
                "fumier_volaille",
                "fumier_mou_susceptible_ecoulement",
            ]
        },
        "engrais_mineral": {"sous_fertilisants": ["engrais_azote_mineral"]},
    },
}


def test_backfill_couvert_reconstruit_form_et_categorie():
    # Le lien casse du bug #175 : couvert pilote par sous_culture, sans champs front.
    data = {
        "occupation_sol": "couvert_intercultures",
        "sous_culture": "cine_apres_0101",
        "type_fertilisant": "type_Ib",
    }
    out = backfill_form_fields(data, REFERENTIELS)
    # categorie UI = valeur du radio 1er niveau (longue/courte), pas l'occupation_sol
    assert out["categorie_culture"] == "couvert_intercultures_longue"
    assert (
        out["sous_culture_form"] == "couvert_non_recolte_toujours_en_place_apres_0101"
    )


def test_backfill_fertilisant_categorie_depuis_sous_fertilisant():
    data = {
        "sous_culture": "cine_apres_0101",
        "occupation_sol": "couvert_intercultures",
        "sous_fertilisant": "fumier_mou_susceptible_ecoulement",
    }
    out = backfill_form_fields(data, REFERENTIELS)
    assert out["categorie_fertilisant"] == "fumiers"


def test_backfill_nexecrase_pas_les_valeurs_fournies():
    data = {
        "occupation_sol": "couvert_intercultures",
        "sous_culture": "cine_apres_0101",
        "categorie_culture": "DEJA_LA",
        "sous_culture_form": "forme_fournie",
        "sous_fertilisant": "fumier_volaille",
        "categorie_fertilisant": "categorie_fournie",
    }
    out = backfill_form_fields(data, REFERENTIELS)
    assert out["categorie_culture"] == "DEJA_LA"
    assert out["sous_culture_form"] == "forme_fournie"
    assert out["categorie_fertilisant"] == "categorie_fournie"


def test_backfill_ambigu_ne_devine_pas_le_form():
    # culture_printemps <- mais / autre : 2 formes, on ne tranche pas.
    data = {
        "occupation_sol": "culture_principale",
        "sous_culture": "culture_printemps",
    }
    out = backfill_form_fields(data, REFERENTIELS)
    assert not out.get("sous_culture_form")
    # categorie_culture non plus (on ne l'a pas via une forme unique)
    assert not out.get("categorie_culture")


def test_backfill_ne_fabrique_pas_sous_fertilisant_depuis_type():
    # type seul -> jamais de sous_fertilisant invente (info reellement perdue).
    data = {
        "occupation_sol": "couvert_intercultures",
        "sous_culture": "cine_apres_0101",
        "type_fertilisant": "type_II",
    }
    out = backfill_form_fields(data, REFERENTIELS)
    assert not out.get("sous_fertilisant")
    assert not out.get("categorie_fertilisant")


def test_backfill_categorie_depuis_form_fourni_sans_categorie():
    # sous_culture_form fourni mais categorie manquante -> deterministe.
    data = {"sous_culture_form": "luzerne"}
    out = backfill_form_fields(data, REFERENTIELS)
    assert out["categorie_culture"] == "prairies_ou_luzerne"


def test_backfill_data_vide_ne_plante_pas():
    assert backfill_form_fields({}, REFERENTIELS) == {}
    assert backfill_form_fields({}, {}) == {}


def test_backfill_valeurs_non_str_ne_plantent_pas():
    """L'appelant reel passe request.GET.dict() (valeurs str), mais on blinde
    contre un dict a valeurs non-str (liste facon QueryDict brut, None) :
    `_txt` normalise via str(...) au lieu de lever AttributeError sur .strip()."""
    data = {
        "sous_culture": ["cine_apres_0101"],  # liste (QueryDict brut)
        "occupation_sol": None,  # None
        "categorie_culture": ["deja"],  # non vide -> pas ecrase, pas de crash
    }
    # Ne doit pas lever. On ne teste pas le contenu reconstruit (les cles-listes
    # ne matchent pas le referentiel), juste l'absence de crash + preservation.
    out = backfill_form_fields(data, REFERENTIELS)
    assert out["categorie_culture"] == ["deja"]


@pytest.mark.django_db
def test_backfill_avec_referentiels_reels():
    """Integration : sur le vrai referentiel, un lien couvert casse se repare."""
    from envergo.nitrates.yaml_tree import load_referentiels

    ref = load_referentiels()
    data = {
        "occupation_sol": "couvert_intercultures",
        "sous_culture": "cine_apres_0101",
        "sous_fertilisant": "fumier_mou_susceptible_ecoulement",
    }
    out = backfill_form_fields(data, ref)
    assert out["categorie_culture"] == "couvert_intercultures_longue"
    assert out["sous_culture_form"]
    assert out["categorie_fertilisant"]
