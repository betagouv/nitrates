"""Regression : à l'ajout d'une branche avec kind=renvoi_vers, le champ
cible doit etre un <select> ferme alimente par les ids existants de
l'arbre, pas un <input type=text> libre.
"""

import textwrap

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from envergo.nitrates.models import DecisionTree

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]


@pytest.fixture(autouse=True)
def _purge():
    DecisionTree.objects.all().delete()


@pytest.fixture
def staff_user(db):
    User = get_user_model()
    return User.objects.create_user(
        email="staff@test.local", name="Staff", password="x", is_staff=True
    )


@pytest.fixture
def draft_tree(make_active_tree):
    """Arbre avec plusieurs ids qui peuvent servir de cibles de renvoi."""
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
                regle:
                  id: "r_hors"
                  type: "non_applicable"
                  message: "Hors ZVN"
              - valeur: true
                regle:
                  id: "r_en"
                  type: "non_applicable"
                  message: "En ZVN"
        """
    )
    active = make_active_tree(yaml_text)
    return DecisionTree.objects.create(
        name=active.name,
        status=DecisionTree.STATUS_DRAFT,
        contenu=active.contenu,
        contenu_yaml_brut=active.contenu_yaml_brut,
        parent=active,
    )


def test_add_form_renvoi_vers_is_select_with_targets(client, staff_user, draft_tree):
    """GET sur AddChildView avec kind=renvoi_vers doit renvoyer un <select>
    contenant les ids existants de l'arbre comme options."""
    client.force_login(staff_user)
    url = (
        reverse("nitrates_admin_yaml_add_child", kwargs={"tree_pk": draft_tree.pk})
        + "?path=n_zvn&kind=renvoi_vers"
    )
    resp = client.get(url)
    assert resp.status_code == 200, resp.content[:500]
    body = resp.content.decode()
    # Le champ c_renvoi_vers doit etre un <select>, pas un <input>.
    assert (
        '<select name="c_renvoi_vers"' in body
    ), "c_renvoi_vers doit etre un <select> ferme"
    assert '<input type="text"\n               name="c_renvoi_vers"' not in body
    # Les ids existants de l'arbre doivent etre proposes en option.
    assert 'value="r_hors"' in body
    assert 'value="r_en"' in body
