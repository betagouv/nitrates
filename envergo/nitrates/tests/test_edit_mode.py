"""Tests du mode edition (etape 4 phase 3bis) :
- EditActiveView : entry point qui clone l'actif en draft
- find_or_create_edit_draft : reprend un draft existant si conditions OK
- YamlTreeView en mode edition : check status + lock
- CancelEditView : libere le lock
"""

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


def _make_tree(**overrides) -> DecisionTree:
    defaults = {
        "name": "national",
        "status": DecisionTree.STATUS_ACTIVE,
        "contenu": {"arbre": {"noeud": {"id": "n_root"}}},
        "contenu_yaml_brut": "arbre:\n  noeud:\n    id: n_root\n",
    }
    defaults.update(overrides)
    return DecisionTree.objects.create(**defaults)


# ─── find_or_create_edit_draft ─────────────────────────────────────────────


def test_find_or_create_cree_un_draft_si_aucun(alice):
    active = _make_tree()
    draft = DecisionTree.find_or_create_edit_draft(alice)
    assert draft is not None
    assert draft.status == DecisionTree.STATUS_DRAFT
    assert draft.parent_id == active.pk
    assert draft.created_by_id == alice.pk


def test_find_or_create_reutilise_draft_existant(alice):
    _make_tree()
    first = DecisionTree.find_or_create_edit_draft(alice)
    second = DecisionTree.find_or_create_edit_draft(alice)
    assert first.pk == second.pk


def test_find_or_create_cree_nouveau_si_draft_locked_par_autre(alice, bob):
    _make_tree()
    # Bob cree un draft et le lock
    bob_draft = DecisionTree.find_or_create_edit_draft(bob)
    bob_draft.acquire_lock(bob)
    # Alice arrive : on lui cree un draft separe
    alice_draft = DecisionTree.find_or_create_edit_draft(alice)
    assert alice_draft.pk != bob_draft.pk
    assert alice_draft.created_by_id == alice.pk


def test_find_or_create_returns_none_sans_actif(alice):
    """Aucun arbre actif en DB -> rien a editer."""
    result = DecisionTree.find_or_create_edit_draft(alice)
    assert result is None


# ─── EditActiveView ─────────────────────────────────────────────────────────


def test_edit_active_redirige_vers_viewer_du_draft(client, alice):
    _make_tree()
    client.force_login(alice)
    resp = client.get(reverse("nitrates_admin_yaml_edit_active"))
    assert resp.status_code == 302
    assert "mode=edition" in resp["Location"]
    assert "tree_id=" in resp["Location"]
    drafts = DecisionTree.objects.filter(status=DecisionTree.STATUS_DRAFT)
    assert drafts.count() == 1


def test_edit_active_reutilise_draft_existant(client, alice):
    _make_tree()
    client.force_login(alice)
    client.get(reverse("nitrates_admin_yaml_edit_active"))
    client.get(reverse("nitrates_admin_yaml_edit_active"))
    # 1 seul draft cree au total
    assert DecisionTree.objects.filter(status=DecisionTree.STATUS_DRAFT).count() == 1


# ─── YamlTreeView en mode edition ──────────────────────────────────────────


def test_mode_edition_seulement_sur_drafts(client, alice):
    """Force ?mode=edition sur l'actif : retombe en lecture silencieusement."""
    active = _make_tree()
    client.force_login(alice)
    url = reverse("nitrates_admin_yaml_tree") + f"?tree_id={active.pk}&mode=edition"
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    # Pas de bandeau d'edition affiche
    assert "yaml-admin__edit-banner" not in body


def test_mode_edition_sur_draft_affiche_bandeau(client, alice):
    active = _make_tree()
    draft = DecisionTree.clone_to_draft(active, user=alice)
    client.force_login(alice)
    url = reverse("nitrates_admin_yaml_tree") + f"?tree_id={draft.pk}&mode=edition"
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "yaml-admin__edit-banner" in body
    assert "Édition de" in body
    # Le nom affiche est celui de l'actif (parent), pas du draft
    assert active.name in body


def test_mode_edition_acquiert_lock(client, alice):
    active = _make_tree()
    draft = DecisionTree.clone_to_draft(active, user=alice)
    client.force_login(alice)
    url = reverse("nitrates_admin_yaml_tree") + f"?tree_id={draft.pk}&mode=edition"
    client.get(url)
    draft.refresh_from_db()
    assert draft.locked_by_id == alice.pk


def test_mode_edition_refuse_si_lock_par_autre(client, alice, bob):
    active = _make_tree()
    draft = DecisionTree.clone_to_draft(active, user=bob)
    draft.acquire_lock(bob)
    client.force_login(alice)
    url = reverse("nitrates_admin_yaml_tree") + f"?tree_id={draft.pk}&mode=edition"
    resp = client.get(url)
    body = resp.content.decode()
    # Pas de bandeau d'edition (alice est passe en lecture)
    assert "yaml-admin__edit-banner" not in body
    # Mais un message indiquant que c'est locke
    assert "yaml-admin__lock-warning" in body
    assert "bob@test.local" in body


# ─── Icones d'edition inline ───────────────────────────────────────────────


def test_icones_edition_visibles_seulement_en_edition(client, alice):
    active = _make_tree()
    draft = DecisionTree.clone_to_draft(active, user=alice)
    client.force_login(alice)

    # Lecture : pas d'icones
    body_lecture = client.get(
        reverse("nitrates_admin_yaml_tree") + f"?tree_id={draft.pk}"
    ).content.decode()
    assert "yaml-tree__edit-actions" not in body_lecture

    # Edition : icones presentes
    body_edition = client.get(
        reverse("nitrates_admin_yaml_tree") + f"?tree_id={draft.pk}&mode=edition"
    ).content.decode()
    assert "yaml-tree__edit-actions" in body_edition


# ─── CancelEditView ─────────────────────────────────────────────────────────


def test_cancel_libere_le_lock(client, alice):
    active = _make_tree()
    draft = DecisionTree.clone_to_draft(active, user=alice)
    draft.acquire_lock(alice)
    client.force_login(alice)
    resp = client.post(
        reverse("nitrates_admin_yaml_cancel_edit", kwargs={"pk": draft.pk})
    )
    assert resp.status_code == 302
    draft.refresh_from_db()
    assert draft.locked_by_id is None


def test_cancel_redirige_vers_draft(client, alice):
    """Apres sauvegarde, on revient en lecture sur le DRAFT (pas l'actif).
    Permet de continuer a explorer le brouillon, et de relancer une
    edition via le bouton si besoin. Avant 2026-05-28 on redirigeait
    vers l'actif, ce qui faisait perdre la trace du brouillon edite."""
    active = _make_tree()
    draft = DecisionTree.clone_to_draft(active, user=alice)
    client.force_login(alice)
    resp = client.post(
        reverse("nitrates_admin_yaml_cancel_edit", kwargs={"pk": draft.pk})
    )
    assert resp.status_code == 302
    assert f"tree_id={draft.pk}" in resp["Location"]


def test_cancel_ne_supprime_pas_le_draft(client, alice):
    active = _make_tree()
    draft = DecisionTree.clone_to_draft(active, user=alice)
    client.force_login(alice)
    client.post(reverse("nitrates_admin_yaml_cancel_edit", kwargs={"pk": draft.pk}))
    assert DecisionTree.objects.filter(pk=draft.pk).exists()
