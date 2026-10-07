"""Tests de couverture pour views_admin_yaml.py (vues non-htmx de l'editeur :
liste/viewer, editer-actif, renommer, cloner)."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from envergo.nitrates.models import DecisionTree

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]


@pytest.fixture(autouse=True)
def _purge():
    DecisionTree.objects.all().delete()


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user(
        email="alice@test.local", name="Alice", password="x", is_staff=True
    )


@pytest.fixture
def bob(db):
    return get_user_model().objects.create_user(
        email="bob@test.local", name="Bob", password="x", is_staff=True
    )


@pytest.fixture
def observator(db):
    from django.contrib.auth.models import Group

    from envergo.nitrates.permissions import EXTERNAL_OBSERVATOR_GROUP

    user = get_user_model().objects.create_user(
        email="obs@test.local", name="Obs", password="x", is_staff=True
    )
    group, _ = Group.objects.get_or_create(name=EXTERNAL_OBSERVATOR_GROUP)
    user.groups.add(group)
    return user


def _arbre_minimal():
    return {
        "arbre": {
            "noeud": {
                "type_noeud": "catalogue",
                "id": "n_root",
                "champ": "en_zone_vulnerable",
                "source": "sig",
                "reference": "zone_vulnerable_nitrates",
                "branches": [
                    {
                        "valeur": False,
                        "regle": {"id": "r_hors_zv", "type": "non_applicable"},
                    },
                ],
            }
        }
    }


@pytest.fixture
def actif():
    return DecisionTree.objects.create(
        name="actif",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_NATIONAL,
        contenu=_arbre_minimal(),
        contenu_yaml_brut="x: 1\n",
    )


# ─── YamlTreeView : pas d'arbre disponible ──────────────────────────────────


def test_yaml_tree_view_sans_aucun_arbre_en_base(client, alice):
    client.force_login(alice)
    resp = client.get(reverse("nitrates_admin_yaml_tree"))
    assert resp.status_code == 200
    assert resp.context["no_tree"] is True


def test_yaml_tree_view_tree_id_invalide_retombe_sur_no_tree(client, alice):
    client.force_login(alice)
    resp = client.get(reverse("nitrates_admin_yaml_tree") + "?tree_id=pas-un-entier")
    assert resp.status_code == 200
    assert resp.context["no_tree"] is True


def test_yaml_tree_view_mode_invalide_retombe_en_lecture(client, alice, actif):
    client.force_login(alice)
    resp = client.get(
        reverse("nitrates_admin_yaml_tree") + f"?tree_id={actif.pk}&mode=pas_un_mode"
    )
    assert resp.status_code == 200
    assert resp.context["mode"] == "lecture"


def test_yaml_tree_view_lock_bloque_retombe_en_lecture(client, alice, bob, actif):
    """Un draft verrouillé par bob : alice qui tente le mode edition retombe
    en lecture avec lock_blocked_by renseigné."""
    draft = DecisionTree.objects.create(
        name="d",
        status=DecisionTree.STATUS_DRAFT,
        contenu=_arbre_minimal(),
        contenu_yaml_brut="x: 1\n",
    )
    draft.acquire_lock(bob)
    client.force_login(alice)
    resp = client.get(
        reverse("nitrates_admin_yaml_tree") + f"?tree_id={draft.pk}&mode=edition"
    )
    assert resp.status_code == 200
    assert resp.context["mode"] == "lecture"
    assert resp.context["lock_blocked_by"] == bob


def test_yaml_tree_view_vue_brut_genere_le_html_colore(client, alice, actif):
    client.force_login(alice)
    resp = client.get(
        reverse("nitrates_admin_yaml_tree") + f"?tree_id={actif.pk}&vue=brut"
    )
    assert resp.status_code == 200
    assert "yaml-raw" in resp.context["raw_html"]


# ─── EditActiveView ─────────────────────────────────────────────────────────


def test_edit_active_refuse_a_un_observateur_externe(client, observator, actif):
    client.force_login(observator)
    resp = client.get(reverse("nitrates_admin_yaml_edit_active"))
    assert resp.status_code == 403


def test_edit_active_sans_arbre_actif_redirige_vers_la_liste(client, alice):
    client.force_login(alice)
    resp = client.get(reverse("nitrates_admin_yaml_edit_active"))
    assert resp.status_code == 302
    assert resp.url == reverse("nitrates_admin_yaml_tree")


def test_edit_active_cree_un_draft_et_redirige_en_edition(client, alice, actif):
    client.force_login(alice)
    resp = client.get(reverse("nitrates_admin_yaml_edit_active"))
    assert resp.status_code == 302
    assert "mode=edition" in resp.url
    draft = DecisionTree.objects.get(parent=actif, created_by=alice)
    assert draft.status == DecisionTree.STATUS_DRAFT


# ─── RenameTreeView ─────────────────────────────────────────────────────────


def test_rename_nom_vide_ne_modifie_rien(client, alice, actif):
    client.force_login(alice)
    nom_avant = actif.name
    client.post(
        reverse("nitrates_admin_yaml_rename_tree", kwargs={"pk": actif.pk}),
        {"name": "   "},
    )
    actif.refresh_from_db()
    assert actif.name == nom_avant


def test_rename_en_collision_ajoute_un_suffixe_numerique(client, alice, actif):
    """Un autre tree s'appelle deja 'nouveau nom' ET 'nouveau nom (2)' :
    le suffixe doit grimper à (3)."""
    DecisionTree.objects.create(
        name="nouveau nom",
        status=DecisionTree.STATUS_DRAFT,
        contenu=_arbre_minimal(),
        contenu_yaml_brut="x: 1\n",
    )
    DecisionTree.objects.create(
        name="nouveau nom (2)",
        status=DecisionTree.STATUS_DRAFT,
        contenu=_arbre_minimal(),
        contenu_yaml_brut="x: 1\n",
    )
    client.force_login(alice)
    client.post(
        reverse("nitrates_admin_yaml_rename_tree", kwargs={"pk": actif.pk}),
        {"name": "nouveau nom"},
    )
    actif.refresh_from_db()
    assert actif.name == "nouveau nom (3)"


# ─── CloneConfirmView ───────────────────────────────────────────────────────


def test_clone_confirm_affiche_le_tree_source(client, alice, actif):
    client.force_login(alice)
    resp = client.get(
        reverse("nitrates_admin_yaml_clone_confirm", kwargs={"pk": actif.pk})
    )
    assert resp.status_code == 200
    assert resp.context["source"].pk == actif.pk


def test_clone_confirm_404_si_source_introuvable(client, alice):
    client.force_login(alice)
    resp = client.get(
        reverse("nitrates_admin_yaml_clone_confirm", kwargs={"pk": 999999})
    )
    assert resp.status_code == 404


# ─── CreateDraftView ────────────────────────────────────────────────────────


def test_create_draft_sans_from_ni_pan_actif_redirige_vers_la_liste(client, alice):
    client.force_login(alice)
    resp = client.post(reverse("nitrates_admin_yaml_create_draft"))
    assert resp.status_code == 302
    assert resp.url == reverse("nitrates_admin_yaml_tree")


def test_create_draft_avec_from_clone_la_source_demandee(client, alice, actif):
    client.force_login(alice)
    resp = client.post(
        reverse("nitrates_admin_yaml_create_draft") + f"?from={actif.pk}"
    )
    assert resp.status_code == 302
    nouveau = DecisionTree.objects.exclude(pk=actif.pk).get()
    assert nouveau.parent_id == actif.pk
    assert nouveau.status == DecisionTree.STATUS_DRAFT
