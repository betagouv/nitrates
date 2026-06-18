"""Intercalation d'un noeud parent (editeur YAML admin).

Declenchee depuis la barre d'actions d'un noeud A (icone ⤴) : un nouveau noeud
N s'insere juste AU-DESSUS de A.

Avant :  P --[X]--> A      Apres :  P --[X]--> N --[a_definir]--> A
A (et tout son sous-arbre) descend sous une branche placeholder de N.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from envergo.nitrates.models import DecisionTree
from envergo.nitrates.yaml_admin import editor

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]


def _arbre():
    """Racine catalogue ZV -> branche True -> noeud formulaire culture avec DEUX
    branches (colza, ble) portant chacune une regle."""
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_zvn",
                "champ": "en_zone_vulnerable",
                "source": "sig",
                "reference": "zone_vulnerable_nitrates",
                "branches": [
                    {
                        "valeur": True,
                        "noeud": {
                            "type_noeud": "formulaire",
                            "id": "q_culture",
                            "champ": "occupation_sol",
                            "niveau": "culture",
                            "texte": "Culture ?",
                            "branches": [
                                {
                                    "valeur": "colza",
                                    "regle": {"id": "r_colza", "type": "interdiction"},
                                },
                                {
                                    "valeur": "ble",
                                    "regle": {"id": "r_ble", "type": "interdiction"},
                                },
                            ],
                        },
                    },
                ],
            }
        }
    }


@pytest.fixture
def staff_client(db):
    User = get_user_model()
    u = User.objects.create_user(
        email="ip@test.local", name="IP", password="x", is_staff=True, is_superuser=True
    )
    c = Client()
    c.force_login(u)
    return c, u


@pytest.fixture
def draft(db, staff_client):
    _, u = staff_client
    return DecisionTree.objects.create(
        name="ip", status="draft", contenu=_arbre(), created_by=u
    )


# ─── mutator / fonction editor ───────────────────────────────────────────────


def _content_complement():
    return {
        "id": "q_complement",
        "type_noeud": "formulaire",
        "niveau": "complement",
        "champ": "irrigue",
        "texte": "Irrigué ?",
        "branches": [],
    }


def test_insert_parent_encapsule_le_noeud(draft, staff_client):
    """Intercale N au-dessus de q_culture : la branche True de n_zvn porte
    desormais N ; N a une unique branche 'a_definir' -> q_culture intact (avec
    ses deux branches colza/ble)."""
    _, u = staff_client
    res = editor.insert_parent(
        draft,
        ("n_zvn", "q_culture"),
        "noeud_formulaire_complement",
        _content_complement(),
        u,
    )
    assert res.ok, [e.message for e in res.errors]
    draft.refresh_from_db()
    # La branche True de n_zvn porte maintenant le nouveau noeud N.
    br_true = editor.get_branche_at(draft.contenu, ("n_zvn",), True)
    n = br_true["noeud"]
    assert n["id"] == "q_complement"
    # N a une unique branche placeholder -> q_culture inchange.
    assert len(n["branches"]) == 1
    placeholder = n["branches"][0]
    assert placeholder["valeur"] == "a_definir"
    q = placeholder["noeud"]
    assert q["id"] == "q_culture"
    assert {b["valeur"] for b in q["branches"]} == {"colza", "ble"}
    assert {b["regle"]["id"] for b in q["branches"]} == {"r_colza", "r_ble"}


def test_insert_parent_refuse_kind_non_noeud(draft, staff_client):
    """On ne peut pas intercaler une regle/renvoi (N doit avoir une branche
    pour heberger A)."""
    _, u = staff_client
    res = editor.insert_parent(draft, ("n_zvn", "q_culture"), "regle", {"id": "r_x"}, u)
    assert not res.ok


def test_insert_parent_refuse_racine(draft, staff_client):
    """On ne peut pas intercaler au-dessus de la racine."""
    _, u = staff_client
    res = editor.insert_parent(
        draft, (), "noeud_formulaire_complement", _content_complement(), u
    )
    assert not res.ok


# ─── flux HTTP ───────────────────────────────────────────────────────────────


def test_insert_parent_get_form(draft, staff_client):
    c, _ = staff_client
    url = (
        f"/admin/nitrates/arbre-decision/{draft.pk}/edit/insert-parent/"
        f"?path=n_zvn/q_culture"
    )
    r = c.get(url)
    assert r.status_code == 200
    body = r.content.decode()
    assert 'name="kind"' in body
    # Seuls des noeuds proposes (pas regle/renvoi).
    assert "noeud_formulaire" in body or "noeud_catalogue" in body
    assert 'value="regle"' not in body


def test_insert_parent_post_ok(draft, staff_client):
    c, _ = staff_client
    url = (
        f"/admin/nitrates/arbre-decision/{draft.pk}/edit/insert-parent/"
        f"?path=n_zvn/q_culture"
    )
    r = c.post(
        url,
        {
            "kind": "noeud_formulaire_complement",
            "c_texte": "Irrigué ?",
            "c_champ": "irrigue",
        },
    )
    assert r.status_code == 200
    draft.refresh_from_db()
    # N est intercale au-dessus de q_culture, sous la branche True de n_zvn.
    br_true = editor.get_branche_at(draft.contenu, ("n_zvn",), True)
    n = br_true["noeud"]
    assert n["niveau"] == "complement"
    assert len(n["branches"]) == 1
    q = n["branches"][0]["noeud"]
    assert q["id"] == "q_culture"
    assert {b["valeur"] for b in q["branches"]} == {"colza", "ble"}
