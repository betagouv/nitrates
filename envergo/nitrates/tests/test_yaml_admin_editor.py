"""Tests du service editor.py (mutations atomiques avec validation +
revision automatique)."""

import copy

import pytest
from django.contrib.auth import get_user_model

from envergo.nitrates.models import DecisionTree, DecisionTreeRevision
from envergo.nitrates.yaml_admin import editor

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _purge():
    DecisionTree.objects.all().delete()


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user(
        email="alice@test.local", name="Alice", password="x", is_staff=True
    )


@pytest.fixture
def base_arbre():
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_root",
                "champ": "z",
                "source": "sig",
                "branches": [
                    {
                        "valeur": True,
                        "noeud": {
                            "type_noeud": "formulaire",
                            "niveau": "culture",
                            "id": "q_culture",
                            "champ": "c",
                            "texte": "Culture ?",
                            "branches": [
                                {
                                    "valeur": "colza",
                                    "regle": {
                                        "id": "r_colza",
                                        "type": "interdiction",
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        }
    }


@pytest.fixture
def draft(base_arbre):
    return DecisionTree.objects.create(
        name="d",
        status=DecisionTree.STATUS_DRAFT,
        contenu=copy.deepcopy(base_arbre),
        contenu_yaml_brut="placeholder",
    )


# ─── Lookups ───────────────────────────────────────────────────────────────


def test_get_node_at_racine(base_arbre):
    node = editor.get_node_at(base_arbre, ("n_root",))
    assert node is not None
    assert node["id"] == "n_root"


def test_get_node_at_descendant(base_arbre):
    node = editor.get_node_at(base_arbre, ("n_root", "q_culture"))
    assert node["id"] == "q_culture"


def test_get_node_at_invalide(base_arbre):
    assert editor.get_node_at(base_arbre, ("inexistant",)) is None
    assert editor.get_node_at(base_arbre, ("n_root", "inexistant")) is None


def test_get_branche_at(base_arbre):
    b = editor.get_branche_at(base_arbre, ("n_root", "q_culture"), "colza")
    assert b is not None
    assert b["regle"]["id"] == "r_colza"


def test_get_branche_at_tolere_str_vs_bool():
    """Regression : une branche de catalogue_parametre peut porter la valeur
    string 'False' alors que la vue passe le bool False (coercion query
    string). Le match doit retomber sur la comparaison string -> sinon 403
    'Règle introuvable' à l'édition."""
    arbre = {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue_parametre",
                "id": "n_cp",
                "champ": "x",
                "branches": [
                    {"valeur": True, "regle": {"id": "r_t", "type": "libre"}},
                    {"valeur": "False", "regle": {"id": "r_f", "type": "libre"}},
                ],
            }
        }
    }
    # bool False (ce que _parse_valeur produit) doit retrouver la branche 'False'.
    b = editor.get_branche_at(arbre, ("n_cp",), False)
    assert b is not None and b["regle"]["id"] == "r_f"
    # bool True matche exactement.
    b2 = editor.get_branche_at(arbre, ("n_cp",), True)
    assert b2 is not None and b2["regle"]["id"] == "r_t"


# ─── update_node ───────────────────────────────────────────────────────────


def test_update_node_modifie_les_champs(draft, alice):
    res = editor.update_node(
        draft,
        ("n_root", "q_culture"),
        {"texte": "Quelle culture est cultivée ?", "aide": "Réponse libre"},
        alice,
    )
    assert res.ok
    draft.refresh_from_db()
    node = editor.get_node_at(draft.contenu, ("n_root", "q_culture"))
    assert node["texte"] == "Quelle culture est cultivée ?"
    assert node["aide"] == "Réponse libre"


def test_update_node_preserve_les_branches(draft, alice):
    res = editor.update_node(
        draft, ("n_root", "q_culture"), {"texte": "x", "aide": "y"}, alice
    )
    assert res.ok
    draft.refresh_from_db()
    node = editor.get_node_at(draft.contenu, ("n_root", "q_culture"))
    assert len(node["branches"]) == 1
    assert node["branches"][0]["valeur"] == "colza"


def test_update_node_refuse_id_collision(draft, alice):
    """On ne peut pas changer l'id d'un noeud pour un id deja pris ailleurs."""
    res = editor.update_node(draft, ("n_root", "q_culture"), {"id": "n_root"}, alice)
    assert not res.ok


def test_update_node_garde_son_propre_id(draft, alice):
    """Un noeud peut conserver son id sans declencher de fausse collision."""
    res = editor.update_node(
        draft,
        ("n_root", "q_culture"),
        {"id": "q_culture", "texte": "Culture maj"},
        alice,
    )
    assert res.ok


def test_update_node_inexistant(draft, alice):
    res = editor.update_node(draft, ("inexistant",), {"texte": "x"}, alice)
    assert not res.ok


def test_update_node_enregistre_revision(draft, alice):
    avant = draft.revisions.count()
    editor.update_node(draft, ("n_root", "q_culture"), {"texte": "Culture maj"}, alice)
    apres = draft.revisions.count()
    assert apres == avant + 1


def test_update_node_invalide_ne_mute_pas(draft, alice):
    """Si la validation echoue, le tree n'est pas modifie."""
    avant = copy.deepcopy(draft.contenu)
    res = editor.update_node(
        draft, ("n_root", "q_culture"), {"niveau": "n_importe_quoi"}, alice
    )
    assert not res.ok
    draft.refresh_from_db()
    assert draft.contenu == avant


# ─── update_regle ──────────────────────────────────────────────────────────


def test_update_regle_modifie_les_periodes(draft, alice):
    res = editor.update_regle(
        draft,
        ("n_root", "q_culture"),
        "colza",
        {
            "id": "r_colza",
            "type": "interdiction",
            "periodes": [{"du": "15/12", "au": "15/01"}],
        },
        alice,
    )
    assert res.ok
    draft.refresh_from_db()
    branche = editor.get_branche_at(draft.contenu, ("n_root", "q_culture"), "colza")
    assert branche["regle"]["periodes"] == [{"du": "15/12", "au": "15/01"}]


def test_update_regle_date_invalide(draft, alice):
    res = editor.update_regle(
        draft,
        ("n_root", "q_culture"),
        "colza",
        {
            "id": "r_colza",
            "type": "interdiction",
            "periodes": [{"du": "32/13", "au": "01/01"}],
        },
        alice,
    )
    assert not res.ok


def test_update_regle_periode_condition_persistee(draft, alice):
    """La cle `condition` sur une periode doit etre preservee a travers
    update_regle + round-trip YAML (cf. spec_extension_grammaire_condition)."""
    res = editor.update_regle(
        draft,
        ("n_root", "q_culture"),
        "colza",
        {
            "id": "r_colza",
            "type": "interdiction",
            "periodes": [
                {
                    "du": "15/11",
                    "au": "15/01",
                    "regime": "autorisation_sous_condition",
                    "condition": "date_destruction_couvert >= 05/12",
                }
            ],
        },
        alice,
    )
    assert res.ok, res.errors
    draft.refresh_from_db()
    branche = editor.get_branche_at(draft.contenu, ("n_root", "q_culture"), "colza")
    p = branche["regle"]["periodes"][0]
    assert p.get("condition") == "date_destruction_couvert >= 05/12"
    # Verifie aussi que le YAML brut contient le mot 'condition'
    assert "condition:" in draft.contenu_yaml_brut


def test_update_regle_periode_condition_via_form_post(draft, alice):
    """Simule le path complet : POST -> RegleForm -> to_new_data -> editor.
    Reproduit exactement ce qui se passe quand l'utilisateur soumet le form."""
    from envergo.nitrates.yaml_admin.forms import RegleForm

    form = RegleForm(
        {
            "id": "r_colza",
            "type": "interdiction",
            "periodes-0-du": "15/11",
            "periodes-0-au": "15/01",
            "periodes-0-regime": "autorisation_sous_condition",
            "periodes-0-condition": "date_destruction_couvert >= 05/12",
        }
    )
    assert form.is_valid(), form.errors
    new_data = form.to_new_data()
    res = editor.update_regle(draft, ("n_root", "q_culture"), "colza", new_data, alice)
    assert res.ok, res.errors
    draft.refresh_from_db()
    branche = editor.get_branche_at(draft.contenu, ("n_root", "q_culture"), "colza")
    p = branche["regle"]["periodes"][0]
    assert (
        p.get("condition") == "date_destruction_couvert >= 05/12"
    ), f"condition perdue. Periode complete : {dict(p)}"
    # Round-trip YAML : recharge depuis le YAML brut et verifie que la
    # condition est preservee (cas du reload page apres save).
    from ruamel.yaml import YAML

    yaml = YAML(typ="rt")
    contenu_recharge = yaml.load(draft.contenu_yaml_brut)
    branche_rechargee = editor.get_branche_at(
        contenu_recharge, ("n_root", "q_culture"), "colza"
    )
    assert (
        branche_rechargee["regle"]["periodes"][0].get("condition")
        == "date_destruction_couvert >= 05/12"
    )


# ─── add_branch ────────────────────────────────────────────────────────────


def test_add_branch_squelette_vide_ok(draft, alice):
    """On peut ajouter une branche sans contenu (squelette draft)."""
    res = editor.add_branch(
        draft, ("n_root", "q_culture"), {"valeur": "luzerne"}, alice
    )
    assert res.ok
    draft.refresh_from_db()
    parent = editor.get_node_at(draft.contenu, ("n_root", "q_culture"))
    valeurs = [b["valeur"] for b in parent["branches"]]
    assert "luzerne" in valeurs


def test_add_branch_collision_valeur(draft, alice):
    """Refus si une branche avec la meme valeur existe deja."""
    res = editor.add_branch(draft, ("n_root", "q_culture"), {"valeur": "colza"}, alice)
    assert not res.ok


def test_add_branch_sans_valeur_ko(draft, alice):
    res = editor.add_branch(draft, ("n_root", "q_culture"), {}, alice)
    assert not res.ok


def test_add_branch_parent_inexistant(draft, alice):
    res = editor.add_branch(draft, ("inexistant",), {"valeur": "x"}, alice)
    assert not res.ok


# ─── update_branch_content ─────────────────────────────────────────────────


def test_set_branch_content_regle_ok(draft, alice):
    """On insere une regle dans une branche vide."""
    editor.add_branch(draft, ("n_root", "q_culture"), {"valeur": "luzerne"}, alice)
    draft.refresh_from_db()
    res = editor.update_branch_content(
        draft,
        ("n_root", "q_culture"),
        "luzerne",
        "regle",
        {"id": "r_luzerne", "type": "interdiction"},
        alice,
    )
    assert res.ok
    draft.refresh_from_db()
    b = editor.get_branche_at(draft.contenu, ("n_root", "q_culture"), "luzerne")
    assert b["regle"]["id"] == "r_luzerne"


def test_set_branch_content_renvoi_arbre_avec_noeud_cible(draft, alice):
    """#222 : un renvoi_arbre persiste aussi son noeud_cible (renvoi cross-arbre
    cible), pas seulement la cle renvoi_arbre."""
    editor.add_branch(draft, ("n_root", "q_culture"), {"valeur": "legumes"}, alice)
    draft.refresh_from_db()
    res = editor.update_branch_content(
        draft,
        ("n_root", "q_culture"),
        "legumes",
        "renvoi_arbre",
        {"renvoi_arbre": "national", "noeud_cible": "q_printemps_fert"},
        alice,
    )
    assert res.ok
    draft.refresh_from_db()
    b = editor.get_branche_at(draft.contenu, ("n_root", "q_culture"), "legumes")
    assert b["renvoi_arbre"] == "national"
    assert b["noeud_cible"] == "q_printemps_fert"


def test_set_branch_content_renvoi_arbre_change_nettoie_noeud_cible(draft, alice):
    """#222 : repasser sur un renvoi_arbre SANS noeud_cible retire l'ancien
    noeud_cible (pas de residu), et changer de kind aussi."""
    editor.add_branch(draft, ("n_root", "q_culture"), {"valeur": "legumes"}, alice)
    draft.refresh_from_db()
    editor.update_branch_content(
        draft,
        ("n_root", "q_culture"),
        "legumes",
        "renvoi_arbre",
        {"renvoi_arbre": "national", "noeud_cible": "q_printemps_fert"},
        alice,
    )
    draft.refresh_from_db()
    # Re-renvoi_arbre sans noeud_cible : l'ancien doit disparaitre.
    editor.update_branch_content(
        draft,
        ("n_root", "q_culture"),
        "legumes",
        "renvoi_arbre",
        {"renvoi_arbre": "national"},
        alice,
    )
    draft.refresh_from_db()
    b = editor.get_branche_at(draft.contenu, ("n_root", "q_culture"), "legumes")
    assert b["renvoi_arbre"] == "national"
    assert "noeud_cible" not in b


def test_set_branch_content_remplace_existant(draft, alice):
    """Si la branche a deja un contenu, il est remplace."""
    res = editor.update_branch_content(
        draft,
        ("n_root", "q_culture"),
        "colza",
        "regle",
        {"id": "r_colza_v2", "type": "libre"},
        alice,
    )
    assert res.ok
    draft.refresh_from_db()
    b = editor.get_branche_at(draft.contenu, ("n_root", "q_culture"), "colza")
    assert b["regle"]["id"] == "r_colza_v2"
    assert b["regle"]["type"] == "libre"


def test_set_branch_content_kind_interdit(draft, alice):
    """On ne peut pas inserer un noeud_formulaire_culture sous un noeud
    qui a deja un parent culture (ordre des niveaux)."""
    # On ajoute une branche luzerne vide sous q_culture (niveau culture).
    editor.add_branch(draft, ("n_root", "q_culture"), {"valeur": "luzerne"}, alice)
    draft.refresh_from_db()
    # Tenter d'inserer un noeud_formulaire_culture (deja vu) -> KO
    res = editor.update_branch_content(
        draft,
        ("n_root", "q_culture"),
        "luzerne",
        "noeud_formulaire_culture",
        {
            "type_noeud": "formulaire",
            "niveau": "culture",
            "id": "q_culture_2",
            "champ": "c2",
            "texte": "x",
        },
        alice,
    )
    assert not res.ok


def test_set_branch_content_validation_locale(draft, alice):
    """Le contenu lui-meme est valide (niveau 1) avant insertion."""
    editor.add_branch(draft, ("n_root", "q_culture"), {"valeur": "luzerne"}, alice)
    draft.refresh_from_db()
    # regle sans type ni a_completer -> validation locale ko
    res = editor.update_branch_content(
        draft,
        ("n_root", "q_culture"),
        "luzerne",
        "regle",
        {"id": "r_invalide"},  # pas de type !
        alice,
    )
    assert not res.ok


# ─── delete_branch ─────────────────────────────────────────────────────────


def test_delete_branch_ok(draft, alice):
    res = editor.delete_branch(draft, ("n_root", "q_culture"), "colza", alice)
    assert res.ok
    draft.refresh_from_db()
    parent = editor.get_node_at(draft.contenu, ("n_root", "q_culture"))
    assert all(b["valeur"] != "colza" for b in parent.get("branches", []))


def test_delete_branch_inexistante(draft, alice):
    res = editor.delete_branch(draft, ("n_root", "q_culture"), "fictive", alice)
    assert not res.ok


# ─── delete_node ───────────────────────────────────────────────────────────


def test_delete_node_descendant_ok(draft, alice):
    """Supprimer q_culture supprime la branche True du parent qui le portait."""
    res = editor.delete_node(draft, ("n_root", "q_culture"), alice)
    assert res.ok
    draft.refresh_from_db()
    racine = editor.get_node_at(draft.contenu, ("n_root",))
    assert all(
        not (isinstance(b.get("noeud"), dict) and b["noeud"].get("id") == "q_culture")
        for b in racine.get("branches", [])
    )


def test_delete_node_racine_refuse(draft, alice):
    res = editor.delete_node(draft, ("n_root",), alice)
    assert not res.ok


# ─── revisions et undo ─────────────────────────────────────────────────────


def test_chaque_mutation_genere_revision(draft, alice):
    avant = draft.revisions.count()
    editor.update_node(draft, ("n_root", "q_culture"), {"texte": "x"}, alice)
    editor.add_branch(draft, ("n_root", "q_culture"), {"valeur": "luzerne"}, alice)
    editor.delete_branch(draft, ("n_root", "q_culture"), "colza", alice)
    apres = draft.revisions.count()
    assert apres == avant + 3


def test_revision_metadata_action(draft, alice):
    editor.add_branch(draft, ("n_root", "q_culture"), {"valeur": "luzerne"}, alice)
    rev = draft.revisions.first()
    assert rev.action == DecisionTreeRevision.ACTION_ADD


def test_undo_via_restore(draft, alice):
    """On modifie, puis on restaure : le tree revient a l'etat d'avant."""
    avant_contenu = copy.deepcopy(draft.contenu)
    editor.update_node(draft, ("n_root", "q_culture"), {"texte": "modifie"}, alice)
    # La revision capturee est celle d'avant la mutation
    rev = draft.revisions.first()
    rev.restore()
    draft.refresh_from_db()
    # Apres restore, on retombe sur l'etat initial
    node = editor.get_node_at(draft.contenu, ("n_root", "q_culture"))
    assert (
        node["texte"]
        == avant_contenu["arbre"]["noeud"]["branches"][0]["noeud"]["texte"]
    )


# ─── reorder_branches ──────────────────────────────────────────────────────


def test_reorder_branches_permute(draft, alice):
    """Ajoute 2 branches puis permute leur ordre. Les contenus suivent."""
    editor.add_branch(draft, ("n_root", "q_culture"), {"valeur": "luzerne"}, alice)
    editor.add_branch(draft, ("n_root", "q_culture"), {"valeur": "ble"}, alice)
    draft.refresh_from_db()
    node = editor.get_node_at(draft.contenu, ("n_root", "q_culture"))
    valeurs_avant = [b["valeur"] for b in node["branches"]]
    assert valeurs_avant == ["colza", "luzerne", "ble"]

    # Permute : ble en premier, puis colza, puis luzerne.
    res = editor.reorder_branches(
        draft, ("n_root", "q_culture"), ["ble", "colza", "luzerne"], alice
    )
    assert res.ok, res.errors
    draft.refresh_from_db()
    node = editor.get_node_at(draft.contenu, ("n_root", "q_culture"))
    valeurs_apres = [b["valeur"] for b in node["branches"]]
    assert valeurs_apres == ["ble", "colza", "luzerne"]
    # Le contenu de la branche colza (avec sa regle r_colza) est preserve.
    colza = next(b for b in node["branches"] if b["valeur"] == "colza")
    assert colza["regle"]["id"] == "r_colza"


def test_reorder_branches_refuse_si_valeurs_mismatch(draft, alice):
    """Si la liste d'ordre ne matche pas exactement les branches existantes,
    on refuse (pas d'ajout ni suppression possible via reorder)."""
    res = editor.reorder_branches(
        draft, ("n_root", "q_culture"), ["valeur_inconnue"], alice
    )
    assert not res.ok


def test_reorder_branches_revision_creee(draft, alice):
    editor.add_branch(draft, ("n_root", "q_culture"), {"valeur": "luzerne"}, alice)
    avant = draft.revisions.count()
    editor.reorder_branches(draft, ("n_root", "q_culture"), ["luzerne", "colza"], alice)
    assert draft.revisions.count() == avant + 1
