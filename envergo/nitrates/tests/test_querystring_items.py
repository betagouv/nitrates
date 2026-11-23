"""Une cle `items` dans la query string ne doit pas casser le rendu.

Dans un gabarit, `data.items` essaie `data["items"]` avant la methode
`.items()` : `/?items=abc` faisait iterer la chaine "abc" et levait
`ValueError: Need 2 values to unpack in for loop` (500 en prod, envoye par
un scanner XSS le 18/11/2026 puis le 21/11/2026). Le filtre `paires`
appelle la methode sur l'objet lui-meme.
"""

import pytest
from django.contrib.sites.models import Site
from django.http import QueryDict

from envergo.nitrates.templatetags.nitrates_tags import paires

pytestmark = pytest.mark.django_db


@pytest.fixture
def nitrates_site(settings):
    settings.ENVERGO_NITRATES_DOMAIN = "testserver"
    site, _ = Site.objects.get_or_create(domain="testserver")
    site.name = "Simulateur nitrates"
    site.save()
    return site


def test_paires_ignore_une_cle_items():
    assert paires({"items": "abc", "lat": "48.5"}) == [
        ("items", "abc"),
        ("lat", "48.5"),
    ]


def test_paires_querydict_et_vide():
    assert paires(QueryDict("items=abc&items=def")) == [("items", "def")]
    assert paires(None) == []
    assert paires({}) == []


@pytest.mark.parametrize("valeur", ["abc", "", "'>\"<svg/onload=confirm(1)>"])
def test_root_avec_param_items(client, settings, nitrates_site, valeur):
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = True

    resp = client.get("/", {"items": valeur, "widget": "x"})

    assert resp.status_code == 200
    contenu = resp.content.decode()
    assert "<svg/onload" not in contenu
