"""Tests de couverture pour les filtres/tags template de l'éditeur YAML admin
(envergo/nitrates/templatetags/yaml_admin_extras.py) : cas limites des
filtres simples (valeurs vides/None) et des tags de lien (admin_url_for_resultat,
preview_url...)."""

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from envergo.nitrates.models import DecisionTree
from envergo.nitrates.templatetags.yaml_admin_extras import (
    _stringify_valeur_for_url,
    admin_url_for_resultat,
    fold_link,
    is_open,
    preview_url,
    preview_url_regle,
    reset_link,
    split_filter,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _purge():
    DecisionTree.objects.all().delete()


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user(
        email="alice@test.local", name="Alice", password="x", is_staff=True
    )


# ─── Filtres simples : cas vides ────────────────────────────────────────────


def test_split_filter_valeur_vide_renvoie_liste_vide():
    assert split_filter("") == []
    assert split_filter(None) == []


def test_split_filter_separateur_par_defaut():
    assert split_filter("a,b,c") == ["a", "b", "c"]


def test_is_open_sans_set_renvoie_false():
    assert is_open(None, "n_root") is False


def test_is_open_path_present():
    assert is_open({"n_root", "n_autre"}, "n_root") is True


def test_reset_link_sans_querystring_base():
    assert reset_link("") == "?"
    assert reset_link(None) == "?"


def test_reset_link_avec_querystring_base():
    assert reset_link("vue=brut") == "?vue=brut"


def test_fold_link_retire_le_path_deja_ouvert():
    """Toggle : un path déjà dans `expand` doit en être retiré (pas dupliqué)."""
    url = fold_link("vue=arbre", ["n_root"], [], "n_root", deep=False)
    assert "expand=n_root" not in url


def test_fold_link_ajoute_le_path_absent():
    url = fold_link("vue=arbre", [], [], "n_root", deep=False)
    assert "expand=n_root" in url


def test_fold_link_mode_deep_retire_le_path():
    url = fold_link("vue=arbre", [], ["n_root"], "n_root", deep=True)
    assert "expand_deep=n_root" not in url


def test_stringify_valeur_for_url_bool_et_autres():
    assert _stringify_valeur_for_url(True) == "True"
    assert _stringify_valeur_for_url(False) == "False"
    assert _stringify_valeur_for_url("mais") == "mais"


# ─── preview_url / preview_url_regle : path vide ───────────────────────────


@pytest.fixture
def actif():
    return DecisionTree.objects.create(
        name="actif",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_NATIONAL,
        contenu={
            "arbre": {
                "noeud": {
                    "type_noeud": "catalogue",
                    "id": "n_root",
                    "champ": "en_zone_vulnerable",
                    "source": "sig",
                    "branches": [
                        {
                            "valeur": False,
                            "regle": {"id": "r_hors_zv", "type": "non_applicable"},
                        }
                    ],
                }
            }
        },
        contenu_yaml_brut="x: 1\n",
    )


def test_preview_url_sans_path_str_part_de_la_racine(actif):
    url = preview_url(actif.contenu, "", actif.pk, tree_status="active")
    assert url.startswith("/simulateur/")


def test_preview_url_regle_sans_parent_path_str(actif):
    url = preview_url_regle(actif.contenu, "", False, actif.pk, tree_status="active")
    assert url.startswith("/simulateur/")


def test_preview_url_tree_pk_inconnu_ne_casse_pas(actif):
    """Un tree_pk qui ne correspond a rien : _activation_point avale
    l'exception et retombe sur None, l'URL se construit normalement."""
    url = preview_url(actif.contenu, "", 999999, tree_status="active")
    assert url.startswith("/simulateur/")


# ─── admin_url_for_resultat ─────────────────────────────────────────────────


def _context_staff(user):
    request = RequestFactory().get("/")
    request.user = user
    return {"request": request}


def _context_non_staff():
    request = RequestFactory().get("/")

    class Anon:
        is_staff = False
        is_authenticated = False

    request.user = Anon()
    return {"request": request}


def test_admin_url_for_resultat_non_staff_renvoie_vide(alice):
    assert admin_url_for_resultat(_context_non_staff(), ["n_root"]) == ""


def test_admin_url_for_resultat_sans_chemin_renvoie_vide(alice):
    assert admin_url_for_resultat(_context_staff(alice), []) == ""


def test_admin_url_for_resultat_draft_tree_id_invalide_renvoie_vide(alice):
    assert (
        admin_url_for_resultat(
            _context_staff(alice), ["n_root"], draft_tree_id="pas-un-entier"
        )
        == ""
    )


def test_admin_url_for_resultat_tree_pk_invalide_renvoie_vide(alice):
    assert (
        admin_url_for_resultat(_context_staff(alice), ["n_root"], tree_pk="xxx") == ""
    )


def test_admin_url_for_resultat_sans_arbre_et_sans_pan_actif_renvoie_vide(alice):
    assert admin_url_for_resultat(_context_staff(alice), ["n_root"]) == ""


def test_admin_url_for_resultat_fallback_pan_actif(alice, actif):
    url = admin_url_for_resultat(_context_staff(alice), ["n_root", "r_hors_zv"])
    assert url.startswith("/admin/nitrates/arbre-decision/?")
    assert f"tree_id={actif.pk}" in url
    assert "mode=lecture" in url
    assert "expand=n_root" in url
