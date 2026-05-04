"""Tests fonctionnels de EditNodeView (etape 5c) : endpoint htmx
d'edition inline d'un noeud."""

import copy

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from envergo.nitrates.models import DecisionTree

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


@pytest.fixture
def base_arbre():
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_root",
                "champ": "z",
                "source": "sig",
                "branches": [
                    {
                        "valeur": True,
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "culture",
                            "id": "q_culture",
                            "champ": "c",
                            "texte": "Culture ?",
                            "branches": [],
                        },
                    }
                ],
            }
        }
    }


@pytest.fixture
def draft(base_arbre, alice):
    return DecisionTree.objects.create(
        name="d",
        status=DecisionTree.STATUS_DRAFT,
        contenu=copy.deepcopy(base_arbre),
        contenu_yaml_brut="placeholder: 1\n",
        created_by=alice,
    )


@pytest.fixture
def url_edit(draft):
    return reverse("nitrates_admin_yaml_edit_node", kwargs={"tree_pk": draft.pk})


# ─── GET formulaire ─────────────────────────────────────────────────────────


def test_get_form_pour_noeud_formulaire(client, alice, draft, url_edit):
    client.force_login(alice)
    resp = client.get(url_edit + "?path=n_root/q_culture")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "yaml-tree__inline-form" in body
    assert 'name="texte"' in body
    assert "Culture ?" in body


def test_get_form_pour_noeud_catalogue(client, alice, draft, url_edit):
    client.force_login(alice)
    resp = client.get(url_edit + "?path=n_root")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'name="source"' in body
    assert "n_root" in body


def test_get_form_lock_acquis(client, alice, draft, url_edit):
    """Un GET sur le form acquiert le lock."""
    client.force_login(alice)
    client.get(url_edit + "?path=n_root/q_culture")
    draft.refresh_from_db()
    assert draft.locked_by_id == alice.pk


def test_get_form_refuse_si_locked_par_autre(client, alice, bob, draft, url_edit):
    draft.acquire_lock(bob)
    client.force_login(alice)
    resp = client.get(url_edit + "?path=n_root/q_culture")
    assert resp.status_code == 403


def test_get_form_refuse_sur_arbre_actif(client, alice, base_arbre, url_edit):
    """L'edition n'est possible que sur des drafts."""
    active = DecisionTree.objects.create(
        name="a",
        status=DecisionTree.STATUS_ACTIVE,
        contenu=copy.deepcopy(base_arbre),
        contenu_yaml_brut="x: 1\n",
    )
    url = reverse("nitrates_admin_yaml_edit_node", kwargs={"tree_pk": active.pk})
    client.force_login(alice)
    resp = client.get(url + "?path=n_root")
    assert resp.status_code == 403


# ─── POST submit ────────────────────────────────────────────────────────────


def test_post_modifie_le_noeud(client, alice, draft, url_edit):
    client.force_login(alice)
    resp = client.post(
        url_edit + "?path=n_root/q_culture",
        {
            "id": "q_culture",
            "niveau": "culture",
            "texte": "Quelle culture est cultivée ?",
            "champ": "occupation_sol",
        },
    )
    assert resp.status_code == 200
    draft.refresh_from_db()
    node = draft.contenu["arbre"]["noeud"]["branches"][0]["noeud"]
    assert node["texte"] == "Quelle culture est cultivée ?"
    assert node["champ"] == "occupation_sol"


def test_post_invalide_renvoie_form_avec_erreurs(client, alice, draft, url_edit):
    """Champ requis vide -> renvoie le form avec erreur, pas de mutation."""
    client.force_login(alice)
    avant = copy.deepcopy(draft.contenu)
    resp = client.post(
        url_edit + "?path=n_root/q_culture",
        {
            "id": "q_culture",
            "niveau": "culture",
            "texte": "",  # champ vide
            "champ": "c",
        },
    )
    assert resp.status_code == 422
    body = resp.content.decode()
    assert "yaml-tree__form-field-error" in body or "form-error" in body
    draft.refresh_from_db()
    assert draft.contenu == avant


def test_post_id_collision_refuse(client, alice, draft, url_edit):
    """On ne peut pas changer l'id pour un id deja pris."""
    client.force_login(alice)
    resp = client.post(
        url_edit + "?path=n_root/q_culture",
        {
            "id": "n_root",  # collision avec la racine
            "niveau": "culture",
            "texte": "x",
            "champ": "c",
        },
    )
    assert resp.status_code == 422


def test_post_renvoie_revision(client, alice, draft, url_edit):
    """Chaque edit reussi enregistre une revision."""
    client.force_login(alice)
    avant = draft.revisions.count()
    client.post(
        url_edit + "?path=n_root/q_culture",
        {
            "id": "q_culture",
            "niveau": "culture",
            "texte": "Texte modifie",
            "champ": "c",
        },
    )
    apres = draft.revisions.count()
    assert apres == avant + 1


# ─── Cancel ─────────────────────────────────────────────────────────────────


def test_cancel_renvoie_la_ligne(client, alice, draft):
    url = reverse("nitrates_admin_yaml_edit_node_cancel", kwargs={"tree_pk": draft.pk})
    client.force_login(alice)
    resp = client.get(url + "?path=n_root/q_culture")
    assert resp.status_code == 200
    body = resp.content.decode()
    # On retrouve le summary avec le row id
    assert "node-row-" in body
    # Le summary contient bien le nom du noeud et son tag
    assert "q_culture" in body


# ─── Acces ──────────────────────────────────────────────────────────────────


def test_anonymous_redirected(client, draft, url_edit):
    resp = client.get(url_edit + "?path=n_root/q_culture")
    assert resp.status_code in (301, 302)
