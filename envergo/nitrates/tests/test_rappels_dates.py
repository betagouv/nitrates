"""Rappels réglementaires sous les dates du couvert (#407)."""

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.urls import reverse

from envergo.geodata.models import MAP_TYPES, Department, Map, Zone
from envergo.nitrates.models import DecisionTree
from envergo.nitrates.yaml_tree import ValidationError, validate_arbre
from envergo.nitrates.yaml_tree.rappels_dates import (
    rappels_dates_couvert,
    texte_rappel,
    valider_rappels_dates,
)

LONGUE = ["cine_avant_3112", "cine_apres_0101", "cie_avant_3112", "cie_apres_0101"]

MAPPING = {
    "couvert_recolte_plus_en_place_apres_3112": {"sous_culture": "cie_avant_3112"},
    "couvert_recolte_toujours_en_place_apres_0101": {"sous_culture": "cie_apres_0101"},
    "couvert_non_recolte_plus_en_place_apres_3112": {"sous_culture": "cine_avant_3112"},
    "couvert_non_recolte_toujours_en_place_apres_0101": {
        "sous_culture": "cine_apres_0101"
    },
    "couvert_courte_recolte": {"sous_culture": "cie_courte"},
    "couvert_courte_non_recolte": {"sous_culture": "cine_courte"},
    "colza": {"sous_culture": "colza"},
}


def _arbre(rappels=None):
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
                "source": "sig",
                "reference": "zone_vulnerable_nitrates",
                "branches": [
                    {
                        "valeur": True,
                        "regle": {"id": "r_tout", "type": "libre"},
                    },
                    {
                        "valeur": False,
                        "regle": {"id": "r_hors_zvn", "type": "non_applicable"},
                    },
                ],
            }
        }
    }
    if rappels is not None:
        arbre["rappels_dates"] = rappels
    return arbre


def _groupe(semis_max=None, destruction_min=None, sous_cultures=LONGUE):
    inputs = []
    if semis_max:
        inputs.append({"id": "date_semis_couvert", "rappel_max": semis_max})
    if destruction_min:
        inputs.append({"id": "date_destruction_couvert", "rappel_min": destruction_min})
    return {"sous_cultures": sous_cultures, "inputs": inputs}


PAN = _arbre([_groupe(destruction_min="date_semis_couvert+8semaines")])
PAR_GE = _arbre(
    [_groupe(semis_max="30/09", destruction_min=["date_semis_couvert+2mois", "15/10"])]
)
ZAR_GE = _arbre(
    [
        _groupe(
            semis_max="30/09",
            destruction_min=["date_semis_couvert+11semaines", "15/10"],
        )
    ]
)


# ─── Phrases (textes validés sur la carte #407) ─────────────────────────


def test_texte_semis_grand_est():
    assert texte_rappel("date_semis_couvert", rappel_max="30/09") == (
        "Pour rappel, sauf dérogation, le couvert doit être implanté au plus "
        "tard le 30 septembre inclus."
    )


def test_texte_destruction_grand_est_duree_avant_date_fixe():
    # Ordre de déclaration indifférent : la durée se lit avant la date fixe.
    assert texte_rappel(
        "date_destruction_couvert", rappel_min=["15/10", "date_semis_couvert+2mois"]
    ) == (
        "Pour rappel, sauf dérogation, le couvert doit être maintenu au moins "
        "2 mois après semis et ne peut pas être détruit avant le 15 octobre."
    )


def test_texte_destruction_hauts_de_france_1er_novembre():
    assert texte_rappel(
        "date_destruction_couvert", rappel_min=["date_semis_couvert+8semaines", "01/11"]
    ) == (
        "Pour rappel, sauf dérogation, le couvert doit être maintenu au moins "
        "8 semaines après semis et ne peut pas être détruit avant le 1er novembre."
    )


def test_texte_destruction_au_plus_tard():
    assert texte_rappel("date_destruction_couvert", rappel_max="15/12") == (
        "Pour rappel, sauf dérogation, le couvert doit être détruit au plus "
        "tard le 15 décembre inclus."
    )


def test_texte_vide_sans_borne():
    assert texte_rappel("date_semis_couvert") == ""


# ─── Validation ─────────────────────────────────────────────────────────


def test_bloc_absent_valide():
    assert valider_rappels_dates(_arbre()) == []


def test_bloc_valide():
    assert valider_rappels_dates(PAR_GE, set(LONGUE)) == []


@pytest.mark.parametrize(
    "rappels, attendu",
    [
        ({"sous_cultures": LONGUE}, "liste de groupes"),
        ([{"sous_cultures": [], "inputs": []}], "`sous_cultures`"),
        (
            [_groupe(semis_max="31/09")],
            "date invalide",
        ),
        (
            [_groupe(destruction_min="date_destruction_couvert+2mois")],
            "se borner lui-même",
        ),
        (
            [_groupe(destruction_min="semis+2ans")],
            "ni date JJ/MM",
        ),
        (
            [{"sous_cultures": LONGUE, "inputs": [{"id": "date_semis_couvert"}]}],
            "au moins un de",
        ),
        (
            [{"sous_cultures": LONGUE, "inputs": [{"id": "x", "min": "01/01"}]}],
            "clés inconnues",
        ),
        ([_groupe(semis_max="30/09"), _groupe(semis_max="20/09")], "plusieurs groupes"),
    ],
)
def test_bloc_invalide(rappels, attendu):
    erreurs = valider_rappels_dates(_arbre(rappels))
    assert any(attendu in e for e in erreurs), erreurs


def test_sous_culture_inconnue_du_referentiel():
    erreurs = valider_rappels_dates(PAR_GE, {"cine_avant_3112"})
    assert any("inconnues du référentiel" in e for e in erreurs), erreurs


def test_validate_arbre_branche_le_controle():
    with pytest.raises(ValidationError) as exc:
        validate_arbre(_arbre([_groupe(semis_max="99/99")]), referentiels={})
    assert "[rappels_dates]" in str(exc.value)
    validate_arbre(PAR_GE, referentiels={})


# ─── Cascade ────────────────────────────────────────────────────────────


def test_cascade_arbre_le_plus_specifique_par_input():
    rappels = rappels_dates_couvert([ZAR_GE, PAR_GE, PAN], MAPPING)
    cine = rappels["couvert_non_recolte_plus_en_place_apres_3112"]
    assert "11 semaines" in cine["date_destruction_couvert"]["texte"]
    assert "30 septembre" in cine["date_semis_couvert"]["texte"]


def test_cascade_retombe_sur_le_pan_si_le_par_ne_declare_rien():
    rappels = rappels_dates_couvert([_arbre(), PAN], MAPPING)
    cie = rappels["couvert_recolte_toujours_en_place_apres_0101"]
    assert set(cie) == {"date_destruction_couvert"}
    assert "8 semaines" in cie["date_destruction_couvert"]["texte"]


def test_par_partiel_couvre_toutes_les_sous_cultures_declarees():
    # Le PAR ne surcharge pas forcément les branches CIE : le rappel régional
    # vaut quand même, puisqu'il est porté par l'arbre et non par ses feuilles.
    rappels = rappels_dates_couvert([PAR_GE, PAN], MAPPING)
    cie = rappels["couvert_recolte_plus_en_place_apres_3112"]
    assert "2 mois" in cie["date_destruction_couvert"]["texte"]


def test_interculture_courte_sans_rappel():
    rappels = rappels_dates_couvert([PAR_GE, PAN], MAPPING)
    assert "couvert_courte_recolte" not in rappels
    assert "colza" not in rappels


def test_arbres_sans_bloc():
    assert rappels_dates_couvert([_arbre()], MAPPING) == {}


# ─── Info parcelle (clic carte) ─────────────────────────────────────────

CARRE = ((3.5, 48.5), (5.0, 48.5), (5.0, 49.5), (3.5, 49.5), (3.5, 48.5))


@pytest.fixture
def grand_est(db, monkeypatch):
    DecisionTree.objects.all().delete()
    Department.objects.create(
        department="51", geometry=MultiPolygon(Polygon(CARRE), srid=4326)
    )
    monkeypatch.setattr(
        "envergo.nitrates.views.load_referentiels",
        lambda: {"mapping_sous_culture_vers_branche": MAPPING},
    )
    DecisionTree.objects.create(
        name="pan", status=DecisionTree.STATUS_ACTIVE, weight=1, contenu=PAN
    )
    DecisionTree.objects.create(
        name="par",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_REGION,
        region_code="44",
        weight=10,
        contenu=PAR_GE,
    )


@pytest.mark.urls("config.urls_nitrates")
def test_info_parcelle_expose_les_rappels(client, grand_est):
    resp = client.get(reverse("nitrates_debug"), {"lng": 4.0, "lat": 49.2})
    rappels = resp.json()["rappels_dates_couvert"]
    semis = rappels["couvert_non_recolte_toujours_en_place_apres_0101"][
        "date_semis_couvert"
    ]
    assert semis["texte"].endswith("au plus tard le 30 septembre inclus.")
    assert semis["rappel_max"] == ["30/09"]


@pytest.mark.urls("config.urls_nitrates")
def test_info_parcelle_zar_prime_sur_par(client, grand_est):
    zar_map = Map.objects.create(
        name="zar",
        map_type=MAP_TYPES.zone_action_renforcee,
        description="",
        expected_geometries=1,
        is_active=True,
    )
    Zone.objects.create(map=zar_map, geometry=MultiPolygon(Polygon(CARRE), srid=4326))
    DecisionTree.objects.create(
        name="zar",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_ZAR,
        region_code="44",
        activation_map=zar_map,
        weight=20,
        contenu=ZAR_GE,
    )
    resp = client.get(reverse("nitrates_debug"), {"lng": 4.0, "lat": 49.2})
    data = resp.json()
    assert data["en_zar"] is True
    destruction = data["rappels_dates_couvert"][
        "couvert_non_recolte_plus_en_place_apres_3112"
    ]["date_destruction_couvert"]
    assert "11 semaines" in destruction["texte"]


@pytest.mark.urls("config.urls_nitrates")
def test_info_parcelle_sans_arbre_ne_casse_pas(client, db):
    DecisionTree.objects.all().delete()
    resp = client.get(reverse("nitrates_debug"), {"lng": 4.0, "lat": 49.2})
    assert resp.status_code == 200
    assert resp.json()["rappels_dates_couvert"] == {}
