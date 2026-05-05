"""Tests du modele DecisionTree : contrainte unique partielle + activate()."""

import pytest
from django.db import IntegrityError, transaction

from envergo.nitrates.models import DecisionTree

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _purge_decision_trees():
    """La migration data 0004 cree un DecisionTree au 1er migrate. On
    purge avant chaque test pour partir d'une table vide."""
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


def test_un_seul_actif_a_la_fois():
    """La contrainte UNIQUE partielle empeche d'avoir 2 trees actifs."""
    _make_tree(name="t1", status=DecisionTree.STATUS_ACTIVE)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _make_tree(name="t2", status=DecisionTree.STATUS_ACTIVE)


def test_drafts_multiples_autorises():
    """Plusieurs drafts peuvent coexister librement."""
    _make_tree(name="d1", status=DecisionTree.STATUS_DRAFT)
    _make_tree(name="d2", status=DecisionTree.STATUS_DRAFT)
    _make_tree(name="d3", status=DecisionTree.STATUS_DRAFT)
    assert DecisionTree.objects.filter(status=DecisionTree.STATUS_DRAFT).count() == 3


def test_archives_multiples_autorisees():
    """Plusieurs archives peuvent coexister."""
    _make_tree(name="a1", status=DecisionTree.STATUS_ARCHIVE)
    _make_tree(name="a2", status=DecisionTree.STATUS_ARCHIVE)
    assert DecisionTree.objects.filter(status=DecisionTree.STATUS_ARCHIVE).count() == 2


def test_activate_archive_actif_courant():
    """activate() sur un draft : l'actif courant passe en archive, le draft
    devient actif, activated_at est rempli."""
    actif = _make_tree(name="ancien_actif", status=DecisionTree.STATUS_ACTIVE)
    draft = _make_tree(name="nouveau", status=DecisionTree.STATUS_DRAFT)

    draft.activate()

    actif.refresh_from_db()
    draft.refresh_from_db()

    assert actif.status == DecisionTree.STATUS_ARCHIVE
    assert draft.status == DecisionTree.STATUS_ACTIVE
    assert draft.activated_at is not None


def test_activate_idempotent():
    """Re-activer un tree deja actif ne casse pas la contrainte."""
    tree = _make_tree(status=DecisionTree.STATUS_ACTIVE)
    tree.activate()
    tree.refresh_from_db()
    assert tree.status == DecisionTree.STATUS_ACTIVE
    assert DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE).count() == 1


def test_activate_premier_tree_sans_actif_courant():
    """activate() sans actif en DB : le tree devient simplement actif."""
    draft = _make_tree(status=DecisionTree.STATUS_DRAFT)
    draft.activate()
    draft.refresh_from_db()
    assert draft.status == DecisionTree.STATUS_ACTIVE
    assert draft.activated_at is not None
