"""UX : les libelles du formulaire d'ajout doivent etre contextuels au
niveau du parent (culture / sous_culture / type_fertilisant / complement)
plutot que generique "Ajout d'une valeur".
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


def _make_draft(make_active_tree, niveau):
    yaml_text = textwrap.dedent(
        f"""\
        metadata:
          version: "0.0.1-test"
        arbre:
          noeud:
            type_noeud: "formulaire"
            niveau: "{niveau}"
            id: "q_root"
            texte: "Question ?"
            champ: "champ_x"
            branches:
              - valeur: "x"
                regle: {{id: "r_x", type: "interdiction"}}
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


@pytest.mark.parametrize(
    "niveau,attendu_titre",
    [
        ("culture", "Ajout d'une culture"),
        ("sous_culture", "Ajout d'une sous-culture"),
        ("type_fertilisant", "Ajout d'un type de fertilisant"),
        ("complement", "Ajout d'une réponse possible"),
    ],
)
def test_titre_add_form_contextuel(
    client, staff_user, make_active_tree, niveau, attendu_titre
):
    """Le titre du formulaire d'ajout reflete le niveau du parent."""
    draft = _make_draft(make_active_tree, niveau)
    client.force_login(staff_user)
    url = (
        reverse("nitrates_admin_yaml_add_child", kwargs={"tree_pk": draft.pk})
        + "?path=q_root"
    )
    body = client.get(url).content.decode()
    assert (
        attendu_titre in body
    ), f"titre attendu '{attendu_titre}' pas trouve dans le body"


def test_kind_label_dit_de_l_enfant(client, staff_user, make_active_tree):
    """Le label du select kind dit 'type de contenu de l'enfant', pas juste
    'type de contenu' (qui pouvait porter a confusion avec le type d'une regle)."""
    draft = _make_draft(make_active_tree, "culture")
    client.force_login(staff_user)
    url = (
        reverse("nitrates_admin_yaml_add_child", kwargs={"tree_pk": draft.pk})
        + "?path=q_root"
    )
    body = client.get(url).content.decode()
    assert (
        "type de contenu de l&#x27;enfant" in body
        or "type de contenu de l'enfant" in body
    )
