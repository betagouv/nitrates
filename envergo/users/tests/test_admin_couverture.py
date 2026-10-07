"""Complément de couverture de envergo/users/admin.py (UserAdmin).

test_admin.py couvre déjà save_related (envoi d'email de droits GUH). Ce
fichier couvre les pages changelist/add du UserAdmin, les colonnes
d'affichage, et le formulaire UserForm (projets suivis + queryset
departments allégé)."""

import pytest
from django.contrib.admin.sites import AdminSite
from django.urls import reverse

from envergo.petitions.tests.factories import PetitionProjectFactory
from envergo.users.admin import UserAdmin, UserForm
from envergo.users.models import User
from envergo.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_changelist_user_superuser_200(client, admin_user):
    client.force_login(admin_user)
    url = reverse("admin:users_user_changelist")
    resp = client.get(url)
    assert resp.status_code == 200
    assert admin_user.email in resp.content.decode()


def test_add_user_page_200(client, admin_user):
    client.force_login(admin_user)
    url = reverse("admin:users_user_add")
    resp = client.get(url)
    assert resp.status_code == 200
    assert 'name="email"' in resp.content.decode()


def test_display_columns():
    admin_instance = UserAdmin(User, AdminSite())
    u = User(
        is_superuser=True,
        is_staff=True,
        access_amenagement=True,
        access_haie=False,
        is_instructor=True,
    )
    assert admin_instance.superuser_col(u) is True
    assert admin_instance.is_staff_col(u) is True
    assert admin_instance.access_amenagement_col(u) is True
    assert admin_instance.access_haie_col(u) is False
    assert admin_instance.is_instructor_col(u) is True


def test_userform_init_charge_les_projets_suivis(db):
    from django.forms import modelform_factory

    user = UserFactory(is_envergo_user=True)
    projet = PetitionProjectFactory()
    user.followed_petition_projects.add(projet)
    Form = modelform_factory(User, form=UserForm, fields=["email", "name"])
    form = Form(instance=user)
    assert projet in form.fields["followed_petition_projects"].initial


def test_userform_save_m2m_projets_suivis(db):
    from django.forms import modelform_factory

    user = UserFactory(is_envergo_user=True)
    projet = PetitionProjectFactory()
    Form = modelform_factory(User, form=UserForm, fields=["email", "name"])
    form = Form(
        data={
            "email": user.email,
            "name": user.name,
            "followed_petition_projects": [projet.pk],
        },
        instance=user,
    )
    assert form.is_valid(), form.errors
    saved = form.save()
    assert projet in saved.followed_petition_projects.all()


def test_formfield_for_manytomany_departments_defer_geometry(db):
    """Le queryset proposé pour `departments` ne charge pas la géométrie
    (optimisation de l'admin, cf. UserAdmin.formfield_for_manytomany)."""
    admin_instance = UserAdmin(User, AdminSite())
    field = User._meta.get_field("departments")
    formfield = admin_instance.formfield_for_manytomany(field)
    qs = formfield.queryset
    assert "geometry" in qs.query.deferred_loading[0]
