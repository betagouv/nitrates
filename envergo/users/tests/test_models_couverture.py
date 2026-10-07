"""Complément de couverture de envergo/users/models.py.

test_models.py couvre déjà is_involved_in_guh et get_unique_hash pour le cas
nominal. Ce fichier couvre les erreurs de configuration et le manager
(create_user/create_superuser)."""

import pytest
from django.core.exceptions import ImproperlyConfigured

from envergo.users.models import User

pytestmark = pytest.mark.django_db


def test_get_unique_hash_sans_salt_leve_erreur(settings):
    settings.HASH_SALT_KEY = ""
    user = User.objects.create_user(email="salt-test@example.com", name="Salt")
    with pytest.raises(ImproperlyConfigured):
        user.get_unique_hash()


def test_create_user_sans_email_leve_erreur():
    with pytest.raises(ValueError):
        User.objects.create_user(email="", name="Sans email")


def test_create_user_defauts_non_staff_non_superuser():
    user = User.objects.create_user(email="simple@example.com", name="Simple")
    assert user.is_staff is False
    assert user.is_superuser is False
    assert user.check_password(None) is False


def test_create_superuser_ok():
    user = User.objects.create_superuser(email="super@example.com", name="Super")
    assert user.is_staff is True
    assert user.is_superuser is True


def test_create_superuser_refuse_is_staff_false():
    with pytest.raises(ValueError):
        User.objects.create_superuser(
            email="passtaff@example.com", name="X", is_staff=False
        )


def test_create_superuser_refuse_is_superuser_false():
    with pytest.raises(ValueError):
        User.objects.create_superuser(
            email="passuper@example.com", name="X", is_superuser=False
        )


def test_str_renvoie_le_nom():
    user = User.objects.create_user(email="nom@example.com", name="Jean Dupont")
    assert str(user) == "Jean Dupont"
