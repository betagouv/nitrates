"""Garde-fou du simulateur sur `?draft_tree_id=` (#80).

Un visiteur qui n'a pas le droit de prévisualiser un brouillon ne doit pas le
voir via une URL devinée : le paramètre est retiré silencieusement et le
simulateur retombe sur l'arbre actif.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from envergo.nitrates.models import DecisionTree
from envergo.nitrates.views import MoulinetteView

pytestmark = pytest.mark.django_db


@pytest.fixture
def brouillon(db):
    return DecisionTree.objects.create(
        name="brouillon", status=DecisionTree.STATUS_DRAFT, contenu={}
    )


def _garde(user, draft_tree_id):
    request = RequestFactory().get("/simulateur/", {"draft_tree_id": draft_tree_id})
    request.user = user
    MoulinetteView()._guard_draft_tree_id(request)
    return request.GET


@pytest.mark.parametrize("draft_tree_id", ["999999", "pas-un-nombre"])
def test_identifiant_inconnu_ou_invalide_retire(draft_tree_id):
    params = _garde(AnonymousUser(), draft_tree_id)
    assert "draft_tree_id" not in params
    assert params._mutable is False


def test_anonyme_ne_voit_pas_le_brouillon(brouillon):
    assert "draft_tree_id" not in _garde(AnonymousUser(), str(brouillon.pk))


def test_superuser_garde_le_parametre(brouillon):
    admin = get_user_model().objects.create_user(
        email="su@test.local", name="Su", password="x", is_staff=True, is_superuser=True
    )
    assert _garde(admin, str(brouillon.pk))["draft_tree_id"] == str(brouillon.pk)


def test_sans_parametre_rien_a_faire():
    request = RequestFactory().get("/simulateur/")
    request.user = AnonymousUser()
    MoulinetteView()._guard_draft_tree_id(request)
    assert dict(request.GET) == {}
