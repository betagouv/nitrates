"""Lien retour depuis le panneau debug 'Chemin parcouru' du simulateur
vers l'editeur YAML, cible sur le dernier noeud du chemin."""

from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser, Group

from envergo.nitrates.models import DecisionTree
from envergo.nitrates.permissions import EXTERNAL_OBSERVATOR_GROUP
from envergo.nitrates.templatetags.yaml_admin_extras import admin_url_for_resultat
from envergo.users.tests.factories import UserFactory


def _ctx(user):
    """Construit un context minimal compatible avec un simple_tag
    takes_context=True (dict avec une cle 'request')."""
    request = SimpleNamespace(user=user)
    return {"request": request}


def _make_tree(status, created_by=None, name="test"):
    # Garde-fou : un seul actif a la fois (contrainte unique partielle DB).
    if status == DecisionTree.STATUS_ACTIVE:
        DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE).delete()
    return DecisionTree.objects.create(
        name=name,
        status=status,
        contenu={"arbre": {"noeud": {"id": "n_zvn"}}},
        contenu_yaml_brut="",
        created_by=created_by,
    )


def test_user_non_authenticated_returns_empty():
    """Anonyme : pas de lien."""
    url = admin_url_for_resultat(
        _ctx(AnonymousUser()), ["n_zvn", "q_culture", "r_truc"]
    )
    assert url == ""


@pytest.mark.django_db
def test_user_non_staff_returns_empty():
    """User authentifie mais non-staff : pas de lien."""
    user = UserFactory(is_staff=False)
    assert admin_url_for_resultat(_ctx(user), ["n_zvn", "r_x"]) == ""


@pytest.mark.django_db
def test_chemin_vide_returns_empty():
    user = UserFactory(is_staff=True, is_superuser=True)
    assert admin_url_for_resultat(_ctx(user), []) == ""
    assert admin_url_for_resultat(_ctx(user), None) == ""


@pytest.mark.django_db
def test_staff_no_draft_id_uses_active_tree():
    """Sans draft_tree_id : on cible l'arbre actif courant."""
    user = UserFactory(is_staff=True, is_superuser=True)
    tree = _make_tree(DecisionTree.STATUS_ACTIVE, created_by=user, name="actif")
    url = admin_url_for_resultat(_ctx(user), ["n_zvn", "q_culture", "r_truc"])
    assert url.startswith("/admin/nitrates/arbre-decision/?")
    assert f"tree_id={tree.pk}" in url
    assert "mode=lecture" in url
    assert "expand=n_zvn" in url
    assert "expand=n_zvn%2Fq_culture" in url
    assert "expand=n_zvn%2Fq_culture%2Fr_truc" in url
    # Fragment ancre sur le dernier noeud (slugify remplace / par -)
    assert "#node-" in url


@pytest.mark.django_db
def test_staff_with_draft_id_targets_draft():
    """Avec draft_tree_id : on cible ce tree precis (verifie via can_preview_tree)."""
    user = UserFactory(is_staff=True, is_superuser=True)
    draft = _make_tree(DecisionTree.STATUS_DRAFT, created_by=user, name="draft")
    url = admin_url_for_resultat(
        _ctx(user), ["n_zvn", "r_x"], draft_tree_id=str(draft.pk)
    )
    assert f"tree_id={draft.pk}" in url


@pytest.mark.django_db
def test_staff_with_invalid_draft_id_returns_empty():
    """draft_tree_id qui ne resout aucun tree -> pas de lien (silencieux)."""
    user = UserFactory(is_staff=True, is_superuser=True)
    url = admin_url_for_resultat(_ctx(user), ["n_zvn"], draft_tree_id="999999")
    assert url == ""


@pytest.mark.django_db
def test_external_observator_blocked_on_other_user_draft():
    """external_observator ne suit pas le lien retour sur un draft d'autrui."""
    owner = UserFactory(is_staff=True, is_superuser=False)
    other = UserFactory(is_staff=True, is_superuser=False)
    grp, _ = Group.objects.get_or_create(name=EXTERNAL_OBSERVATOR_GROUP)
    other.groups.add(grp)

    draft = _make_tree(DecisionTree.STATUS_DRAFT, created_by=owner, name="not-mine")
    url = admin_url_for_resultat(_ctx(other), ["n_zvn"], draft_tree_id=str(draft.pk))
    assert url == ""


@pytest.mark.django_db
def test_external_observator_ok_on_own_draft():
    """external_observator OK pour suivre le lien retour sur SON draft."""
    user = UserFactory(is_staff=True, is_superuser=False)
    grp, _ = Group.objects.get_or_create(name=EXTERNAL_OBSERVATOR_GROUP)
    user.groups.add(grp)
    draft = _make_tree(DecisionTree.STATUS_DRAFT, created_by=user, name="mine")
    url = admin_url_for_resultat(_ctx(user), ["n_zvn"], draft_tree_id=str(draft.pk))
    assert f"tree_id={draft.pk}" in url


@pytest.mark.django_db
def test_no_active_tree_in_db_returns_empty():
    """Pas d'arbre actif en base + pas de draft_tree_id -> lien vide."""
    DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE).delete()
    user = UserFactory(is_staff=True, is_superuser=True)
    url = admin_url_for_resultat(_ctx(user), ["n_zvn"])
    assert url == ""


# ─── Mode lecture vs edition selon le verrou ────────────────────────────


@pytest.mark.django_db
def test_arbre_actif_toujours_mode_lecture():
    """Lien retour sur l'arbre actif : toujours mode=lecture (l'edition
    passe par un draft, on n'ouvre pas l'actif en edition)."""
    user = UserFactory(is_staff=True, is_superuser=True)
    _make_tree(DecisionTree.STATUS_ACTIVE, created_by=user, name="actif")
    url = admin_url_for_resultat(_ctx(user), ["n_zvn", "r_x"])
    assert "mode=lecture" in url
    assert "mode=edition" not in url


@pytest.mark.django_db
def test_draft_avec_lock_du_user_ouvre_en_edition():
    """Draft + user detient le lock valide -> mode=edition (cas nominal)."""
    from django.utils import timezone

    user = UserFactory(is_staff=True, is_superuser=True)
    draft = _make_tree(DecisionTree.STATUS_DRAFT, created_by=user, name="d")
    draft.locked_by = user
    draft.locked_at = timezone.now()
    draft.save()
    url = admin_url_for_resultat(
        _ctx(user), ["n_zvn", "r_x"], draft_tree_id=str(draft.pk)
    )
    assert "mode=edition" in url


@pytest.mark.django_db
def test_draft_avec_lock_autre_user_ouvre_en_lecture():
    """Draft + verrou tenu par un autre user -> mode=lecture (pas de vol
    de verrou involontaire)."""
    from django.utils import timezone

    me = UserFactory(is_staff=True, is_superuser=True)
    autre = UserFactory(is_staff=True, is_superuser=True)
    draft = _make_tree(DecisionTree.STATUS_DRAFT, created_by=me, name="d")
    draft.locked_by = autre
    draft.locked_at = timezone.now()
    draft.save()
    url = admin_url_for_resultat(
        _ctx(me), ["n_zvn", "r_x"], draft_tree_id=str(draft.pk)
    )
    assert "mode=lecture" in url
    assert "mode=edition" not in url


@pytest.mark.django_db
def test_draft_sans_lock_ouvre_en_lecture():
    """Draft + aucun verrou -> mode=lecture (l'user decide d'acquerir
    le lock depuis l'admin s'il veut editer)."""
    user = UserFactory(is_staff=True, is_superuser=True)
    draft = _make_tree(DecisionTree.STATUS_DRAFT, created_by=user, name="d")
    # Pas de lock pose
    assert draft.locked_by_id is None
    url = admin_url_for_resultat(
        _ctx(user), ["n_zvn", "r_x"], draft_tree_id=str(draft.pk)
    )
    assert "mode=lecture" in url
    assert "mode=edition" not in url


@pytest.mark.django_db
def test_draft_avec_lock_expire_du_user_ouvre_en_lecture():
    """Draft + verrou du user mais expire -> mode=lecture (le verrou
    n'est plus garanti, faut le re-acquerir explicitement)."""
    from datetime import timedelta

    from django.utils import timezone

    user = UserFactory(is_staff=True, is_superuser=True)
    draft = _make_tree(DecisionTree.STATUS_DRAFT, created_by=user, name="d")
    draft.locked_by = user
    # 2h en arriere -> au-dela du LOCK_TIMEOUT de 60 min
    draft.locked_at = timezone.now() - timedelta(hours=2)
    draft.save()
    url = admin_url_for_resultat(
        _ctx(user), ["n_zvn", "r_x"], draft_tree_id=str(draft.pk)
    )
    assert "mode=lecture" in url
    assert "mode=edition" not in url
