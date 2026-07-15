"""Regression #218 : convertir une regle calculatrice -> nature simple via
l'editeur doit PURGER les champs orphelins du calendrier dynamique couvert
(composant couvert, inputs_requis, condition/masque de periode, texte_condition
herite). Sinon ils survivent en base et fuient a l'affichage (bulle ⓘ
"Autorisation dans les conditions de la note 1" sur une interdiction pure).
"""

import textwrap

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from envergo.nitrates.models import DecisionTree
from envergo.nitrates.yaml_admin import editor

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
def draft_calculatrice(make_active_tree):
    """Arbre avec une regle calculatrice couvert complete (composant couvert,
    inputs_requis, periodes masque + condition, texte_condition)."""
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
                  id: "r_calc"
                  type: "calculatrice"
                  composant: "calendrier_dynamique_couvert"
                  texte_condition: "Autorisation dans les conditions de la note 1."
                  periodes:
                    - du: "15/12"
                      au: "date_semis_couvert+4semaines"
                      regime: "interdiction"
                      masque: true
                      condition: "15/12 < date_semis_couvert+4semaines"
                  inputs_requis:
                    - id: "date_semis_couvert"
                      type: "date"
                      label: "Date de semis"
                      label_court: "semis"
                      placeholder: "15/08"
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


def test_conversion_calculatrice_vers_interdiction_purge_les_residus(
    client, staff_user, draft_calculatrice
):
    client.force_login(staff_user)
    url = _edit_url(draft_calculatrice, "n_root", "True")
    # L'utilisateur passe la regle en interdiction pure 15/12 -> 15/01. Le form
    # POSTe encore composant/inputs_requis/texte_condition (inputs masques mais
    # dans le DOM), reproduisant le bug.
    resp = client.post(
        url,
        data={
            "id": "r_calc",
            "type": "interdiction",
            "composant": "calendrier_dynamique_couvert",
            "texte_condition": "Autorisation dans les conditions de la note 1.",
            "periodes-0-du": "15/12",
            "periodes-0-au": "15/01",
            "periodes-0-regime": "interdiction",
            "inputs_requis-0-id": "date_semis_couvert",
            "inputs_requis-0-label": "Date de semis",
            "inputs_requis-0-label_court": "semis",
            "inputs_requis-0-type": "date",
            "inputs_requis-0-placeholder": "15/08",
        },
    )
    assert resp.status_code == 200, resp.content[:500]

    draft_calculatrice.refresh_from_db()
    branche = editor.get_branche_at(draft_calculatrice.contenu, ["n_root"], True)
    regle = branche["regle"]

    assert regle["type"] == "interdiction"
    # Champs calculatrice orphelins purges :
    assert regle.get("composant") in (None, ""), "composant couvert residuel non purge"
    assert not regle.get("inputs_requis"), "inputs_requis residuels non purges"
    assert not (
        regle.get("texte_condition") or ""
    ).strip(), (
        "texte_condition herite de la calculatrice non purge (source de la bulle)"
    )
    # La periode d'interdiction est conservee, mais sans condition/masque :
    periodes = regle.get("periodes") or []
    assert len(periodes) == 1
    assert periodes[0]["du"] == "15/12" and periodes[0]["au"] == "15/01"
    assert "condition" not in periodes[0], "condition de periode residuelle non purgee"
    assert "masque" not in periodes[0], "masque de periode residuel non purge"


def test_texte_condition_legitime_preserve_sur_interdiction_non_calculatrice(
    client, staff_user, make_active_tree
):
    """Une regle qui n'a JAMAIS ete calculatrice (interdiction avec
    texte_condition volontaire, sans composant couvert) doit CONSERVER son
    texte_condition apres edition -- cf. les 13 justifications du PAR HdF."""
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
                  id: "r_interdit"
                  type: "interdiction"
                  texte_condition: "Justification metier volontaire (art. 2-II A)."
                  periodes:
                    - du: "01/11"
                      au: "15/01"
                      regime: "interdiction"
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
    url = _edit_url(draft, "n_root", "True")
    resp = client.post(
        url,
        data={
            "id": "r_interdit",
            "type": "interdiction",
            "texte_condition": "Justification metier volontaire (art. 2-II A).",
            "periodes-0-du": "01/11",
            "periodes-0-au": "15/01",
            "periodes-0-regime": "interdiction",
        },
    )
    assert resp.status_code == 200, resp.content[:500]
    draft.refresh_from_db()
    branche = editor.get_branche_at(draft.contenu, ["n_root"], True)
    assert (
        branche["regle"].get("texte_condition")
        == "Justification metier volontaire (art. 2-II A)."
    ), "justification volontaire effacee a tort (elle n'a jamais ete calculatrice)"
