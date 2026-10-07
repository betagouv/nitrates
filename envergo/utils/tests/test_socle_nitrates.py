"""Helpers transverses utilisés par le simulateur nitrates : champ email sans
IDN (admin des utilisateurs), outils divers."""

from collections import OrderedDict

import pytest
from django.contrib.sites.models import Site
from django.core.exceptions import ValidationError

from envergo.utils import tools
from envergo.utils.fields import (
    MultipleFileField,
    NoIdnEmailField,
    get_human_readable_value,
)


def test_email_sans_idn():
    champ = NoIdnEmailField()
    assert champ.clean("agent@agriculture.gouv.fr") == "agent@agriculture.gouv.fr"
    with pytest.raises(ValidationError):
        champ.clean("agent@agrículture.fr")


def test_valeur_lisible_d_un_choix():
    choix = [("a", "Alpha"), ("b", "Bêta")]
    assert get_human_readable_value(choix, "b") == "Bêta"
    assert get_human_readable_value(choix, "z") is None


def test_multiple_file_field_accepte_une_liste():
    from django.core.files.uploadedfile import SimpleUploadedFile

    f1 = SimpleUploadedFile("a.txt", b"a")
    f2 = SimpleUploadedFile("b.txt", b"b")
    assert MultipleFileField().clean([f1, f2]) == [f1, f2]
    assert MultipleFileField().clean(f1) == f1


def test_get_site_literal(settings):
    settings.ENVERGO_HAIE_DOMAIN = "haie.test"
    assert tools.get_site_literal(Site(domain="haie.test")) == "haie"
    assert tools.get_site_literal(Site(domain="nitrates.test")) == "amenagement"


def test_get_base_url():
    assert (
        tools.get_base_url("nitrates.beta.gouv.fr") == "https://nitrates.beta.gouv.fr"
    )


def test_generate_key(settings):
    settings.URLMAPPING_KEY_LENGTH = 12
    cle = tools.generate_key()
    assert len(cle) == 12
    assert not set(cle) & set("l1iO0")


def test_insert_before():
    d = OrderedDict([("a", 1), ("c", 3)])
    assert list(tools.insert_before(d, "b", 2, "c").items()) == [
        ("a", 1),
        ("b", 2),
        ("c", 3),
    ]


def test_display_form_details():
    from django import forms

    class F(forms.Form):
        email = NoIdnEmailField(label="Courriel")

    form = F(data={"email": "pas-un-email"})
    form.is_valid()
    details = tools.display_form_details(form)
    assert '"Courriel": "pas-un-email"' in details
    assert '"email"' in details
