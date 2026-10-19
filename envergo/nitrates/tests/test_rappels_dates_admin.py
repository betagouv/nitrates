"""Rappels des dates du couvert dans l'éditeur d'arbres (#407) : panneau de
l'arbre, conditions affichées sur les inputs des feuilles, édition du bloc."""

import copy

import pytest
import yaml
from django.contrib.auth import get_user_model
from django.urls import reverse

from envergo.nitrates.models import DecisionTree, DecisionTreeRevision
from envergo.nitrates.yaml_tree.rappels_dates import rappels_pour_regle

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]

GROUPE = {
    "sous_cultures": ["cine_avant_3112"],
    "source_juridique": "PAR7 Grand Est, article 10",
    "inputs": [
        {"id": "date_semis_couvert", "rappel_max": "30/09"},
        {
            "id": "date_destruction_couvert",
            "rappel_min": ["date_semis_couvert+2mois", "15/10"],
        },
    ],
}


def _calculatrice(rid):
    return {
        "id": rid,
        "type": "calculatrice",
        "composant": "calendrier_dynamique_couvert",
        "inputs_requis": [
            {"id": "date_semis_couvert", "label": "Semis", "type": "date"},
            {"id": "date_destruction_couvert", "label": "Fin", "type": "date"},
        ],
        "periodes": [
            {
                "du": "date_semis_couvert",
                "au": "date_destruction_couvert",
                "regime": "interdiction",
            }
        ],
    }


def _arbre(rappels=True):
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_root",
                "champ": "en_zone_vulnerable",
                "source": "sig",
                "reference": "zone_vulnerable_nitrates",
                "branches": [
                    {
                        "valeur": False,
                        "regle": {"id": "r_hors", "type": "non_applicable"},
                    },
                    {
                        "valeur": True,
                        "noeud": {
                            "type_noeud": "formulaire",
                            "id": "q_sous_culture",
                            "champ": "sous_culture",
                            "niveau": "sous_culture",
                            "texte": "Quel couvert ?",
                            "branches": [
                                {
                                    "valeur": "cine_avant_3112",
                                    "regle": _calculatrice("r_longue"),
                                },
                                {
                                    "valeur": "cine_courte",
                                    "regle": _calculatrice("r_courte"),
                                },
                            ],
                        },
                    },
                ],
            }
        }
    }
    if rappels:
        arbre["rappels_dates"] = [copy.deepcopy(GROUPE)]
    return arbre


@pytest.fixture(autouse=True)
def _purge():
    DecisionTree.objects.all().delete()


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user(
        email="alice@test.local", name="Alice", password="x", is_staff=True
    )


@pytest.fixture
def draft(alice):
    arbre = _arbre()
    return DecisionTree.objects.create(
        name="d",
        status=DecisionTree.STATUS_DRAFT,
        contenu=arbre,
        contenu_yaml_brut="# commentaire conservé\n"
        + yaml.safe_dump(arbre, sort_keys=False, allow_unicode=True),
        created_by=alice,
    )


def _url(tree):
    return reverse(
        "nitrates_admin_yaml_edit_rappels_dates", kwargs={"tree_pk": tree.pk}
    )


def test_rappels_pour_regle_suit_la_sous_culture_de_la_feuille():
    arbre = _arbre()
    longue = rappels_pour_regle(arbre, "r_longue")
    assert longue["date_destruction_couvert"]["conditions"] == [
        "date_destruction_couvert ≥ date_semis_couvert+2mois",
        "date_destruction_couvert ≥ 15/10",
    ]
    assert longue["date_semis_couvert"]["conditions"] == ["date_semis_couvert ≤ 30/09"]
    assert rappels_pour_regle(arbre, "r_courte") == {}


def test_editeur_affiche_panneau_et_conditions_sur_les_inputs(client, alice, draft):
    client.force_login(alice)
    resp = client.get(
        reverse("nitrates_admin_yaml_tree"),
        {"tree_id": draft.pk, "mode": "lecture", "expand_deep": "n_root"},
    )
    html = resp.content.decode()
    assert "Rappels des dates du couvert" in html
    assert "PAR7 Grand Est, article 10" in html
    assert "date_destruction_couvert ≥ date_semis_couvert+2mois" in html
    # Les 2 inputs de la feuille longue portent leur rappel, pas ceux de la courte.
    assert html.count("yaml-tree__input-rappel") == 2


def test_edition_du_bloc_enregistre_contenu_yaml_et_revision(client, alice, draft):
    client.force_login(alice)
    bloc = [
        {
            "sous_cultures": ["cine_avant_3112"],
            "inputs": [
                {
                    "id": "date_destruction_couvert",
                    "rappel_min": ["date_semis_couvert+8semaines", "01/11"],
                }
            ],
        }
    ]
    resp = client.post(_url(draft), {"rappels_dates": yaml.safe_dump(bloc)})
    assert resp.status_code == 200
    draft.refresh_from_db()
    assert draft.contenu["rappels_dates"] == bloc
    assert "date_semis_couvert+8semaines" in draft.contenu_yaml_brut
    assert draft.contenu_yaml_brut.startswith("# commentaire conservé")
    assert DecisionTreeRevision.objects.filter(tree=draft).count() == 1


def test_edition_invalide_refusee(client, alice, draft):
    client.force_login(alice)
    bloc = [
        {
            "sous_cultures": ["cine_avant_3112"],
            "inputs": [{"id": "date_semis_couvert", "rappel_max": "31/09"}],
        }
    ]
    resp = client.post(_url(draft), {"rappels_dates": yaml.safe_dump(bloc)})
    assert "date invalide" in resp.content.decode()
    draft.refresh_from_db()
    assert draft.contenu["rappels_dates"] == [GROUPE]


def test_bloc_vide_supprime_les_rappels(client, alice, draft):
    client.force_login(alice)
    client.post(_url(draft), {"rappels_dates": ""})
    draft.refresh_from_db()
    assert "rappels_dates" not in draft.contenu
    assert "rappels_dates" not in draft.contenu_yaml_brut


def test_edition_interdite_sur_un_arbre_actif(client, alice, draft):
    draft.status = DecisionTree.STATUS_ACTIVE
    draft.save()
    client.force_login(alice)
    resp = client.post(_url(draft), {"rappels_dates": ""})
    assert resp.status_code == 403
