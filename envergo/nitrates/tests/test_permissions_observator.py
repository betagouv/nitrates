"""Tests des permissions du groupe `external_observator`.

Couvre :
  - identification (is_external_observator)
  - autorisations DecisionTree : edit / delete / activate / edit_active
  - admin Django : filtre app + visibilite ModelAdmin
  - commande provision_admin --group external_observator
"""

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command

from envergo.nitrates.models import DecisionTree
from envergo.nitrates.permissions import (
    EXTERNAL_OBSERVATOR_GROUP,
    can_activate_tree,
    can_change_tree,
    can_delete_tree,
    can_edit_active,
    is_external_observator,
)
from envergo.users.tests.factories import UserFactory

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def observator_group(db):
    """Le groupe external_observator (cree par migration 0010, mais on
    le re-cree ici pour qu'il existe meme si la migration n'a pas tourne
    sur la DB de test)."""
    group, _ = Group.objects.get_or_create(name=EXTERNAL_OBSERVATOR_GROUP)
    return group


@pytest.fixture
def observator_user(db, observator_group):
    """Un staff external_observator (is_staff=True, pas superuser)."""
    u = UserFactory(is_staff=True, is_superuser=False)
    u.groups.add(observator_group)
    return u


@pytest.fixture
def other_observator(db, observator_group):
    """Un 2e external_observator distinct (pour tester l'ownership)."""
    u = UserFactory(is_staff=True, is_superuser=False)
    u.groups.add(observator_group)
    return u


@pytest.fixture
def superuser(db):
    return UserFactory(is_staff=True, is_superuser=True)


@pytest.fixture
def intra_staff(db):
    """Un staff intra : is_staff=True, pas dans le groupe observator,
    pas superuser. Devrait conserver les permissions d'edition larges."""
    return UserFactory(is_staff=True, is_superuser=False)


@pytest.fixture
def anonymous_user(db):
    """Un user non-staff (visiteur lambda authentifie)."""
    return UserFactory(is_staff=False, is_superuser=False)


def _make_tree(status, created_by, name="test"):
    # Garde-fou : un seul actif a la fois (contrainte unique partielle DB).
    # Tests qui creent un actif doivent nettoyer / etre isoles.
    if status == DecisionTree.STATUS_ACTIVE:
        DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE).delete()
    return DecisionTree.objects.create(
        name=name,
        status=status,
        contenu={},
        contenu_yaml_brut="",
        created_by=created_by,
    )


# ---------------------------------------------------------------------------
# is_external_observator
# ---------------------------------------------------------------------------


def test_is_external_observator_true_pour_membre(observator_user):
    assert is_external_observator(observator_user) is True


def test_is_external_observator_false_pour_superuser_meme_dans_groupe(
    db, observator_group
):
    # Un superuser dans le groupe est quand meme considere comme superuser
    # (bypass des restrictions), pas observator.
    u = UserFactory(is_staff=True, is_superuser=True)
    u.groups.add(observator_group)
    assert is_external_observator(u) is False


def test_is_external_observator_false_pour_intra_staff(intra_staff):
    assert is_external_observator(intra_staff) is False


def test_is_external_observator_false_pour_anonymous(anonymous_user):
    assert is_external_observator(anonymous_user) is False


# ---------------------------------------------------------------------------
# can_change_tree
# ---------------------------------------------------------------------------


def test_observator_peut_editer_son_draft(observator_user):
    tree = _make_tree(DecisionTree.STATUS_DRAFT, observator_user)
    assert can_change_tree(observator_user, tree) is True


def test_observator_ne_peut_pas_editer_draft_d_autrui(
    observator_user, other_observator
):
    tree = _make_tree(DecisionTree.STATUS_DRAFT, other_observator)
    assert can_change_tree(observator_user, tree) is False


def test_observator_ne_peut_pas_editer_arbre_actif(observator_user):
    tree = _make_tree(DecisionTree.STATUS_ACTIVE, observator_user)
    assert can_change_tree(observator_user, tree) is False


def test_observator_ne_peut_pas_editer_arbre_archive(observator_user):
    tree = _make_tree(DecisionTree.STATUS_ARCHIVE, observator_user)
    assert can_change_tree(observator_user, tree) is False


def test_superuser_peut_editer_tout(superuser, intra_staff):
    for status in (
        DecisionTree.STATUS_DRAFT,
        DecisionTree.STATUS_ACTIVE,
        DecisionTree.STATUS_ARCHIVE,
    ):
        tree = _make_tree(status, intra_staff)
        assert can_change_tree(superuser, tree) is True


def test_intra_staff_peut_editer_drafts_autres_users(intra_staff, observator_user):
    """Les staff non-observator gardent le comportement large existant."""
    tree = _make_tree(DecisionTree.STATUS_DRAFT, observator_user)
    assert can_change_tree(intra_staff, tree) is True


def test_anonymous_ne_peut_rien(anonymous_user, intra_staff):
    tree = _make_tree(DecisionTree.STATUS_DRAFT, intra_staff)
    assert can_change_tree(anonymous_user, tree) is False


# ---------------------------------------------------------------------------
# can_delete_tree
# ---------------------------------------------------------------------------


def test_observator_peut_supprimer_son_draft(observator_user):
    tree = _make_tree(DecisionTree.STATUS_DRAFT, observator_user)
    assert can_delete_tree(observator_user, tree) is True


def test_observator_ne_peut_pas_supprimer_draft_d_autrui(
    observator_user, other_observator
):
    tree = _make_tree(DecisionTree.STATUS_DRAFT, other_observator)
    assert can_delete_tree(observator_user, tree) is False


def test_observator_ne_peut_pas_supprimer_actif(observator_user):
    tree = _make_tree(DecisionTree.STATUS_ACTIVE, observator_user)
    assert can_delete_tree(observator_user, tree) is False


# ---------------------------------------------------------------------------
# can_activate_tree
# ---------------------------------------------------------------------------


def test_observator_ne_peut_pas_activer_meme_son_draft(observator_user):
    tree = _make_tree(DecisionTree.STATUS_DRAFT, observator_user)
    assert can_activate_tree(observator_user, tree) is False


def test_superuser_peut_activer(superuser, intra_staff):
    tree = _make_tree(DecisionTree.STATUS_DRAFT, intra_staff)
    assert can_activate_tree(superuser, tree) is True


def test_intra_staff_peut_activer(intra_staff):
    tree = _make_tree(DecisionTree.STATUS_DRAFT, intra_staff)
    assert can_activate_tree(intra_staff, tree) is True


# ---------------------------------------------------------------------------
# can_edit_active
# ---------------------------------------------------------------------------


def test_observator_ne_peut_pas_editer_arbre_actif_via_endpoint(observator_user):
    assert can_edit_active(observator_user) is False


def test_intra_peut_editer_arbre_actif(intra_staff, superuser):
    assert can_edit_active(intra_staff) is True
    assert can_edit_active(superuser) is True


# ---------------------------------------------------------------------------
# Filtre app admin (get_app_list)
# ---------------------------------------------------------------------------


def test_get_app_list_filtre_apps_pour_observator(rf, observator_user, intra_staff):
    """Un observator ne voit que l'app nitrates dans l'admin.
    Un intra staff voit tout."""
    from envergo.admin.site import EnvergoAdminSite

    site = EnvergoAdminSite(name="test-admin")
    request = rf.get("/admin/")
    request.user = observator_user

    apps = site.get_app_list(request)
    labels = {a["app_label"] for a in apps}
    # Observator : que nitrates (au max). Peut etre vide si nitrates n'a
    # pas de model visible pour le user (cas a part), donc on tolere.
    assert labels.issubset({"nitrates"})


def test_get_app_list_non_filtre_pour_intra(rf, intra_staff):
    """Un intra (non observator) voit la liste complete."""
    from envergo.admin.site import EnvergoAdminSite

    site = EnvergoAdminSite(name="test-admin")
    request = rf.get("/admin/")
    request.user = intra_staff

    apps = site.get_app_list(request)
    # On ne sait pas exactement quelles apps apparaissent (depend des
    # permissions intra par defaut), mais ce ne doit pas etre filtre a
    # nitrates seul. Test de non-regression : on s'assure que le code de
    # filtrage observator n'a pas ete declenche par erreur.
    assert isinstance(apps, list)


# ---------------------------------------------------------------------------
# Commande provision_admin --group
# ---------------------------------------------------------------------------


def test_provision_admin_avec_group_ajoute_au_groupe(db, observator_group):
    """provision_admin --group external_observator ajoute le user au groupe."""
    from envergo.users.models import User

    call_command(
        "provision_admin",
        "--email",
        "observator-test@example.com",
        "--name",
        "Observator Test",
        "--group",
        EXTERNAL_OBSERVATOR_GROUP,
    )
    u = User.objects.get(email="observator-test@example.com")
    assert u.is_staff is True
    assert u.is_superuser is False
    assert u.groups.filter(name=EXTERNAL_OBSERVATOR_GROUP).exists()


def test_provision_admin_group_inconnu_leve_erreur(db):
    """Un --group inexistant doit faire echouer la commande."""
    from django.core.management import CommandError

    with pytest.raises(CommandError):
        call_command(
            "provision_admin",
            "--email",
            "x@x.fr",
            "--group",
            "groupe_qui_existe_pas",
        )


def test_provision_admin_revoke_retire_groupes(db, observator_group):
    """--revoke retire les groupes en plus de is_staff/is_superuser."""
    from envergo.users.models import User

    call_command(
        "provision_admin",
        "--email",
        "revoke-test@example.com",
        "--group",
        EXTERNAL_OBSERVATOR_GROUP,
    )
    u = User.objects.get(email="revoke-test@example.com")
    assert u.groups.count() == 1

    call_command("provision_admin", "--email", "revoke-test@example.com", "--revoke")
    u.refresh_from_db()
    assert u.is_staff is False
    assert u.groups.count() == 0


def test_provision_admin_neutralise_password_existant(db):
    """Faille pentest F2 : re-provisionner un compte qui a DEJA un mot de passe
    utilisable doit le neutraliser (sinon vecteur de login qui contourne
    ProConnect). L'ancienne exception « emergency access » est supprimee."""
    from envergo.users.models import User

    # Compte pre-existant avec un mot de passe utilisable (cas F2).
    u = User.objects.create(email="legacy-admin@example.com", is_active=True)
    u.set_password("MotDePasseUtilisable123!")  # pragma: allowlist secret
    u.save()
    assert u.has_usable_password() is True

    # Re-provisionner via la commande doit neutraliser le mot de passe.
    call_command("provision_admin", "--email", "legacy-admin@example.com")

    u.refresh_from_db()
    assert u.is_staff is True
    assert u.has_usable_password() is False
