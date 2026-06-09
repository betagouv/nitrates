"""Killer feature #80 : preview d'un draft via le simulateur avec
`?draft_tree_id=<pk>`.

- staff/superuser : peut prévisualiser n'importe quel tree
- external_observator : uniquement ses propres drafts
- visiteur non-staff : param ignoré, fallback sur arbre actif
- draft_tree_id invalide / inconnu : fallback sur arbre actif
"""

import textwrap

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from envergo.nitrates.models import DecisionTree
from envergo.nitrates.permissions import EXTERNAL_OBSERVATOR_GROUP, can_preview_tree

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]


@pytest.fixture(autouse=True)
def _purge():
    DecisionTree.objects.all().delete()


@pytest.fixture
def superadmin(db):
    User = get_user_model()
    return User.objects.create_user(
        email="admin@test.local",
        name="Admin",
        password="x",
        is_staff=True,
        is_superuser=True,
    )


@pytest.fixture
def observator(db):
    User = get_user_model()
    user = User.objects.create_user(
        email="obs@test.local",
        name="Obs",
        password="x",
        is_staff=True,
    )
    group, _ = Group.objects.get_or_create(name=EXTERNAL_OBSERVATOR_GROUP)
    user.groups.add(group)
    return user


@pytest.fixture
def other_user(db):
    User = get_user_model()
    return User.objects.create_user(
        email="other@test.local", name="Other", password="x"
    )


@pytest.fixture
def active_and_draft(make_active_tree, superadmin):
    yaml_text = textwrap.dedent(
        """\
        metadata:
          version: "0.0.1-test"
        arbre:
          noeud:
            type_noeud: "catalogue"
            id: "n_zvn"
            champ: "en_zone_vulnerable"
            source: "sig"
            reference: "zone_vulnerable_nitrates"
            branches:
              - valeur: false
                regle: {id: "r_hors", type: "non_applicable"}
              - valeur: true
                regle: {id: "r_en", type: "non_applicable"}
        """
    )
    active = make_active_tree(yaml_text)
    draft = DecisionTree.objects.create(
        name=active.name,
        status=DecisionTree.STATUS_DRAFT,
        contenu=active.contenu,
        contenu_yaml_brut=active.contenu_yaml_brut,
        parent=active,
        created_by=superadmin,
    )
    return active, draft


def test_can_preview_tree_superuser(active_and_draft, superadmin):
    _, draft = active_and_draft
    assert can_preview_tree(superadmin, draft) is True


def test_can_preview_tree_observator_own_draft(
    active_and_draft, observator, make_active_tree
):
    """Un observator peut preview SES drafts."""
    active, _ = active_and_draft
    own_draft = DecisionTree.objects.create(
        name=active.name,
        status=DecisionTree.STATUS_DRAFT,
        contenu=active.contenu,
        contenu_yaml_brut=active.contenu_yaml_brut,
        parent=active,
        created_by=observator,
    )
    assert can_preview_tree(observator, own_draft) is True


def test_can_preview_tree_observator_others_draft_refused(active_and_draft, observator):
    """Un observator ne peut PAS preview les drafts d'autres users."""
    _, draft = active_and_draft  # cree par superadmin
    assert can_preview_tree(observator, draft) is False


def test_can_preview_tree_observator_active_refused(active_and_draft, observator):
    """Un observator ne peut PAS preview l'actif via draft_tree_id (deja
    accessible via simulateur normal)."""
    active, _ = active_and_draft
    assert can_preview_tree(observator, active) is False


def test_can_preview_tree_non_staff_refused(active_and_draft, other_user):
    """Un user non-staff ne peut pas preview de tree."""
    _, draft = active_and_draft
    assert can_preview_tree(other_user, draft) is False


def test_can_preview_tree_anonymous_refused(active_and_draft):
    """User None ou anonymous -> refus."""
    _, draft = active_and_draft
    assert can_preview_tree(None, draft) is False
