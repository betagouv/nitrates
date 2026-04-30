"""Tests du lock d'edition sur DecisionTree (phase 3bis)."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from envergo.nitrates.models import DecisionTree

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _purge_decision_trees():
    DecisionTree.objects.all().delete()


def _make_tree(**overrides) -> DecisionTree:
    defaults = {
        "name": "test_tree",
        "status": DecisionTree.STATUS_DRAFT,
        "contenu": {"arbre": {"noeud": {"id": "n_test"}}},
        "contenu_yaml_brut": "",
    }
    defaults.update(overrides)
    return DecisionTree.objects.create(**defaults)


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


# ─── acquire_lock ──────────────────────────────────────────────────────────


def test_acquire_lock_libre(alice):
    tree = _make_tree()
    assert tree.acquire_lock(alice) is True
    assert tree.locked_by_id == alice.pk
    assert tree.locked_at is not None


def test_acquire_lock_par_meme_user_idempotent(alice):
    """Si user a deja le lock, re-acquire le rafraichit."""
    tree = _make_tree()
    tree.acquire_lock(alice)
    first_at = tree.locked_at
    # On force un decalage minimal pour verifier le refresh
    tree.locked_at = first_at - timedelta(seconds=10)
    tree.save(update_fields=["locked_at"])
    assert tree.acquire_lock(alice) is True
    tree.refresh_from_db()
    assert tree.locked_at > first_at - timedelta(seconds=10)


def test_acquire_lock_refuse_si_autre_user(alice, bob):
    tree = _make_tree()
    assert tree.acquire_lock(alice) is True
    tree2 = DecisionTree.objects.get(pk=tree.pk)
    assert tree2.acquire_lock(bob) is False
    tree2.refresh_from_db()
    assert tree2.locked_by_id == alice.pk


def test_acquire_lock_ok_si_lock_expire(alice, bob):
    tree = _make_tree()
    tree.acquire_lock(alice)
    # Force expiration
    tree.locked_at = timezone.now() - DecisionTree.LOCK_TIMEOUT - timedelta(minutes=1)
    tree.save(update_fields=["locked_at"])
    tree2 = DecisionTree.objects.get(pk=tree.pk)
    assert tree2.acquire_lock(bob) is True
    tree2.refresh_from_db()
    assert tree2.locked_by_id == bob.pk


# ─── release_lock ──────────────────────────────────────────────────────────


def test_release_lock_par_proprietaire(alice):
    tree = _make_tree()
    tree.acquire_lock(alice)
    tree.release_lock(alice)
    tree.refresh_from_db()
    assert tree.locked_by_id is None
    assert tree.locked_at is None


def test_release_lock_par_autre_noop(alice, bob):
    tree = _make_tree()
    tree.acquire_lock(alice)
    tree.release_lock(bob)
    tree.refresh_from_db()
    assert tree.locked_by_id == alice.pk


# ─── is_locked_by_other ─────────────────────────────────────────────────────


def test_is_locked_by_other_libre(alice):
    tree = _make_tree()
    assert tree.is_locked_by_other(alice) is False


def test_is_locked_by_other_meme_user(alice):
    tree = _make_tree()
    tree.acquire_lock(alice)
    assert tree.is_locked_by_other(alice) is False


def test_is_locked_by_other_autre_user(alice, bob):
    tree = _make_tree()
    tree.acquire_lock(alice)
    tree.refresh_from_db()
    assert tree.is_locked_by_other(bob) is True


def test_is_locked_by_other_lock_expire(alice, bob):
    tree = _make_tree()
    tree.acquire_lock(alice)
    tree.locked_at = timezone.now() - DecisionTree.LOCK_TIMEOUT - timedelta(seconds=1)
    tree.save(update_fields=["locked_at"])
    tree.refresh_from_db()
    assert tree.is_locked_by_other(bob) is False
