"""Deuxième lot de tests de couverture pour views_admin_yaml_edit.py : erreurs
de formulaire d'AddChildView, construction du contenu d'une règle complète via
_build_content_data, bascule vers renvoi_arbre, et quelques branches d'erreur
d'EditNodeView (noeud catalogue, formulaire invalide)."""

import copy

import pytest
import yaml
from django.contrib.auth import get_user_model
from django.urls import reverse

from envergo.nitrates.models import DecisionTree
from envergo.nitrates.yaml_admin import editor

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]


@pytest.fixture(autouse=True)
def _purge():
    DecisionTree.objects.all().delete()


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user(
        email="alice@test.local", name="Alice", password="x", is_staff=True
    )


def _arbre_valide():
    return {
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
                        "regle": {"id": "r_hors_zv", "type": "non_applicable"},
                    },
                    {
                        "valeur": True,
                        "noeud": {
                            "type_noeud": "formulaire",
                            "id": "q_culture",
                            "champ": "occupation_sol",
                            "niveau": "culture",
                            "texte": "Quelle culture ?",
                            "branches": [
                                {
                                    "valeur": "mais",
                                    "regle": {
                                        "id": "r_mais",
                                        "type": "interdiction",
                                        "periodes": [{"du": "15/12", "au": "15/01"}],
                                    },
                                },
                                {"valeur": "ble", "renvoi_vers": "r_mais"},
                            ],
                        },
                    },
                ],
            }
        }
    }


def _yaml_brut(arbre):
    return yaml.safe_dump(arbre, sort_keys=False, allow_unicode=True)


@pytest.fixture
def draft(alice):
    arbre = _arbre_valide()
    return DecisionTree.objects.create(
        name="d",
        status=DecisionTree.STATUS_DRAFT,
        contenu=copy.deepcopy(arbre),
        contenu_yaml_brut=_yaml_brut(arbre),
        created_by=alice,
    )


def _url_add_child(tree):
    return reverse("nitrates_admin_yaml_add_child", kwargs={"tree_pk": tree.pk})


# ─── AddChildView : erreurs de formulaire ───────────────────────────────────


def test_add_child_valeur_vide_refuse(client, alice, draft):
    client.force_login(alice)
    resp = client.post(
        _url_add_child(draft) + "?path=n_root/q_culture",
        {"kind": "regle", "valeur": ""},
    )
    assert resp.status_code == 422
    assert "requise" in resp.content.decode()


def test_add_child_valeur_en_collision_refuse(client, alice, draft):
    client.force_login(alice)
    resp = client.post(
        _url_add_child(draft) + "?path=n_root/q_culture",
        {"kind": "regle", "valeur": "mais"},
    )
    assert resp.status_code == 422
    assert "existe deja" in resp.content.decode()


def test_add_child_kind_non_autorise_refuse(client, alice, draft):
    client.force_login(alice)
    resp = client.post(
        _url_add_child(draft) + "?path=n_root/q_culture",
        {"kind": "kind_inexistant", "valeur": "orge"},
    )
    assert resp.status_code == 422


def test_add_child_regle_complete_construit_le_contenu_attendu(client, alice, draft):
    """Exercice _build_content_data(kind='regle', ...) avec periodes, plafond,
    composant et inputs_requis -- vérifie le contenu réellement écrit en DB."""
    client.force_login(alice)
    resp = client.post(
        _url_add_child(draft) + "?path=n_root/q_culture",
        {
            "kind": "regle",
            "valeur": "orge",
            "c_id": "r_orge",
            "c_type": "plafonnement",
            "c_periodes-0-du": "01/03",
            "c_periodes-0-au": "30/04",
            "c_periodes-0-regime": "autorisation",
            "c_plafond_azote_kg_n_ha": "120",
            "c_composant": "luzerne_post_coupe",
            "c_inputs_requis": "date_semis, date_destruction",
            "c_note": "note_5",
        },
    )
    assert resp.status_code == 200
    draft.refresh_from_db()
    branche = editor.get_branche_at(draft.contenu, ("n_root", "q_culture"), "orge")
    regle = branche["regle"]
    assert regle["id"] == "r_orge"
    assert regle["type"] == "plafonnement"
    assert regle["periodes"] == [
        {"du": "01/03", "au": "30/04", "regime": "autorisation"}
    ]
    assert regle["plafond_azote_kg_n_ha"] == 120.0
    assert regle["composant"] == "luzerne_post_coupe"
    assert regle["inputs_requis"] == ["date_semis", "date_destruction"]
    assert regle["note"] == "note_5"


def test_add_child_regle_plafond_non_numerique_est_ignore(client, alice, draft):
    """Un plafond non convertible en float est silencieusement ignoré (pas
    de 500, pas de clé ajoutée)."""
    client.force_login(alice)
    resp = client.post(
        _url_add_child(draft) + "?path=n_root/q_culture",
        {
            "kind": "regle",
            "valeur": "orge",
            "c_id": "r_orge",
            "c_type": "plafonnement",
            "c_plafond_azote_kg_n_ha": "pas-un-nombre",
        },
    )
    assert resp.status_code == 200
    draft.refresh_from_db()
    branche = editor.get_branche_at(draft.contenu, ("n_root", "q_culture"), "orge")
    assert "plafond_azote_kg_n_ha" not in branche["regle"]


def test_add_child_catalogue_parametre_sans_expression_refuse(client, alice):
    """Sous un noeud catalogue_parametre, une expression est requise."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue_parametre",
                "id": "n_root",
                "champ": "x",
                "branches": [
                    {
                        "valeur": "a",
                        "expression": "True",
                        "regle": {"id": "r_a", "type": "non_applicable"},
                    }
                ],
            }
        }
    }
    draft = DecisionTree.objects.create(
        name="d2",
        status=DecisionTree.STATUS_DRAFT,
        contenu=copy.deepcopy(arbre),
        contenu_yaml_brut=_yaml_brut(arbre),
    )
    client.force_login(alice)
    resp = client.post(
        _url_add_child(draft) + "?path=n_root",
        {"kind": "regle", "valeur": "b"},
    )
    assert resp.status_code == 422
    assert "expression est requise" in resp.content.decode()


def test_add_child_catalogue_parametre_expression_invalide_refuse(client, alice):
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue_parametre",
                "id": "n_root",
                "champ": "x",
                "branches": [
                    {
                        "valeur": "a",
                        "expression": "True",
                        "regle": {"id": "r_a", "type": "non_applicable"},
                    }
                ],
            }
        }
    }
    draft = DecisionTree.objects.create(
        name="d3",
        status=DecisionTree.STATUS_DRAFT,
        contenu=copy.deepcopy(arbre),
        contenu_yaml_brut=_yaml_brut(arbre),
    )
    client.force_login(alice)
    resp = client.post(
        _url_add_child(draft) + "?path=n_root",
        {"kind": "regle", "valeur": "b", "expression": "import os"},
    )
    assert resp.status_code == 422


# ─── ChangeBranchContentView : bascule vers renvoi_arbre ───────────────────


def test_change_content_post_bascule_vers_renvoi_arbre_avec_noeud_cible(
    client, alice, draft
):
    client.force_login(alice)
    url = reverse("nitrates_admin_yaml_change_content", kwargs={"tree_pk": draft.pk})
    resp = client.post(
        url + "?path=n_root/q_culture&valeur=ble",
        {
            "kind": "renvoi_arbre",
            "c_renvoi_arbre": DecisionTree.SCOPE_REGION,
            "c_noeud_cible": "n_cible_region",
        },
    )
    assert resp.status_code == 200
    draft.refresh_from_db()
    branche = editor.get_branche_at(draft.contenu, ("n_root", "q_culture"), "ble")
    assert branche["renvoi_arbre"] == DecisionTree.SCOPE_REGION
    assert branche["noeud_cible"] == "n_cible_region"
    assert "renvoi_vers" not in branche


# ─── EditNodeView : branches peu exercées ──────────────────────────────────


def _url_edit_node(tree):
    return reverse("nitrates_admin_yaml_edit_node", kwargs={"tree_pk": tree.pk})


def test_edit_node_get_introuvable_refuse(client, alice, draft):
    client.force_login(alice)
    resp = client.get(_url_edit_node(draft) + "?path=n_inexistant")
    assert resp.status_code == 403


def test_edit_node_post_introuvable_refuse(client, alice, draft):
    client.force_login(alice)
    resp = client.post(_url_edit_node(draft) + "?path=n_inexistant")
    assert resp.status_code == 403


def test_edit_node_post_noeud_catalogue_modifie_champ_et_reference(
    client, alice, draft
):
    client.force_login(alice)
    resp = client.post(
        _url_edit_node(draft) + "?path=n_root",
        {
            "id": "n_root",
            "champ": "en_zone_vulnerable_v2",
            "source": "sig",
            "reference": "zone_vulnerable_nitrates_v2",
        },
    )
    assert resp.status_code == 200
    draft.refresh_from_db()
    racine = draft.contenu["arbre"]["noeud"]
    assert racine["champ"] == "en_zone_vulnerable_v2"
    assert racine["reference"] == "zone_vulnerable_nitrates_v2"


def test_edit_node_post_formulaire_niveau_invalide_refuse(client, alice, draft):
    client.force_login(alice)
    resp = client.post(
        _url_edit_node(draft) + "?path=n_root/q_culture",
        {
            "id": "q_culture",
            "niveau": "pas_un_niveau_valide",
            "texte": "Quelle culture ?",
        },
    )
    assert resp.status_code == 422
