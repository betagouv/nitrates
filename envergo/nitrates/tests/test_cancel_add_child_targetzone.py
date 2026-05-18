"""Bug : CancelAddChildView retournait une chaine vide. Avec hx-swap=outerHTML
ca supprimait le <div id="add-zone-{path}"></div> du DOM cote navigateur,
et le prochain clic sur le bouton + du noeud declenchait htmx:targetError
(la cible n'existe plus).

Fix : le cancel renvoie le div vide reinitialise.
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
                  id: "r_hors_zvn"
                  type: "non_applicable"
                  message: "Hors ZVN"
              - valeur: true
                regle:
                  id: "r_en_zvn"
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


def test_cancel_renders_empty_add_zone_div(client, staff_user, draft_tree):
    """CancelAddChildView doit renvoyer le `<div id="add-zone-{slug}">` vide,
    pas une chaine vide. Sinon le swap outerHTML supprime la cible et casse
    le prochain clic sur le bouton +."""
    client.force_login(staff_user)
    url = (
        reverse(
            "nitrates_admin_yaml_add_child_cancel", kwargs={"tree_pk": draft_tree.pk}
        )
        + "?path=n_zvn"
    )
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    # Le div vide doit etre present avec l'id calcule via slugify(path)
    assert (
        'id="add-zone-n_zvn"' in body
    ), f"cancel doit renvoyer le div add-zone vide, recu : {body!r}"


def test_cancel_with_empty_path_renders_root_add_zone(client, staff_user, draft_tree):
    """Cas limite : annulation sur la racine (path vide) doit renvoyer
    `<div id="add-zone-">`."""
    client.force_login(staff_user)
    url = reverse(
        "nitrates_admin_yaml_add_child_cancel", kwargs={"tree_pk": draft_tree.pk}
    )
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'id="add-zone-"' in body
