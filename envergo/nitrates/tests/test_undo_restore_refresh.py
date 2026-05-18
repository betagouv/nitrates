"""Annuler / Restaurer doivent forcer un hard refresh de la page cote
client. Sinon l'arbre dans le DOM reste sur l'etat pre-mutation et
l'utilisateur a l'impression que l'action n'a pas fait son effet.
"""

import textwrap

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from envergo.nitrates.models import DecisionTree, DecisionTreeRevision

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
def draft_tree_with_revision(make_active_tree, staff_user):
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
    )
    # On simule une mutation pour avoir une revision a annuler
    from envergo.nitrates.yaml_admin import editor

    editor.update_regle(
        draft,
        ("n_zvn",),
        False,
        {"message": "Modifie"},
        staff_user,
    )
    return draft


def test_undo_returns_hx_refresh(client, staff_user, draft_tree_with_revision):
    """UndoLastView doit retourner HX-Refresh:true pour forcer reload."""
    client.force_login(staff_user)
    url = reverse(
        "nitrates_admin_yaml_undo",
        kwargs={"tree_pk": draft_tree_with_revision.pk},
    )
    resp = client.post(url)
    assert resp.status_code == 200
    assert (
        resp.get("HX-Refresh") == "true"
    ), f"HX-Refresh attendu, headers : {dict(resp.headers)}"


def test_restore_returns_hx_refresh(client, staff_user, draft_tree_with_revision):
    """RestoreRevisionView doit retourner HX-Refresh:true."""
    client.force_login(staff_user)
    revision = (
        DecisionTreeRevision.objects.filter(tree=draft_tree_with_revision)
        .order_by("-created_at")
        .first()
    )
    url = (
        reverse(
            "nitrates_admin_yaml_restore_revision",
            kwargs={"tree_pk": draft_tree_with_revision.pk},
        )
        + f"?revision_id={revision.pk}"
    )
    resp = client.post(url)
    assert resp.status_code == 200
    assert resp.get("HX-Refresh") == "true"
