"""Dropdowns dans le formulaire d'ajout d'une branche (AddChildView).

Tu as au format dropdown a l'insertion exactement les memes choix que pour
l'edition d'une branche/regle existante :
- valeur de branche : select si parent niveau=type_fertilisant/sous_culture
- code_prescription : select avec slugs canoniques
- note : select avec slugs canoniques
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
def draft_with_type_fert_parent(make_active_tree):
    yaml_text = textwrap.dedent(
        """\
        metadata:
          version: "0.0.1-test"
        arbre:
          noeud:
            type_noeud: "formulaire"
            niveau: "type_fertilisant"
            id: "q_fert"
            texte: "Type fertilisant ?"
            champ: "type_fertilisant"
            branches:
              - valeur: "type_0"
                regle:
                  id: "r_t0"
                  type: "interdiction"
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


def test_add_form_valeur_is_select_for_type_fertilisant_parent(
    client, staff_user, draft_with_type_fert_parent
):
    """Sur un parent niveau=type_fertilisant, le champ valeur de l'add form
    doit etre un <select> ferme."""
    client.force_login(staff_user)
    url = (
        reverse(
            "nitrates_admin_yaml_add_child",
            kwargs={"tree_pk": draft_with_type_fert_parent.pk},
        )
        + "?path=q_fert&kind=regle"
    )
    body = client.get(url).content.decode()
    assert '<select name="valeur"' in body
    # Plusieurs slugs canoniques du referentiel doivent etre proposes.
    found = sum(
        1
        for s in ("type_Ia", "type_Ib", "type_II", "type_III")
        if f'value="{s}"' in body
    )
    assert found >= 2, f"select doit lister >=2 slugs du referentiel, {found}"


def test_add_form_code_prescription_is_select(
    client, staff_user, draft_with_type_fert_parent
):
    """Le champ code_prescription du kind=regle doit etre un <select> ferme."""
    client.force_login(staff_user)
    url = (
        reverse(
            "nitrates_admin_yaml_add_child",
            kwargs={"tree_pk": draft_with_type_fert_parent.pk},
        )
        + "?path=q_fert&kind=regle"
    )
    body = client.get(url).content.decode()
    assert '<select name="c_code_prescription"' in body
    # Slugs canoniques pc1..pcN doivent etre la
    pc_count = sum(1 for s in ("pc1", "pc2", "pc3") if f'value="{s}"' in body)
    assert pc_count >= 2, f"pcN doivent etre la, {pc_count}"


def test_add_form_note_is_select(client, staff_user, draft_with_type_fert_parent):
    """Le champ note du kind=regle doit etre un <select> ferme."""
    client.force_login(staff_user)
    url = (
        reverse(
            "nitrates_admin_yaml_add_child",
            kwargs={"tree_pk": draft_with_type_fert_parent.pk},
        )
        + "?path=q_fert&kind=regle"
    )
    body = client.get(url).content.decode()
    assert '<select name="c_note"' in body
    note_count = sum(
        1 for s in ("note_1", "note_2", "note_3") if f'value="{s}"' in body
    )
    assert note_count >= 2


def test_add_form_culture_parent_keeps_free_input(client, staff_user, make_active_tree):
    """Niveau culture pas mappe au referentiel -> valeur reste input libre."""
    yaml_text = textwrap.dedent(
        """\
        metadata:
          version: "0.0.1-test"
        arbre:
          noeud:
            type_noeud: "formulaire"
            niveau: "culture"
            id: "q_cult"
            texte: "Culture ?"
            champ: "occupation_sol"
            branches:
              - valeur: "colza"
                regle:
                  id: "r_colza"
                  type: "interdiction"
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
    client.force_login(staff_user)
    url = (
        reverse("nitrates_admin_yaml_add_child", kwargs={"tree_pk": draft.pk})
        + "?path=q_cult&kind=regle"
    )
    body = client.get(url).content.decode()
    # Le champ valeur doit rester un input texte (pas un select)
    assert '<select name="valeur"' not in body
    # Et un input de type texte avec ce nom doit etre present
    import re

    assert re.search(r'<input[^>]*type="text"[^>]*name="valeur"', body) or re.search(
        r'<input[^>]*name="valeur"[^>]*type="text"', body
    ), "input texte valeur attendu pour niveau culture"
