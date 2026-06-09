"""L'overlay global "en cours" est present dans base.html et active par
body.yaml-admin--busy. Permet de bloquer les clics et montrer un message
pendant les requetes mutatives non-inline (Annuler, Restaurer, etc.).
"""

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


def test_overlay_html_present_in_admin_page(client, staff_user, make_active_tree):
    """L'overlay HTML doit etre present sur la page admin yaml (en lecture
    ou edition)."""
    import textwrap

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
    make_active_tree(yaml_text)
    client.force_login(staff_user)
    body = client.get(reverse("nitrates_admin_yaml_tree")).content.decode()
    assert "yaml-admin__global-overlay" in body
    assert "Sauvegarde en cours" in body
    # Listener htmx pour ajouter/retirer la classe body
    assert "yaml-admin--busy" in body


def test_overlay_css_rule_present_in_yaml_tree_css():
    """La regle CSS qui declenche l'overlay sur body.yaml-admin--busy doit
    etre dans yaml_tree.css."""
    from pathlib import Path

    css_path = (
        Path(__file__).resolve().parent.parent.parent
        / "static"
        / "nitrates_admin"
        / "yaml_tree.css"
    )
    content = css_path.read_text(encoding="utf-8")
    assert "body.yaml-admin--busy .yaml-admin__global-overlay" in content
    assert "cursor: wait" in content
