"""L'admin n'expose que le périmètre nitrates (apps Envergo dormantes
retirées) et un admin des comptes propre à nitrates."""

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from envergo.nitrates.admin_perimetre import (
    PERIMETRE,
    NitratesUserAdmin,
    hors_perimetre,
)

pytestmark = pytest.mark.django_db

User = get_user_model()
MDP = "Un-mot-de-passe-solide-42"  # pragma: allowlist secret


@pytest.fixture
def admin_client_su(client):
    su = User.objects.create_user(
        email="su@test.local",
        name="Su",
        password="x",
        is_staff=True,
        is_superuser=True,
    )
    client.force_login(su)
    return client


def test_registre_limite_au_perimetre():
    apps = {m._meta.app_label for m in admin.site._registry}
    assert apps <= set(PERIMETRE)
    for app in ("petitions", "evaluations", "hedges", "pages", "urlmappings"):
        assert app not in apps
    noms = {m.__name__ for m in admin.site._registry}
    assert {"Regulation", "Criterion", "Map", "Zone", "CSPReport"} <= noms
    assert not {"ConfigHaie", "Line", "Event", "Site"} & noms


def test_hors_perimetre():
    from envergo.geodata.models import Line, Map
    from envergo.nitrates.models import DecisionTree
    from envergo.petitions.models import PetitionProject

    assert hors_perimetre(PetitionProject)
    assert hors_perimetre(Line)
    assert not hors_perimetre(Map)
    assert not hors_perimetre(DecisionTree)


def test_comptes_geres_par_l_admin_nitrates():
    assert isinstance(admin.site._registry[User], NitratesUserAdmin)


def test_index_admin_sans_apps_envergo(admin_client_su):
    r = admin_client_su.get("/admin/")
    assert r.status_code == 200
    labels = {a["app_label"] for a in r.context["app_list"]}
    assert "nitrates" in labels
    assert not labels & {"petitions", "evaluations", "hedges", "confs", "sites"}


def test_fiche_utilisateur_sans_champs_envergo(admin_client_su):
    u = User.objects.create_user(email="agent@agriculture.gouv.fr", name="Agent")
    r = admin_client_su.get(f"/admin/users/user/{u.pk}/change/")
    assert r.status_code == 200
    form = r.context["adminform"].form
    assert {"email", "name", "groups", "proconnect_sub"} & set(form.fields) == {
        "email",
        "name",
        "groups",
    }
    for envergo in ("access_haie", "is_instructor", "departments"):
        assert envergo not in form.fields
    assert b"followed_petition_projects" not in r.content


def test_creation_utilisateur(admin_client_su):
    groupe = Group.objects.create(name="observateurs")
    r = admin_client_su.post(
        "/admin/users/user/add/",
        {
            "email": "nouvel.agent@agriculture.gouv.fr",
            "name": "Nouvel Agent",
            "password1": MDP,
            "password2": MDP,
        },
    )
    assert r.status_code == 302, r.context["adminform"].form.errors
    u = User.objects.get(email="nouvel.agent@agriculture.gouv.fr")
    assert u.name == "Nouvel Agent"
    assert groupe.user_set.count() == 0


def test_creation_refuse_un_domaine_idn(admin_client_su):
    r = admin_client_su.post(
        "/admin/users/user/add/",
        {
            "email": "agent@agrículture.fr",
            "name": "X",
            "password1": MDP,
            "password2": MDP,
        },
    )
    assert r.status_code == 200
    assert "email" in r.context["adminform"].form.errors


def test_liste_utilisateurs_et_recherche(admin_client_su):
    User.objects.create_user(email="cherche@test.local", name="Trouvable")
    r = admin_client_su.get("/admin/users/user/", {"q": "Trouvable"})
    assert r.status_code == 200
    assert r.context["cl"].result_count == 1
