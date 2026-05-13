"""Tests fonctionnels phase 3bis : intégration des endpoints admin YAML.

Couvre les flows critiques :
  - publication d'un draft (validation deep + transition status)
  - blocage de la publication par une erreur de validation
  - lock concurrent entre 2 staff users
  - transition draft -> active -> archive

Pour les CRUD individuels (édition règle, ajout/suppression noeud), voir
test_edit_node_view.py / test_edit_regle_view.py / test_yaml_admin_editor.py.
"""

import copy
from datetime import timedelta

import pytest
import yaml
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

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


def _arbre_valide():
    """Arbre minimal qui passe le validator deep."""
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
                        "regle": {
                            "id": "r_en_zv",
                            "type": "interdiction",
                            "periodes": [{"du": "15/12", "au": "15/01"}],
                        },
                    },
                ],
            }
        }
    }


def _arbre_invalide_renvoi_casse():
    """Arbre qui pointe vers un id inexistant -> validator refuse."""
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_root",
                "champ": "x",
                "source": "sig",
                "reference": "zone_vulnerable_nitrates",
                "branches": [
                    {"valeur": True, "renvoi_vers": "r_inexistant"},
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


def _make_active(arbre, name="actif_initial"):
    return DecisionTree.objects.create(
        name=name,
        status=DecisionTree.STATUS_ACTIVE,
        contenu=copy.deepcopy(arbre),
        contenu_yaml_brut=_yaml_brut(arbre),
        activated_at=timezone.now(),
    )


# ─── Activation : succès ───────────────────────────────────────────────


def test_activate_draft_valide_passe_en_actif_et_archive_l_ancien(client, alice):
    actif = _make_active(_arbre_valide(), name="ancien")
    draft = _make_draft(_arbre_valide(), alice, name="nouveau")
    client.force_login(alice)
    url = reverse("nitrates_admin_yaml_activate_tree", kwargs={"tree_pk": draft.pk})
    resp = client.post(url)
    assert resp.status_code == 200
    actif.refresh_from_db()
    draft.refresh_from_db()
    assert draft.status == DecisionTree.STATUS_ACTIVE
    assert draft.activated_at is not None
    assert actif.status == DecisionTree.STATUS_ARCHIVE


def test_activate_repond_avec_hx_redirect_vers_le_viewer(client, alice):
    draft = _make_draft(_arbre_valide(), alice)
    client.force_login(alice)
    url = reverse("nitrates_admin_yaml_activate_tree", kwargs={"tree_pk": draft.pk})
    resp = client.post(url)
    assert resp.status_code == 200
    assert "HX-Redirect" in resp
    assert f"tree_id={draft.pk}" in resp["HX-Redirect"]


# ─── Activation : refus ────────────────────────────────────────────────


def test_activate_avec_arbre_invalide_refuse_et_renvoie_panneau_d_erreurs(
    client, alice
):
    draft = _make_draft(_arbre_invalide_renvoi_casse(), alice)
    client.force_login(alice)
    url = reverse("nitrates_admin_yaml_activate_tree", kwargs={"tree_pk": draft.pk})
    resp = client.post(url)
    # Pas de redirect : on reste sur place avec un panneau d'erreurs.
    assert resp.status_code == 200
    assert "HX-Redirect" not in resp
    body = resp.content.decode()
    assert (
        "publication refusée" in body.lower() or "publication refusee" in body.lower()
    )
    assert "r_inexistant" in body
    draft.refresh_from_db()
    assert draft.status == DecisionTree.STATUS_DRAFT


def test_activate_d_un_actif_refuse(client, alice):
    """Seul un draft peut être activé."""
    actif = _make_active(_arbre_valide())
    client.force_login(alice)
    url = reverse("nitrates_admin_yaml_activate_tree", kwargs={"tree_pk": actif.pk})
    resp = client.post(url)
    assert resp.status_code == 403


def test_activate_par_non_staff_refuse(client, alice, db):
    """Un user non-staff ne peut pas publier."""
    draft = _make_draft(_arbre_valide(), alice)
    user = get_user_model().objects.create_user(
        email="user@test.local", name="User", password="x"
    )
    client.force_login(user)
    url = reverse("nitrates_admin_yaml_activate_tree", kwargs={"tree_pk": draft.pk})
    resp = client.post(url)
    # staff_member_required redirige vers la login admin
    assert resp.status_code in (302, 403)


# ─── Lock concurrent ──────────────────────────────────────────────────


def test_lock_acquis_par_alice_bloque_bob(client, alice, bob):
    draft = _make_draft(_arbre_valide(), alice)
    # Alice prend le lock implicite via _check_editable
    draft.acquire_lock(alice)
    # Bob essaie d'éditer un noeud du draft
    client.force_login(bob)
    url = reverse("nitrates_admin_yaml_edit_node", kwargs={"tree_pk": draft.pk})
    resp = client.get(f"{url}?path=n_root")
    assert resp.status_code == 403
    body = resp.content.decode()
    assert "verrouill" in body.lower()


def test_lock_release_libere_pour_bob(client, alice, bob):
    draft = _make_draft(_arbre_valide(), alice)
    draft.acquire_lock(alice)
    draft.release_lock(alice)
    client.force_login(bob)
    url = reverse("nitrates_admin_yaml_edit_node", kwargs={"tree_pk": draft.pk})
    resp = client.get(f"{url}?path=n_root")
    # Bob peut maintenant éditer
    assert resp.status_code == 200


def test_lock_expire_apres_timeout(client, alice, bob):
    """Si Alice n'a pas touché le draft depuis longtemps, Bob peut prendre la main."""
    draft = _make_draft(_arbre_valide(), alice)
    draft.acquire_lock(alice)
    # On simule un lock vieux : on rembobine le timestamp au-delà du timeout.
    expired = timezone.now() - DecisionTree.LOCK_TIMEOUT - timedelta(seconds=10)
    DecisionTree.objects.filter(pk=draft.pk).update(locked_at=expired)
    draft.refresh_from_db()
    client.force_login(bob)
    url = reverse("nitrates_admin_yaml_edit_node", kwargs={"tree_pk": draft.pk})
    resp = client.get(f"{url}?path=n_root")
    assert resp.status_code == 200


# ─── Transitions de statut ─────────────────────────────────────────────


def test_transition_draft_active_archive_chain(client, alice):
    """Cycle complet : 2 drafts successifs publient, l'archive cumule."""
    actif = _make_active(_arbre_valide(), name="v0")
    draft1 = _make_draft(_arbre_valide(), alice, name="v1")
    draft2 = _make_draft(_arbre_valide(), alice, name="v2")
    client.force_login(alice)

    # Publier draft1
    url1 = reverse("nitrates_admin_yaml_activate_tree", kwargs={"tree_pk": draft1.pk})
    client.post(url1)
    actif.refresh_from_db()
    draft1.refresh_from_db()
    assert actif.status == DecisionTree.STATUS_ARCHIVE
    assert draft1.status == DecisionTree.STATUS_ACTIVE

    # Publier draft2 -> draft1 archive a son tour
    url2 = reverse("nitrates_admin_yaml_activate_tree", kwargs={"tree_pk": draft2.pk})
    client.post(url2)
    draft1.refresh_from_db()
    draft2.refresh_from_db()
    assert draft1.status == DecisionTree.STATUS_ARCHIVE
    assert draft2.status == DecisionTree.STATUS_ACTIVE
    # Les 2 versions précédentes restent en archive
    assert DecisionTree.objects.filter(status=DecisionTree.STATUS_ARCHIVE).count() == 2
