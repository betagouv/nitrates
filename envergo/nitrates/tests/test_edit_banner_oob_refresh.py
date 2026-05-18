"""Bug : le bouton "↩ Annuler" du bandeau d'edition restait disabled meme
apres une modif (si on etait entre en edition sans revisions existantes).
La cause : `_render_partial_node_response` ne re-rendait que le sous-arbre,
pas le bandeau, donc `recent_revisions` n'etait jamais raffraichi cote
client.

Fix : on swap-oob le bandeau apres chaque modif inline.
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


def test_partial_node_response_includes_banner_oob(client, staff_user, draft_tree):
    """Apres une modif inline (ex: edition d'une regle), la reponse htmx
    doit contenir le bandeau d'edition swap-oob (id+attribut)."""
    client.force_login(staff_user)
    # On simule une edition de la regle r_hors : on change juste le message.
    url = (
        reverse("nitrates_admin_yaml_edit_regle", kwargs={"tree_pk": draft_tree.pk})
        + "?path=n_zvn&valeur=False"
    )
    resp = client.post(
        url,
        data={
            "id": "r_hors",
            "type": "non_applicable",
            "message": "Hors ZVN modifie",
        },
    )
    assert resp.status_code == 200, resp.content[:500]
    body = resp.content.decode()

    # Le bandeau doit etre dans la reponse, avec son id et hx-swap-oob.
    assert 'id="yaml-admin-edit-banner"' in body
    assert 'hx-swap-oob="outerHTML"' in body
    # Et le bouton "↩ Annuler" doit etre actif (pas disabled).
    assert "↩ Annuler" in body
    # Verifie que la version du bandeau dans la reponse a un bouton sans
    # l'attribut disabled (recent_revisions n'est plus vide apres la modif).
    banner_start = body.find('id="yaml-admin-edit-banner"')
    banner_end = body.find("</div>", banner_start + 5000)  # marge large
    banner_html = body[banner_start:banner_end]
    annuler_block_start = banner_html.find("↩ Annuler")
    # On regarde le bloc <button> qui contient "↩ Annuler"
    btn_open = banner_html.rfind("<button", 0, annuler_block_start)
    btn_close = banner_html.find(">", btn_open)
    btn_tag = banner_html[btn_open:btn_close]
    assert (
        "disabled" not in btn_tag
    ), f"le bouton ↩ Annuler ne doit plus etre disabled, tag = {btn_tag}"
