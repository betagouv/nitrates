"""Complement de couverture pour envergo/nitrates/permissions.py.

test_permissions_observator.py couvre can_change_tree / can_delete_tree /
can_activate_tree / can_edit_active. Ce fichier couvre spécifiquement
`can_preview_tree`, qui n'était pas testée du tout (killer feature #80 :
prévisualisation d'un arbre via `?draft_tree_id=<pk>`).
"""

import pytest
from django.contrib.auth.models import Group

from envergo.nitrates.models import DecisionTree
from envergo.nitrates.permissions import (
    EXTERNAL_OBSERVATOR_GROUP,
    can_delete_tree,
    can_preview_tree,
)
from envergo.users.tests.factories import UserFactory


@pytest.fixture
def observator_group(db):
    group, _ = Group.objects.get_or_create(name=EXTERNAL_OBSERVATOR_GROUP)
    return group


@pytest.fixture
def observator_user(db, observator_group):
    u = UserFactory(is_staff=True, is_superuser=False)
    u.groups.add(observator_group)
    return u


@pytest.fixture
def other_observator(db, observator_group):
    u = UserFactory(is_staff=True, is_superuser=False)
    u.groups.add(observator_group)
    return u


@pytest.fixture
def superuser(db):
    return UserFactory(is_staff=True, is_superuser=True)


@pytest.fixture
def intra_staff(db):
    return UserFactory(is_staff=True, is_superuser=False)


@pytest.fixture
def non_staff_user(db):
    return UserFactory(is_staff=False, is_superuser=False)


def _make_tree(status, created_by, name="preview-test"):
    if status == DecisionTree.STATUS_ACTIVE:
        DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE).delete()
    return DecisionTree.objects.create(
        name=name,
        status=status,
        contenu={},
        contenu_yaml_brut="",
        created_by=created_by,
    )


def test_non_staff_ne_peut_jamais_previsualiser(non_staff_user, intra_staff):
    tree = _make_tree(DecisionTree.STATUS_DRAFT, intra_staff)
    assert can_preview_tree(non_staff_user, tree) is False


def test_anonyme_ne_peut_pas_previsualiser(intra_staff):
    tree = _make_tree(DecisionTree.STATUS_DRAFT, intra_staff)

    class _Anon:
        is_authenticated = False
        is_staff = False

    assert can_preview_tree(_Anon(), tree) is False
    assert can_preview_tree(None, tree) is False


def test_superuser_peut_previsualiser_tous_statuts(superuser, intra_staff):
    for status in (
        DecisionTree.STATUS_DRAFT,
        DecisionTree.STATUS_ACTIVE,
        DecisionTree.STATUS_ARCHIVE,
    ):
        tree = _make_tree(status, intra_staff)
        assert can_preview_tree(superuser, tree) is True


def test_intra_staff_peut_previsualiser_tout(intra_staff, observator_user):
    tree = _make_tree(DecisionTree.STATUS_DRAFT, observator_user)
    assert can_preview_tree(intra_staff, tree) is True
    tree_actif = _make_tree(DecisionTree.STATUS_ACTIVE, observator_user)
    assert can_preview_tree(intra_staff, tree_actif) is True


def test_observator_peut_previsualiser_son_propre_draft(observator_user):
    tree = _make_tree(DecisionTree.STATUS_DRAFT, observator_user)
    assert can_preview_tree(observator_user, tree) is True


def test_observator_ne_peut_pas_previsualiser_draft_d_autrui(
    observator_user, other_observator
):
    tree = _make_tree(DecisionTree.STATUS_DRAFT, other_observator)
    assert can_preview_tree(observator_user, tree) is False


def test_observator_ne_peut_pas_previsualiser_arbre_actif(observator_user):
    tree = _make_tree(DecisionTree.STATUS_ACTIVE, observator_user)
    assert can_preview_tree(observator_user, tree) is False


def test_observator_ne_peut_pas_previsualiser_archive(observator_user):
    tree = _make_tree(DecisionTree.STATUS_ARCHIVE, observator_user)
    assert can_preview_tree(observator_user, tree) is False


def test_intra_staff_peut_supprimer_tout(intra_staff, observator_user):
    """can_delete_tree : branche finale `return True` pour un staff intra
    non-observator (non couverte par le fichier historique)."""
    tree = _make_tree(DecisionTree.STATUS_DRAFT, observator_user)
    assert can_delete_tree(intra_staff, tree) is True
    tree_actif = _make_tree(DecisionTree.STATUS_ACTIVE, observator_user)
    assert can_delete_tree(intra_staff, tree_actif) is True
