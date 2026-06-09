"""Test de structure HTML du rendu de l'arbre admin.

Vise specifiquement le bug "deep-btn chevauche edit-actions" : le bouton
"deplier en profondeur" (▾▾) etait positionne en `position: absolute` a
droite du noeud, ce qui le faisait passer par-dessus les boutons
edit/add/delete en mode edition.

Le fix met le deep-btn **dans le summary**, **apres** le contenu et
**avant** les edit-actions. On verifie cet ordre structurel ici ;
le CSS gere la mise a droite via `margin-left: auto`.
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
    """Cree un actif + un draft minimal sur lequel on a un noeud avec
    sous-arbre (donc deep-btn rendu)."""
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
                noeud:
                  type_noeud: "formulaire"
                  niveau: "culture"
                  id: "q_culture"
                  texte: "Quelle culture ?"
                  champ: "occupation_sol"
                  branches:
                    - valeur: "colza"
                      regle:
                        id: "r_colza"
                        type: "interdiction"
        """
    )
    active = make_active_tree(yaml_text)
    # On clone l'actif en draft pour avoir mode=edition
    draft = DecisionTree.objects.create(
        name=active.name,
        status=DecisionTree.STATUS_DRAFT,
        contenu=active.contenu,
        contenu_yaml_brut=active.contenu_yaml_brut,
        parent=active,
    )
    return draft


def test_deep_btn_in_summary_before_edit_actions(client, staff_user, draft_tree):
    """En mode edition, le deep-btn doit etre dans le <summary>, place
    AVANT les .yaml-tree__edit-actions (le CSS les colle a droite via
    margin-left:auto sur deep-btn)."""
    client.force_login(staff_user)
    url = reverse("nitrates_admin_yaml_tree") + f"?tree_id={draft_tree.pk}&mode=edition"
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()

    # Le deep-btn doit etre present (au moins pour le noeud racine qui a des branches)
    assert "yaml-tree__deep-btn" in body, "deep-btn absent du rendu"
    # Et la classe edit-actions aussi (on est en mode edition)
    assert "yaml-tree__edit-actions" in body, "edit-actions absents en mode edition"

    # On verifie l'ordre dans le DOM : deep-btn doit apparaitre AVANT
    # edit-actions sur la racine. Les autres lignes (regles, branches)
    # n'ont pas de deep-btn.
    deep_idx = body.find("yaml-tree__deep-btn")
    actions_idx = body.find("yaml-tree__edit-actions", deep_idx)
    assert (
        deep_idx > 0 and actions_idx > deep_idx
    ), "deep-btn doit etre avant les edit-actions dans le HTML"


def test_deep_btn_inside_summary_not_outside_details(client, staff_user, draft_tree):
    """Le deep-btn doit etre DANS le <summary> (avec les autres elements
    de la row), pas en frere du <details> en position absolute. C'est
    cet emplacement qui evitait le chevauchement."""
    client.force_login(staff_user)
    url = reverse("nitrates_admin_yaml_tree") + f"?tree_id={draft_tree.pk}&mode=edition"
    body = client.get(url).content.decode()

    # Pattern : on cherche le 1er deep-btn et on remonte. Il doit etre
    # entre <summary ...> et </summary>, pas avant <details>.
    deep_idx = body.find("yaml-tree__deep-btn")
    assert deep_idx > 0

    # Cherche la position du <summary> qui le contient
    summary_open = body.rfind("<summary", 0, deep_idx)
    summary_close = body.find("</summary>", deep_idx)
    details_open = body.rfind("<details", 0, deep_idx)
    assert summary_open > 0, "deep-btn pas precede d'un <summary>"
    assert summary_close > deep_idx, "deep-btn pas suivi d'un </summary>"
    # Le <details> doit etre encore avant le <summary> qui l'entoure
    assert details_open < summary_open
