"""Tests du modele DecisionTreeRevision : record/restore/auto-purge."""

import pytest
from django.contrib.auth import get_user_model

from envergo.nitrates.models import DecisionTree, DecisionTreeRevision

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _purge():
    DecisionTree.objects.all().delete()


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user(
        email="alice@test.local", name="Alice", password="x", is_staff=True
    )


def _make_tree(**overrides) -> DecisionTree:
    defaults = {
        "name": "test",
        "status": DecisionTree.STATUS_DRAFT,
        "contenu": {"arbre": {"noeud": {"id": "n_v1"}}},
        "contenu_yaml_brut": "v1",
    }
    defaults.update(overrides)
    return DecisionTree.objects.create(**defaults)


# ─── record ────────────────────────────────────────────────────────────────


def test_record_capture_etat_avant_modif(alice):
    tree = _make_tree()
    rev = DecisionTreeRevision.record(
        tree, action=DecisionTreeRevision.ACTION_EDIT, user=alice
    )
    assert rev.previous_contenu == {"arbre": {"noeud": {"id": "n_v1"}}}
    assert rev.previous_yaml_brut == "v1"
    assert rev.created_by_id == alice.pk


def test_record_independant_du_tree_courant(alice):
    tree = _make_tree()
    rev = DecisionTreeRevision.record(tree, action="edit", user=alice)
    tree.contenu["arbre"]["noeud"]["id"] = "n_v2"
    tree.save()
    assert rev.previous_contenu["arbre"]["noeud"]["id"] == "n_v1"


def test_record_chronologique(alice):
    tree = _make_tree()
    r1 = DecisionTreeRevision.record(tree, action="edit", user=alice)
    r2 = DecisionTreeRevision.record(tree, action="edit", user=alice)
    revisions = list(tree.revisions.all())
    assert revisions[0].pk == r2.pk
    assert revisions[1].pk == r1.pk


def test_record_purge_au_dela_de_50(alice):
    tree = _make_tree()
    for _ in range(55):
        DecisionTreeRevision.record(tree, action="edit", user=alice)
    assert tree.revisions.count() == 50


def test_record_isole_par_tree(alice):
    t1 = _make_tree(name="t1")
    t2 = _make_tree(name="t2")
    DecisionTreeRevision.record(t1, action="edit")
    DecisionTreeRevision.record(t2, action="edit")
    DecisionTreeRevision.record(t2, action="edit")
    assert t1.revisions.count() == 1
    assert t2.revisions.count() == 2


# ─── restore ───────────────────────────────────────────────────────────────


def test_restore_remet_le_contenu_passe(alice):
    tree = _make_tree()
    rev_v1 = DecisionTreeRevision.record(tree, action="edit", user=alice)

    tree.contenu = {"arbre": {"noeud": {"id": "n_v2"}}}
    tree.contenu_yaml_brut = "v2"
    tree.save()

    rev_v1.restore()
    tree.refresh_from_db()
    assert tree.contenu == {"arbre": {"noeud": {"id": "n_v1"}}}
    assert tree.contenu_yaml_brut == "v1"


def test_restore_cree_une_nouvelle_revision(alice):
    tree = _make_tree()
    rev_v1 = DecisionTreeRevision.record(tree, action="edit", user=alice)
    tree.contenu = {"arbre": {"noeud": {"id": "n_v2"}}}
    tree.save()

    revisions_before = tree.revisions.count()
    rev_v1.restore()
    revisions_after = tree.revisions.count()
    assert revisions_after == revisions_before + 1


# ─── meta ──────────────────────────────────────────────────────────────────


def test_action_choices():
    assert DecisionTreeRevision.ACTION_EDIT == "edit"
    assert DecisionTreeRevision.ACTION_ADD == "add"
    assert DecisionTreeRevision.ACTION_DELETE == "delete"
    assert DecisionTreeRevision.ACTION_RENAME == "rename"


def test_record_avec_metadata():
    tree = _make_tree()
    rev = DecisionTreeRevision.record(
        tree,
        action="delete",
        target_path="n_zvn/q_culture",
        description="Suppression du nœud q_culture",
    )
    assert rev.target_path == "n_zvn/q_culture"
    assert rev.description == "Suppression du nœud q_culture"
