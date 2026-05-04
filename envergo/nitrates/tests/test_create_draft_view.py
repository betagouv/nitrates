"""Tests de CreateDraftView : clonage d'un tree en draft."""

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
    return get_user_model().objects.create_user(
        email="staff@test.local", name="Staff", password="x", is_staff=True
    )


@pytest.fixture
def regular_user(db):
    return get_user_model().objects.create_user(
        email="user@test.local", name="User", password="x"
    )


def _make_tree(**overrides) -> DecisionTree:
    defaults = {
        "name": "national",
        "status": DecisionTree.STATUS_ACTIVE,
        "contenu": {"arbre": {"noeud": {"id": "n_root"}}},
        "contenu_yaml_brut": "arbre:\n  noeud:\n    id: n_root\n",
    }
    defaults.update(overrides)
    return DecisionTree.objects.create(**defaults)


@pytest.fixture
def url():
    return reverse("nitrates_admin_yaml_create_draft")


def test_anonymous_redirected(client, url):
    resp = client.post(url)
    assert resp.status_code in (301, 302)


def test_non_staff_refused(client, url, regular_user):
    client.force_login(regular_user)
    resp = client.post(url)
    assert resp.status_code in (301, 302)


def test_clone_active_par_defaut(client, url, staff_user):
    active = _make_tree(name="active_v1")
    client.force_login(staff_user)
    resp = client.post(url)
    assert resp.status_code == 302
    drafts = DecisionTree.objects.filter(status=DecisionTree.STATUS_DRAFT)
    assert drafts.count() == 1
    draft = drafts.get()
    assert draft.name == "active_v1 (copy)"
    assert draft.parent_id == active.pk
    assert draft.contenu == active.contenu
    assert draft.contenu_yaml_brut == active.contenu_yaml_brut
    assert draft.created_by_id == staff_user.pk
    assert resp["Location"].endswith(f"?tree_id={draft.pk}")


def test_clone_from_param_quel_que_soit_le_statut(client, url, staff_user):
    archive = _make_tree(name="old_v0", status=DecisionTree.STATUS_ARCHIVE)
    client.force_login(staff_user)
    resp = client.post(url + f"?from={archive.pk}")
    assert resp.status_code == 302
    draft = DecisionTree.objects.get(status=DecisionTree.STATUS_DRAFT)
    assert draft.parent_id == archive.pk
    assert draft.name == "old_v0 (copy)"


def test_clone_meme_source_2_fois_genere_suffixe(client, url, staff_user):
    active = _make_tree(name="x")
    client.force_login(staff_user)
    client.post(url)
    client.post(url)
    names = set(
        DecisionTree.objects.filter(status=DecisionTree.STATUS_DRAFT).values_list(
            "name", flat=True
        )
    )
    assert names == {"x (copy)", "x (copy 2)"}
    # source intacte
    active.refresh_from_db()
    assert active.status == DecisionTree.STATUS_ACTIVE


def test_clone_modifications_independantes(client, url, staff_user):
    """Modifier le contenu du draft ne touche pas la source."""
    active = _make_tree(name="src")
    client.force_login(staff_user)
    client.post(url)
    draft = DecisionTree.objects.get(status=DecisionTree.STATUS_DRAFT)
    draft.contenu["arbre"]["noeud"]["id"] = "n_modified"
    draft.save()
    active.refresh_from_db()
    assert active.contenu["arbre"]["noeud"]["id"] == "n_root"


def test_clone_sans_actif_redirige_proprement(client, url, staff_user):
    """Sans aucun tree en DB et sans param `from`, on redirige vers le viewer
    (qui affichera "aucun arbre actif")."""
    client.force_login(staff_user)
    resp = client.post(url)
    assert resp.status_code == 302
    assert DecisionTree.objects.count() == 0


def test_rename_tree_par_staff(client, staff_user):
    """RenameTreeView change le name d'un draft et redirige vers le viewer."""
    tree = _make_tree(name="d1", status=DecisionTree.STATUS_DRAFT)
    client.force_login(staff_user)
    rename_url = reverse("nitrates_admin_yaml_rename_tree", kwargs={"pk": tree.pk})
    resp = client.post(rename_url, {"name": "Nouveau nom"})
    assert resp.status_code == 302
    tree.refresh_from_db()
    assert tree.name == "Nouveau nom"


def test_rename_avec_collision_ajoute_suffixe(client, staff_user):
    """Si le nouveau nom existe deja, on suffixe pour eviter la collision."""
    _make_tree(name="existing", status=DecisionTree.STATUS_ACTIVE)
    draft = _make_tree(name="d2", status=DecisionTree.STATUS_DRAFT)
    client.force_login(staff_user)
    rename_url = reverse("nitrates_admin_yaml_rename_tree", kwargs={"pk": draft.pk})
    resp = client.post(rename_url, {"name": "existing"})
    assert resp.status_code == 302
    draft.refresh_from_db()
    assert draft.name != "existing"
    assert "existing" in draft.name


def test_rename_nom_vide_ignore(client, staff_user):
    """Un nom vide ne change rien."""
    tree = _make_tree(name="garde-moi", status=DecisionTree.STATUS_DRAFT)
    client.force_login(staff_user)
    rename_url = reverse("nitrates_admin_yaml_rename_tree", kwargs={"pk": tree.pk})
    client.post(rename_url, {"name": "   "})
    tree.refresh_from_db()
    assert tree.name == "garde-moi"


def test_clone_from_inexistant_ne_cree_rien(client, url, staff_user):
    """Un id `from` inexistant lance Http404 (rendu via la chaine standard
    Django, pas testable ici sans staticfiles compresses). On verifie au
    moins qu'aucun draft n'est cree."""
    client.force_login(staff_user)
    try:
        client.post(url + "?from=99999")
    except Exception:
        pass  # 404 attendu, le template d'erreur peut crasher en test
    assert DecisionTree.objects.filter(status=DecisionTree.STATUS_DRAFT).count() == 0
