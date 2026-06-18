"""Dropdowns dans le formulaire d'ajout d'une branche (AddChildView).

- valeur de branche : select si parent niveau=type_fertilisant/sous_culture
- le formulaire d'ajout d'une regle est minimal (type + flag "a completer") ;
  tout le detail (code_prescription, note, periodes, plafond...) ne s'edite
  qu'APRES insertion via le formulaire d'edition.
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


def test_add_form_regle_est_minimal(client, staff_user, draft_with_type_fert_parent):
    """Le formulaire d'AJOUT d'une regle est volontairement minimal : type +
    flag "a completer". Le detail (periodes, plafond, verdict, code
    prescription, source juridique, note...) ne s'edite qu'APRES insertion,
    via le formulaire d'edition. On verifie ici l'absence de ces champs a
    l'ajout."""
    client.force_login(staff_user)
    url = (
        reverse(
            "nitrates_admin_yaml_add_child",
            kwargs={"tree_pk": draft_with_type_fert_parent.pk},
        )
        + "?path=q_fert&kind=regle"
    )
    body = client.get(url).content.decode()
    # Garde : le type et le flag "a completer".
    assert 'name="c_type"' in body
    assert 'name="c_a_completer"' in body
    # Retire de l'ajout (edition uniquement).
    for absent in (
        "c_code_prescription",
        "c_note",
        "c_message",
        "c_source_juridique",
        "c_periodes-0-du",
        "c_composant",
        "c_plafond_azote_kg_n_ha",
    ):
        assert absent not in body, f"{absent} ne doit plus etre dans l'ajout"


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
