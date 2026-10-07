"""Tests de couverture pour les endpoints htmx moins exercés de
views_admin_yaml_edit.py : édition brute YAML, cibles de renvoi cross-arbre,
réordonnancement/suppression de branches et de nœuds, validation deep.

Complète test_edit_node_view.py / test_patch_ui.py / test_phase_3bis_fonctionnel.py
sans les dupliquer : on cible ici des endpoints qui n'avaient pas (ou peu) de
test fonctionnel dédié d'après le rapport de couverture."""

import copy

import pytest
import yaml
from django.contrib.auth import get_user_model
from django.urls import reverse

from envergo.nitrates.models import DecisionTree, DecisionTreeRevision
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


@pytest.fixture
def bob(db):
    return get_user_model().objects.create_user(
        email="bob@test.local", name="Bob", password="x", is_staff=True
    )


def _arbre_valide():
    """Arbre minimal qui passe le validator deep, avec un noeud intermediaire
    `q_culture` portant deux branches -- utile pour reorder/delete."""
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
                        "regle": {
                            "id": "r_hors_zv",
                            "type": "non_applicable",
                        },
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
                                {
                                    "valeur": "ble",
                                    "renvoi_vers": "r_mais",
                                },
                            ],
                        },
                    },
                ],
            }
        }
    }


def _yaml_brut(arbre):
    return yaml.safe_dump(arbre, sort_keys=False, allow_unicode=True)


def _make_draft(arbre, user, name="d"):
    return DecisionTree.objects.create(
        name=name,
        status=DecisionTree.STATUS_DRAFT,
        contenu=copy.deepcopy(arbre),
        contenu_yaml_brut=_yaml_brut(arbre),
        created_by=user,
    )


@pytest.fixture
def draft(alice):
    return _make_draft(_arbre_valide(), alice)


# ─── EditRawYamlView ────────────────────────────────────────────────────────


def _url_raw(tree):
    return reverse("nitrates_admin_yaml_edit_raw", kwargs={"tree_pk": tree.pk})


def test_edit_raw_yaml_vide_refuse(client, alice, draft):
    client.force_login(alice)
    resp = client.post(_url_raw(draft), {"contenu_yaml_brut": "   "})
    assert resp.status_code == 200
    assert "ne peut pas être vide" in resp.content.decode()
    draft.refresh_from_db()
    assert draft.contenu["arbre"]["noeud"]["id"] == "n_root"  # inchangé


def test_edit_raw_yaml_invalide_syntaxe(client, alice, draft):
    client.force_login(alice)
    resp = client.post(
        _url_raw(draft), {"contenu_yaml_brut": "arbre: [ceci: ne: ferme: pas"}
    )
    assert resp.status_code == 200
    assert "Parse YAML" in resp.content.decode()


def test_edit_raw_yaml_racine_non_dict_refuse(client, alice, draft):
    client.force_login(alice)
    resp = client.post(_url_raw(draft), {"contenu_yaml_brut": "- un\n- deux\n"})
    assert resp.status_code == 200
    assert "doit être un dict" in resp.content.decode()


def test_edit_raw_yaml_echec_validation_deep(client, alice, draft):
    """YAML syntaxiquement correct mais qui ne passe pas le validateur
    profond (renvoi_vers vers un id inexistant) : refusé, draft inchangé."""
    arbre_casse = {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_root",
                "champ": "x",
                "source": "sig",
                "reference": "zone_vulnerable_nitrates",
                "branches": [{"valeur": True, "renvoi_vers": "r_inexistant"}],
            }
        }
    }
    client.force_login(alice)
    resp = client.post(_url_raw(draft), {"contenu_yaml_brut": _yaml_brut(arbre_casse)})
    assert resp.status_code == 200
    draft.refresh_from_db()
    assert draft.contenu["arbre"]["noeud"]["id"] == "n_root"
    assert draft.contenu["arbre"]["noeud"]["branches"][1]["noeud"]["id"] == "q_culture"


def test_edit_raw_yaml_succes_enregistre_et_cree_une_revision(client, alice, draft):
    nouvel_arbre = _arbre_valide()
    nouvel_arbre["arbre"]["noeud"]["champ"] = "en_zone_vulnerable_modifie"
    client.force_login(alice)
    nb_revisions_avant = DecisionTreeRevision.objects.filter(tree=draft).count()
    resp = client.post(_url_raw(draft), {"contenu_yaml_brut": _yaml_brut(nouvel_arbre)})
    assert resp.status_code == 200
    assert "enregistré et validé" in resp.content.decode()
    draft.refresh_from_db()
    assert draft.contenu["arbre"]["noeud"]["champ"] == "en_zone_vulnerable_modifie"
    assert (
        DecisionTreeRevision.objects.filter(tree=draft).count()
        == nb_revisions_avant + 1
    )


def test_edit_raw_yaml_refuse_si_locked_par_un_autre(client, alice, bob, draft):
    draft.acquire_lock(bob)
    client.force_login(alice)
    resp = client.post(
        _url_raw(draft), {"contenu_yaml_brut": _yaml_brut(_arbre_valide())}
    )
    assert resp.status_code == 403


def test_edit_raw_yaml_refuse_sur_arbre_actif(client, alice):
    actif = DecisionTree.objects.create(
        name="a",
        status=DecisionTree.STATUS_ACTIVE,
        contenu=_arbre_valide(),
        contenu_yaml_brut=_yaml_brut(_arbre_valide()),
    )
    client.force_login(alice)
    resp = client.post(
        _url_raw(actif), {"contenu_yaml_brut": _yaml_brut(_arbre_valide())}
    )
    assert resp.status_code == 403


# ─── NoeudsCiblesView ───────────────────────────────────────────────────────


def test_noeuds_cibles_scope_invalide(client, alice):
    client.force_login(alice)
    url = reverse("nitrates_admin_noeuds_cibles", kwargs={"scope": "pas_un_scope"})
    resp = client.get(url)
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_noeuds_cibles_sans_arbre_actif_liste_vide(client, alice):
    client.force_login(alice)
    url = reverse(
        "nitrates_admin_noeuds_cibles",
        kwargs={"scope": DecisionTree.SCOPE_NATIONAL},
    )
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.json() == {"noeuds": []}


def test_noeuds_cibles_collecte_les_noeuds_de_l_arbre_actif(client, alice):
    DecisionTree.objects.create(
        name="actif",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_NATIONAL,
        contenu=_arbre_valide(),
        contenu_yaml_brut=_yaml_brut(_arbre_valide()),
    )
    client.force_login(alice)
    url = reverse(
        "nitrates_admin_noeuds_cibles",
        kwargs={"scope": DecisionTree.SCOPE_NATIONAL},
    )
    resp = client.get(url)
    assert resp.status_code == 200
    data = resp.json()["noeuds"]
    ids = {n["id"] for n in data}
    # n_root (catalogue) et q_culture (formulaire) sont des noeuds
    # atterrissables ; r_mais est une regle, pas un noeud -> absent.
    assert ids == {"n_root", "q_culture"}
    libelle_culture = next(n["label"] for n in data if n["id"] == "q_culture")
    assert libelle_culture == "q_culture — Quelle culture ?"


# ─── ReorderBranchesView ───────────────────────────────────────────────────


def _url_reorder(tree):
    return reverse("nitrates_admin_yaml_reorder_branches", kwargs={"tree_pk": tree.pk})


def test_reorder_sans_ordre_refuse(client, alice, draft):
    client.force_login(alice)
    resp = client.post(_url_reorder(draft) + "?path=n_root/q_culture", {"order": ""})
    assert resp.status_code == 403


def test_reorder_valeurs_incompletes_refuse(client, alice, draft):
    client.force_login(alice)
    resp = client.post(
        _url_reorder(draft) + "?path=n_root/q_culture", {"order": "mais"}
    )
    assert resp.status_code == 403
    draft.refresh_from_db()
    valeurs = [
        b["valeur"]
        for b in draft.contenu["arbre"]["noeud"]["branches"][1]["noeud"]["branches"]
    ]
    assert valeurs == ["mais", "ble"]


def test_reorder_succes_permute_les_branches(client, alice, draft):
    client.force_login(alice)
    resp = client.post(
        _url_reorder(draft) + "?path=n_root/q_culture", {"order": "ble,mais"}
    )
    assert resp.status_code == 200
    draft.refresh_from_db()
    valeurs = [
        b["valeur"]
        for b in draft.contenu["arbre"]["noeud"]["branches"][1]["noeud"]["branches"]
    ]
    assert valeurs == ["ble", "mais"]


# ─── DeleteBrancheView ──────────────────────────────────────────────────────


def _url_delete_branche(tree):
    return reverse("nitrates_admin_yaml_delete_branche", kwargs={"tree_pk": tree.pk})


def test_delete_branche_succes(client, alice, draft):
    client.force_login(alice)
    resp = client.post(_url_delete_branche(draft) + "?path=n_root/q_culture&valeur=ble")
    assert resp.status_code == 200
    draft.refresh_from_db()
    valeurs = [
        b["valeur"]
        for b in draft.contenu["arbre"]["noeud"]["branches"][1]["noeud"]["branches"]
    ]
    assert valeurs == ["mais"]


def test_delete_branche_introuvable_refuse(client, alice, draft):
    client.force_login(alice)
    resp = client.post(
        _url_delete_branche(draft) + "?path=n_root/q_culture&valeur=orge"
    )
    assert resp.status_code == 403


# ─── DeleteNodeView ─────────────────────────────────────────────────────────


def _url_delete_node(tree):
    return reverse("nitrates_admin_yaml_delete_node", kwargs={"tree_pk": tree.pk})


def test_delete_node_supprime_le_noeud_et_sa_branche(client, alice, draft):
    client.force_login(alice)
    resp = client.post(_url_delete_node(draft) + "?path=n_root/q_culture")
    assert resp.status_code == 200
    assert "supprimé" in resp.content.decode()
    draft.refresh_from_db()
    racine = draft.contenu["arbre"]["noeud"]
    # La branche valeur=True (qui portait q_culture) a disparu.
    assert [b["valeur"] for b in racine["branches"]] == [False]


def test_delete_node_introuvable_refuse(client, alice, draft):
    client.force_login(alice)
    resp = client.post(_url_delete_node(draft) + "?path=n_root/q_inexistant")
    assert resp.status_code == 403


# ─── ValidateTreeView ───────────────────────────────────────────────────────


def _url_validate(tree):
    return reverse("nitrates_admin_yaml_validate_tree", kwargs={"tree_pk": tree.pk})


def test_validate_tree_arbre_valide_aucune_erreur(client, alice, draft):
    client.force_login(alice)
    resp = client.post(_url_validate(draft))
    assert resp.status_code == 200
    assert resp.context["errors"] == []


def test_validate_tree_arbre_invalide_humanise_l_erreur(client, alice, draft):
    arbre_casse = draft.contenu
    arbre_casse["arbre"]["noeud"]["branches"][1]["noeud"]["branches"][1][
        "renvoi_vers"
    ] = "r_inexistant"
    draft.contenu = arbre_casse
    draft.contenu_yaml_brut = _yaml_brut(arbre_casse)
    draft.save(update_fields=["contenu", "contenu_yaml_brut"])
    client.force_login(alice)
    resp = client.post(_url_validate(draft))
    assert resp.status_code == 200
    errors = resp.context["errors"]
    assert len(errors) >= 1
    assert any(e["kind"] == "renvoi_vers" for e in errors)


def test_validate_tree_refuse_sur_arbre_non_draft(client, alice):
    actif = DecisionTree.objects.create(
        name="a",
        status=DecisionTree.STATUS_ACTIVE,
        contenu=_arbre_valide(),
        contenu_yaml_brut=_yaml_brut(_arbre_valide()),
    )
    client.force_login(alice)
    resp = client.post(_url_validate(actif))
    assert resp.status_code == 403


# ─── ConvertNodeView : verrou ───────────────────────────────────────────────


def test_convert_node_refuse_si_locked_par_un_autre(client, alice, bob, draft):
    draft.acquire_lock(bob)
    client.force_login(alice)
    url = reverse(
        "nitrates_admin_yaml_convert_catalogue_parametre",
        kwargs={"tree_pk": draft.pk},
    )
    resp = client.post(url + "?path=n_root/q_culture")
    assert resp.status_code == 403


# ─── InsertParentView ───────────────────────────────────────────────────────


def _url_insert_parent(tree):
    return reverse("nitrates_admin_yaml_insert_parent", kwargs={"tree_pk": tree.pk})


def test_insert_parent_get_formulaire(client, alice, draft):
    client.force_login(alice)
    resp = client.get(_url_insert_parent(draft) + "?path=n_root/q_culture")
    assert resp.status_code == 200


def test_insert_parent_racine_refusee(client, alice, draft):
    client.force_login(alice)
    resp = client.get(_url_insert_parent(draft))
    assert resp.status_code == 403
    assert "racine" in resp.content.decode()


def test_insert_parent_post_kind_invalide_refuse(client, alice, draft):
    client.force_login(alice)
    resp = client.post(
        _url_insert_parent(draft) + "?path=n_root/q_culture",
        {"kind": "kind_inexistant"},
    )
    assert resp.status_code == 422


# ─── ChangeBranchContentView ────────────────────────────────────────────────


def _url_change_content(tree):
    return reverse("nitrates_admin_yaml_change_content", kwargs={"tree_pk": tree.pk})


def test_change_content_get_preselectionne_le_kind_courant(client, alice, draft):
    client.force_login(alice)
    resp = client.get(_url_change_content(draft) + "?path=n_root/q_culture&valeur=ble")
    assert resp.status_code == 200
    assert resp.context["selected_kind"] == "renvoi_vers"


def test_change_content_refuse_si_branche_porte_un_sous_arbre(client, alice, draft):
    client.force_login(alice)
    # La branche valeur=True de n_root porte le sous-arbre q_culture.
    resp = client.get(_url_change_content(draft) + "?path=n_root&valeur=True")
    assert resp.status_code == 403


def test_change_content_post_kind_invalide_refuse(client, alice, draft):
    client.force_login(alice)
    resp = client.post(
        _url_change_content(draft) + "?path=n_root/q_culture&valeur=ble",
        {"kind": "kind_inexistant"},
    )
    assert resp.status_code == 422


def test_change_content_post_bascule_renvoi_vers_en_feuille_vide(client, alice, draft):
    client.force_login(alice)
    resp = client.post(
        _url_change_content(draft) + "?path=n_root/q_culture&valeur=ble",
        {"kind": "feuille_vide"},
    )
    assert resp.status_code == 200
    draft.refresh_from_db()
    branche = editor.get_branche_at(draft.contenu, ("n_root", "q_culture"), "ble")
    assert "renvoi_vers" not in branche
    assert branche.get("feuille_vide") is True or "feuille_vide" in branche


# ─── Vues "Cancel" (pas de mutation, juste un re-render de zone vide) ──────


def test_cancel_insert_parent_renvoie_la_zone_vide(client, alice, draft):
    client.force_login(alice)
    url = reverse(
        "nitrates_admin_yaml_insert_parent_cancel", kwargs={"tree_pk": draft.pk}
    )
    resp = client.get(url + "?path=n_root/q_culture")
    assert resp.status_code == 200
    assert "insert-parent-zone-" in resp.content.decode()


def test_cancel_change_content_renvoie_la_zone_vide(client, alice, draft):
    client.force_login(alice)
    url = reverse(
        "nitrates_admin_yaml_change_content_cancel", kwargs={"tree_pk": draft.pk}
    )
    resp = client.get(url + "?path=n_root/q_culture&valeur=ble")
    assert resp.status_code == 200
    assert "change-content-zone-" in resp.content.decode()


def test_cancel_edit_regle_renvoie_le_bloc_en_lecture(client, alice, draft):
    client.force_login(alice)
    url = reverse("nitrates_admin_yaml_edit_regle_cancel", kwargs={"tree_pk": draft.pk})
    resp = client.get(url + "?path=n_root/q_culture&valeur=mais")
    assert resp.status_code == 200
    assert "r_mais" in resp.content.decode()


def test_cancel_edit_regle_sans_regle_renvoie_204(client, alice, draft):
    client.force_login(alice)
    url = reverse("nitrates_admin_yaml_edit_regle_cancel", kwargs={"tree_pk": draft.pk})
    resp = client.get(url + "?path=n_root/q_culture&valeur=ble")
    assert resp.status_code == 204
