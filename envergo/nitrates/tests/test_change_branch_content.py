"""Changer le TYPE de contenu d'une branche feuille sans la supprimer/recreer.

renvoi_vers <-> feuille_vide <-> regle <-> renvoi_arbre. Reserve aux branches
feuilles (pas de sous-arbre a perdre).
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from envergo.nitrates.models import DecisionTree
from envergo.nitrates.yaml_admin import editor

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]


def _arbre():
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
                "branches": [
                    {"valeur": "autre", "renvoi_vers": "q_inexistant"},
                    {
                        "valeur": True,
                        "noeud": {
                            "type_noeud": "formulaire",
                            "id": "q_x",
                            "champ": "occ",
                            "niveau": "culture",
                            "texte": "?",
                            "branches": [
                                {"valeur": "a", "regle": {"id": "r_a", "type": "libre"}}
                            ],
                        },
                    },
                ],
            }
        }
    }


@pytest.fixture
def setup(db):
    u = get_user_model().objects.create_user(
        email="c@t.local", name="C", password="x", is_staff=True, is_superuser=True
    )
    t = DecisionTree.objects.create(
        name="cc", status="draft", scope="zar", region_code="44", contenu=_arbre()
    )
    c = Client()
    c.force_login(u)
    return c, t


def test_change_renvoi_vers_en_feuille_vide(setup):
    c, t = setup
    url = (
        f"/admin/nitrates/arbre-decision/{t.pk}/edit/change-content/"
        f"?path=n_zvn&valeur=autre"
    )
    r = c.post(url, {"kind": "feuille_vide"})
    assert r.status_code == 200
    t.refresh_from_db()
    br = editor.get_branche_at(t.contenu, ("n_zvn",), "autre")
    assert br.get("feuille_vide") is True
    assert "renvoi_vers" not in br  # l'ancien contenu a disparu


def test_change_refuse_branche_avec_sous_arbre(setup):
    """La branche True porte un noeud -> changer son type est refusé (403)."""
    c, t = setup
    url = (
        f"/admin/nitrates/arbre-decision/{t.pk}/edit/change-content/"
        f"?path=n_zvn&valeur=True"
    )
    r = c.get(url)
    assert r.status_code == 403


def test_get_form_preselectionne_le_kind_courant(setup):
    c, t = setup
    url = (
        f"/admin/nitrates/arbre-decision/{t.pk}/edit/change-content/"
        f"?path=n_zvn&valeur=autre"
    )
    r = c.get(url)
    assert r.status_code == 200
    body = r.content.decode()
    # renvoi_vers (kind courant) doit etre l'option selectionnee.
    assert 'value="renvoi_vers" selected' in body
