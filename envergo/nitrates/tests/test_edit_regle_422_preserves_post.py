"""Regression : quand POST sur EditRegleView echoue (422), le formulaire
re-rendu doit preserver les saisies utilisateur. Sans ca, l'utilisateur
perd toutes ses modifications a chaque save invalide -- bug critique
reporte 2026-05-27.
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
def draft_with_regle(make_active_tree):
    yaml_text = textwrap.dedent(
        """\
        metadata:
          version: "0.0.1-test"
        arbre:
          noeud:
            type_noeud: "catalogue"
            id: "n_root"
            champ: "en_zv"
            source: "sig"
            branches:
              - valeur: true
                regle:
                  id: "r_main"
                  type: "interdiction"
                  message: "valeur d'origine"
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


def _edit_url(tree, parent_path, valeur):
    return (
        reverse("nitrates_admin_yaml_edit_regle", kwargs={"tree_pk": tree.pk})
        + f"?path={parent_path}&valeur={valeur}"
    )


def test_422_preserves_user_input_on_invalid_period(
    client, staff_user, draft_with_regle
):
    """POST avec une periode au format invalide (`du=foo` au lieu de JJ/MM).
    Le form re-rendu doit garder : id modifie, message modifie, periode
    saisie -- pas restituer les valeurs d'origine de la DB.
    """
    client.force_login(staff_user)
    url = _edit_url(draft_with_regle, "n_root", "True")
    resp = client.post(
        url,
        data={
            "id": "r_main_renamed",
            "type": "interdiction",
            "message": "verdict modifie par l'utilisateur",
            "periodes-0-du": "PASUNDATE",  # invalide -> 422
            "periodes-0-au": "31/12",
            "periodes-0-regime": "",
        },
    )
    assert resp.status_code == 422, resp.content[:500]
    body = resp.content.decode()
    # Les saisies POST doivent etre presentes dans le re-render :
    assert 'value="r_main_renamed"' in body, "id POST perdu, fallback sur valeur DB"
    # Django escape les apostrophes en `&#x27;` dans les attributs HTML :
    assert (
        "verdict modifie par l&#x27;utilisateur" in body
        or "verdict modifie par l'utilisateur" in body
    ), "message POST perdu, fallback sur valeur DB"
    assert 'value="PASUNDATE"' in body, "periode saisie perdue, re-saisie obligatoire"
    assert 'value="31/12"' in body, "periode au saisie perdue"
    # La valeur d'origine ne doit PAS reapparaitre :
    assert "valeur d'origine" not in body, "fallback indesirable sur message original"


def test_422_preserves_inputs_requis_calculatrice(client, staff_user, draft_with_regle):
    """Cas calculatrice : l'utilisateur switche type=calculatrice, ajoute
    des inputs_requis, mais soumet sans periode (echec validation type
    calculatrice). On verifie que les inputs_requis saisis sont preserves.
    """
    client.force_login(staff_user)
    url = _edit_url(draft_with_regle, "n_root", "True")
    resp = client.post(
        url,
        data={
            "id": "r_main",
            "type": "calculatrice",
            "composant": "calendrier_dynamique_couvert",
            "message": "Calendrier dynamique",
            # Periode invalide pour forcer un 422 :
            "periodes-0-du": "NOPE",
            "periodes-0-au": "",
            "periodes-0-regime": "",
            # 2 inputs_requis saisis :
            "inputs_requis-0-id": "date_semis_couvert",
            "inputs_requis-0-label": "Date de semis",
            "inputs_requis-0-label_court": "semis",
            "inputs_requis-0-type": "date",
            "inputs_requis-0-placeholder": "25/07",
            "inputs_requis-1-id": "date_destruction_couvert",
            "inputs_requis-1-label": "Date destruction",
            "inputs_requis-1-label_court": "destruction",
            "inputs_requis-1-type": "date",
            "inputs_requis-1-placeholder": "23/03",
        },
    )
    assert resp.status_code == 422
    body = resp.content.decode()
    # Les 2 inputs_requis doivent reapparaitre :
    assert 'value="date_semis_couvert"' in body
    assert 'value="Date de semis"' in body
    assert 'value="date_destruction_couvert"' in body
    assert 'value="Date destruction"' in body
