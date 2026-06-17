"""Regression compat : le form d'edition d'une regle pre-remplit le widget
multi-PC, que la PC soit stockee en scalaire (forme historique) ou en liste.

Bug initial : une PC scalaire `code_prescription: "pc4"` ne s'affichait pas dans
le 1er menu deroulant a la reouverture du form (le template iterait sur
`regle.codes_prescription` absent du dict YAML brut).
"""

import re

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from envergo.nitrates.models import DecisionTree

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]


def _arbre(cp):
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
                "branches": [
                    {
                        "valeur": True,
                        "regle": {
                            "id": "r_x",
                            "type": "interdiction",
                            "code_prescription": cp,
                        },
                    }
                ],
            }
        }
    }


@pytest.fixture
def cli(db):
    u = get_user_model().objects.create_user(
        email="pcf@t.local", name="z", password="x", is_staff=True, is_superuser=True
    )
    c = Client()
    c.force_login(u)
    return c


def _form_body(cli, arbre):
    t = DecisionTree.objects.create(name="x", status="draft", contenu=arbre)
    url = f"/admin/nitrates/arbre-decision/{t.pk}/edit/regle/?path=n_zvn&valeur=True"
    return cli.get(url).content.decode()


def test_preremplit_pc_scalaire(cli):
    body = _form_body(cli, _arbre("pc4"))
    assert re.search(r'value="pc4"[^>]*selected', body), "pc4 doit etre pre-selectionne"


def test_preremplit_pc_liste(cli):
    body = _form_body(cli, _arbre(["pc4", "pc11"]))
    assert re.search(r'value="pc4"[^>]*selected', body)
    assert re.search(r'value="pc11"[^>]*selected', body)
