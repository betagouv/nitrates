"""Regression #87 : le bouton 'Sauvegarder et publier' disparaissait apres
chaque modif inline car `_render_banner_oob` ne passait pas
`can_activate_this_tree` au template `_edit_banner.html` -- la condition
template tombait en branche `else` et le bouton n'etait pas rendu.

Fix : passer can_activate_this_tree (et l'user pour _edited_origin_name)
dans le contexte du re-rendu OOB.
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
def admin_user(db):
    User = get_user_model()
    return User.objects.create_user(
        email="admin@test.local",
        name="Admin",
        password="x",
        is_staff=True,
        is_superuser=True,
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
                regle: {id: "r_hors", type: "non_applicable"}
              - valeur: true
                regle: {id: "r_en", type: "non_applicable"}
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


def test_banner_oob_keeps_publish_button_for_admin(client, admin_user, draft_tree):
    """Apres edition d'une regle, le bandeau OOB rerender doit contenir le
    bouton 'Sauvegarder et publier' pour un admin (can_activate_tree=True)."""
    client.force_login(admin_user)
    url = (
        reverse("nitrates_admin_yaml_edit_regle", kwargs={"tree_pk": draft_tree.pk})
        + "?path=n_zvn&valeur=False"
    )
    resp = client.post(
        url,
        data={
            "id": "r_hors",
            "type": "non_applicable",
            "message": "Modif test",
        },
    )
    assert resp.status_code == 200, resp.content[:500]
    body = resp.content.decode()

    # Le bandeau OOB doit etre rendu
    assert 'id="yaml-admin-edit-banner"' in body
    assert 'hx-swap-oob="outerHTML"' in body
    # Le bouton "Sauvegarder et publier" doit etre dans le bandeau OOB
    banner_start = body.find('id="yaml-admin-edit-banner"')
    banner_end = body.find("</div>\n</div>", banner_start)
    if banner_end < 0:
        banner_end = banner_start + 5000
    banner_html = body[banner_start:banner_end]
    assert "Sauvegarder et publier" in banner_html, (
        "Bouton 'Sauvegarder et publier' manquant dans le bandeau OOB "
        f"(regression #87). Banner = {banner_html[:1500]}"
    )
