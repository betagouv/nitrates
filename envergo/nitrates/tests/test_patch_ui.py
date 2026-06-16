"""Edition UI du patch code_prescription sur une branche renvoi_vers (#142).
Le patch est saisi en textarea (une regle 'pcX -> pcY' par ligne) -> supporte
le multi-remap."""

import pytest
from django.test import Client

from envergo.nitrates.models import DecisionTree
from envergo.nitrates.views_admin_yaml_edit import _parse_patch_pc
from envergo.nitrates.yaml_admin import editor
from envergo.users.models import User

pytestmark = pytest.mark.django_db


def test_parse_patch_pc():
    assert _parse_patch_pc("pc13 -> pc14") == {"pc13": "pc14"}
    assert _parse_patch_pc("pc13 -> pc14\npc12 -> pc16") == {
        "pc13": "pc14",
        "pc12": "pc16",
    }
    assert _parse_patch_pc("pc13:pc14") == {"pc13": "pc14"}
    assert _parse_patch_pc("\n  \n") == {}
    assert _parse_patch_pc("ligne sans separateur") == {}


@pytest.fixture
def setup(db):
    u = User.objects.create(email="p@t.local", is_staff=True, is_superuser=True)
    cible = {
        "type_noeud": "formulaire",
        "id": "n_cible",
        "champ": "tf",
        "niveau": "type_fertilisant",
        "texte": "?",
        "branches": [
            {
                "valeur": "type_II",
                "regle": {
                    "id": "r_c",
                    "type": "plafonnement",
                    "code_prescription": "pc13",
                },
            }
        ],
    }
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
                "source": "sig",
                "branches": [
                    {
                        "valeur": True,
                        "noeud": {
                            "type_noeud": "formulaire",
                            "id": "q_occ",
                            "champ": "occupation_sol",
                            "niveau": "culture",
                            "texte": "?",
                            "branches": [
                                {"valeur": "cible", "noeud": cible},
                                {"valeur": "source", "renvoi_vers": "n_cible"},
                            ],
                        },
                    },
                ],
            }
        }
    }
    t = DecisionTree.objects.create(
        name="t",
        status="draft",
        scope="zar",
        region_code="44",
        contenu=arbre,
        contenu_yaml_brut="",
    )
    c = Client()
    c.force_login(u)
    return c, t


def _post(c, t, patch_pc):
    return c.post(
        f"/admin/nitrates/arbre-decision/{t.pk}/edit/branche/?path=n_zvn/q_occ&valeur=source",
        {"valeur_new": "source", "renvoi_vers_new": "n_cible", "patch_pc": patch_pc},
    )


def test_edit_branche_pose_patch_simple(setup):
    c, t = setup
    assert _post(c, t, "pc13 -> pc14").status_code == 200
    t.refresh_from_db()
    br = editor.get_branche_at(t.contenu, ("n_zvn", "q_occ"), "source")
    assert br["patch"] == {"code_prescription": {"pc13": "pc14"}}


def test_edit_branche_pose_patch_multi(setup):
    c, t = setup
    assert _post(c, t, "pc13 -> pc14\npc12 -> pc16").status_code == 200
    t.refresh_from_db()
    br = editor.get_branche_at(t.contenu, ("n_zvn", "q_occ"), "source")
    assert br["patch"]["code_prescription"] == {"pc13": "pc14", "pc12": "pc16"}


def test_edit_branche_retire_patch_si_vide(setup):
    c, t = setup
    _post(c, t, "pc13 -> pc14")
    _post(c, t, "")
    t.refresh_from_db()
    br = editor.get_branche_at(t.contenu, ("n_zvn", "q_occ"), "source")
    assert "patch" not in br
