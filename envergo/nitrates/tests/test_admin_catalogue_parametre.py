"""Tests de l'édition admin des nœuds catalogue_parametre (#128, couche UI).

Couvre :
  - grammar : kind autorisé, validation du nœud et des expressions de branche
  - editor : mapping kind <-> type_noeud
  - vue AddChildView : le formulaire expose le champ expression sous un
    parent catalogue_parametre, et le POST crée la branche valeur+expression
"""

import pytest
from django.test import Client

from envergo.nitrates.models import DecisionTree
from envergo.nitrates.yaml_admin import editor, grammar
from envergo.users.models import User

pytestmark = pytest.mark.django_db


def _arbre_minimal() -> dict:
    return {
        "metadata": {"version": "test"},
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
                            "type_noeud": "catalogue_parametre",
                            "id": "n_origine",
                            "champ": "effluent_peu_charge_elevage",
                            "branches": [],
                        },
                    },
                    {
                        "valeur": False,
                        "regle": {"id": "r_hors", "type": "non_applicable"},
                    },
                ],
            }
        },
    }


# ─── grammar ────────────────────────────────────────────────────────────────


def test_un_seul_kind_catalogue_dans_le_dropdown():
    """Fusion UX : pas de kind separe catalogue_parametre dans le dropdown.
    Le mode expression se choisit DANS le formulaire catalogue (source)."""
    allowed = grammar.get_allowed_child_kinds(_arbre_minimal(), ())
    assert "noeud_catalogue" in allowed
    assert "noeud_catalogue_parametre" not in allowed


def test_validate_noeud_catalogue_parametre_ok():
    node = {
        "type_noeud": "catalogue_parametre",
        "id": "n_origine",
        "champ": "effluent_peu_charge_elevage",
        "branches": [
            {"valeur": True, "expression": "sous_fertilisant == 'a'"},
        ],
    }
    res = grammar.validate_node_local(node, "noeud_catalogue_parametre")
    assert res.ok, [e.message for e in res.errors]


def test_validate_noeud_catalogue_parametre_champ_requis():
    node = {"type_noeud": "catalogue_parametre", "id": "n_x", "branches": []}
    res = grammar.validate_node_local(node, "noeud_catalogue_parametre")
    assert not res.ok
    assert any(e.field == "champ" for e in res.errors)


def test_validate_expression_dunder_rejetee():
    node = {
        "type_noeud": "catalogue_parametre",
        "id": "n_x",
        "champ": "origine",
        "branches": [{"valeur": True, "expression": "().__class__"}],
    }
    res = grammar.validate_node_local(node, "noeud_catalogue_parametre")
    assert not res.ok
    assert any("__class__" in e.message or "interdit" in e.message for e in res.errors)


def test_validate_branche_valeur_plus_expression_ok():
    errs = grammar._validate_branche(
        {"valeur": True, "expression": "sous_fertilisant == 'a'"}
    )
    assert errs == []


def test_validate_branche_expression_cassee_rejetee():
    errs = grammar._validate_branche({"valeur": True, "expression": "1 +"})
    assert len(errs) > 0


# ─── editor mapping ─────────────────────────────────────────────────────────


def test_kind_from_node_catalogue_parametre():
    node = {"type_noeud": "catalogue_parametre", "id": "n_x", "champ": "c"}
    assert editor._kind_from_node(node) == "noeud_catalogue_parametre"


def test_grammar_kind_mapping():
    assert (
        editor._grammar_kind_from_content_kind("noeud_catalogue_parametre")
        == "noeud_catalogue_parametre"
    )


# ─── vue AddChildView ───────────────────────────────────────────────────────


@pytest.fixture
def staff_client(db):
    u = User.objects.create(
        email="cp@test.local", is_staff=True, is_superuser=True, is_active=True
    )
    c = Client()
    c.force_login(u)
    return c, u


@pytest.fixture
def draft(db, staff_client):
    _, u = staff_client
    return DecisionTree.objects.create(
        name="cp-test", status="draft", contenu=_arbre_minimal(), created_by=u
    )


def test_form_expose_expression_sous_catalogue_parametre(staff_client, draft):
    c, _ = staff_client
    url = (
        f"/admin/nitrates/arbre-decision/{draft.pk}/edit/add-child/"
        f"?path=n_zvn/n_origine&kind=regle"
    )
    r = c.get(url)
    assert r.status_code == 200
    assert 'name="expression"' in r.content.decode()


def test_form_pas_d_expression_sous_catalogue_classique(staff_client, draft):
    c, _ = staff_client
    # Parent = racine (catalogue SIG classique) -> le formulaire d'ajout de
    # branche n'a pas de champ expression (celui-ci n'apparait que sous un
    # parent catalogue_parametre).
    url = (
        f"/admin/nitrates/arbre-decision/{draft.pk}/edit/add-child/"
        f"?path=n_zvn&kind=noeud_catalogue"
    )
    r = c.get(url)
    assert r.status_code == 200
    assert 'name="expression"' not in r.content.decode()


def test_form_catalogue_propose_source_expression(staff_client, draft):
    """Le dropdown source du formulaire catalogue inclut l'option expression."""
    c, _ = staff_client
    url = (
        f"/admin/nitrates/arbre-decision/{draft.pk}/edit/add-child/"
        f"?path=n_zvn&kind=noeud_catalogue"
    )
    r = c.get(url)
    html = r.content.decode()
    assert 'name="c_source"' in html
    assert 'value="expression"' in html


def test_post_catalogue_source_expression_cree_catalogue_parametre(staff_client, draft):
    """Choisir source=expression produit un nœud type_noeud=catalogue_parametre
    (sans source stockée)."""
    c, _ = staff_client
    url = f"/admin/nitrates/arbre-decision/{draft.pk}/edit/add-child/?path=n_zvn"
    post = {
        "kind": "noeud_catalogue",
        "valeur": "__test_cp__",
        "c_source": "expression",
        "c_champ": "origine_test",
        "c_id": "n_cp_via_source",
    }
    r = c.post(url, post)
    assert r.status_code == 200
    draft.refresh_from_db()
    node = editor.get_node_at(draft.contenu, ("n_zvn", "n_cp_via_source"))
    assert node is not None
    assert node["type_noeud"] == "catalogue_parametre"
    assert node["champ"] == "origine_test"
    assert "source" not in node


def test_post_branche_avec_expression(staff_client, draft):
    c, _ = staff_client
    url = (
        f"/admin/nitrates/arbre-decision/{draft.pk}/edit/add-child/"
        f"?path=n_zvn/n_origine"
    )
    post = {
        "kind": "regle",
        "valeur": "true",
        "expression": "sous_fertilisant == 'effluents_peu_charges_elevage'",
        "c_type": "interdiction",
        "c_id": "r_cp_oui",
    }
    r = c.post(url, post)
    assert r.status_code == 200
    draft.refresh_from_db()
    cp = editor.get_node_at(draft.contenu, ("n_zvn", "n_origine"))
    assert len(cp["branches"]) == 1
    branche = cp["branches"][0]
    assert branche["valeur"] is True
    assert (
        branche["expression"] == "sous_fertilisant == 'effluents_peu_charges_elevage'"
    )
    assert branche["regle"]["id"] == "r_cp_oui"


def test_post_branche_sans_expression_rejete(staff_client, draft):
    c, _ = staff_client
    url = (
        f"/admin/nitrates/arbre-decision/{draft.pk}/edit/add-child/"
        f"?path=n_zvn/n_origine"
    )
    post = {"kind": "regle", "valeur": "true", "c_type": "libre", "c_id": "r_x"}
    r = c.post(url, post)
    assert r.status_code == 422
    assert "expression" in r.content.decode().lower()


def test_post_branche_expression_dunder_rejete(staff_client, draft):
    c, _ = staff_client
    url = (
        f"/admin/nitrates/arbre-decision/{draft.pk}/edit/add-child/"
        f"?path=n_zvn/n_origine"
    )
    post = {
        "kind": "regle",
        "valeur": "true",
        "expression": "().__class__.__bases__",
        "c_type": "libre",
        "c_id": "r_x",
    }
    r = c.post(url, post)
    assert r.status_code == 422


# ─── Conversion complement -> catalogue_parametre (#128) ────────────────────


def _arbre_avec_complement() -> dict:
    """Arbre avec une question complémentaire effluent (true/false) sous un
    catalogue ZV, à convertir en catalogue_parametre."""
    return {
        "metadata": {"version": "test"},
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
                            "niveau": "complement",
                            "id": "q_effluent",
                            "champ": "effluent_peu_charge",
                            "texte": "S'agit-il d'un effluent peu chargé ?",
                            "aide": "aide test",
                            "branches": [
                                {
                                    "valeur": True,
                                    "libelle": "Oui",
                                    "regle": {"id": "r_oui", "type": "interdiction"},
                                },
                                {
                                    "valeur": False,
                                    "libelle": "Non",
                                    "regle": {"id": "r_non", "type": "libre"},
                                },
                            ],
                        },
                    },
                    {
                        "valeur": False,
                        "regle": {"id": "r_hz", "type": "non_applicable"},
                    },
                ],
            }
        },
    }


def test_convert_complement_preserve_branches_et_contenu(staff_client):
    c, u = staff_client
    draft = DecisionTree.objects.create(
        name="conv", status="draft", contenu=_arbre_avec_complement(), created_by=u
    )
    r = c.post(
        f"/admin/nitrates/arbre-decision/{draft.pk}/edit/"
        f"convert-catalogue-parametre/?path=n_zvn/q_effluent"
    )
    assert r.status_code == 200
    draft.refresh_from_db()
    node = editor.get_node_at(draft.contenu, ("n_zvn", "q_effluent"))
    # type converti
    assert node["type_noeud"] == "catalogue_parametre"
    # champ gardé, niveau/texte/aide retirés
    assert node["champ"] == "effluent_peu_charge"
    assert "niveau" not in node
    assert "texte" not in node
    assert "aide" not in node
    # branches + contenu préservés, expression vide ajoutée
    assert len(node["branches"]) == 2
    for b in node["branches"]:
        assert b["expression"] == ""
        assert "regle" in b  # contenu intact
    assert node["branches"][0]["valeur"] is True
    assert node["branches"][0]["regle"]["id"] == "r_oui"


def test_convert_racine_refuse(staff_client):
    c, u = staff_client
    draft = DecisionTree.objects.create(
        name="conv2", status="draft", contenu=_arbre_avec_complement(), created_by=u
    )
    r = c.post(
        f"/admin/nitrates/arbre-decision/{draft.pk}/edit/"
        f"convert-catalogue-parametre/?path=n_zvn"
    )
    assert r.status_code == 403


def test_convert_deja_catalogue_parametre_refuse(staff_client):
    c, u = staff_client
    draft = DecisionTree.objects.create(
        name="conv3", status="draft", contenu=_arbre_minimal(), created_by=u
    )
    r = c.post(
        f"/admin/nitrates/arbre-decision/{draft.pk}/edit/"
        f"convert-catalogue-parametre/?path=n_zvn/n_origine"
    )
    assert r.status_code == 403


def test_editer_branche_persiste_expression(staff_client):
    """Après conversion, éditer une branche enregistre son expression."""
    c, u = staff_client
    draft = DecisionTree.objects.create(
        name="conv4", status="draft", contenu=_arbre_avec_complement(), created_by=u
    )
    # convertit
    c.post(
        f"/admin/nitrates/arbre-decision/{draft.pk}/edit/"
        f"convert-catalogue-parametre/?path=n_zvn/q_effluent"
    )
    # édite la branche true pour lui donner une expression
    r = c.post(
        f"/admin/nitrates/arbre-decision/{draft.pk}/edit/branche/"
        f"?path=n_zvn/q_effluent&valeur=true",
        {
            "valeur_new": "true",
            "expression": "sous_fertilisant == 'effluents_peu_charges_elevage'",
            "libelle": "Oui",
        },
    )
    assert r.status_code == 200
    draft.refresh_from_db()
    node = editor.get_node_at(draft.contenu, ("n_zvn", "q_effluent"))
    btrue = [b for b in node["branches"] if b["valeur"] is True][0]
    assert btrue["expression"] == "sous_fertilisant == 'effluents_peu_charges_elevage'"


def test_editer_branche_expression_vide_rejetee(staff_client):
    c, u = staff_client
    draft = DecisionTree.objects.create(
        name="conv5", status="draft", contenu=_arbre_avec_complement(), created_by=u
    )
    c.post(
        f"/admin/nitrates/arbre-decision/{draft.pk}/edit/"
        f"convert-catalogue-parametre/?path=n_zvn/q_effluent"
    )
    r = c.post(
        f"/admin/nitrates/arbre-decision/{draft.pk}/edit/branche/"
        f"?path=n_zvn/q_effluent&valeur=true",
        {"valeur_new": "true", "expression": "", "libelle": "Oui"},
    )
    assert r.status_code == 422


def test_editer_branche_expression_dunder_rejetee(staff_client):
    c, u = staff_client
    draft = DecisionTree.objects.create(
        name="conv6", status="draft", contenu=_arbre_avec_complement(), created_by=u
    )
    c.post(
        f"/admin/nitrates/arbre-decision/{draft.pk}/edit/"
        f"convert-catalogue-parametre/?path=n_zvn/q_effluent"
    )
    r = c.post(
        f"/admin/nitrates/arbre-decision/{draft.pk}/edit/branche/"
        f"?path=n_zvn/q_effluent&valeur=true",
        {"valeur_new": "true", "expression": "().__class__", "libelle": "Oui"},
    )
    assert r.status_code == 422
