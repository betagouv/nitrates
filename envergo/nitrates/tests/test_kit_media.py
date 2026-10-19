"""Page Kit média du pied de page (#293) : zip servi en statique."""

import re
import zipfile

import pytest
from django.contrib.sites.models import Site
from django.contrib.staticfiles import finders
from django.urls import reverse as _reverse

from envergo.contrib.middleware import PAGES_FOOTER_PUBLIQUES
from envergo.nitrates.views_kit_media import KIT_MEDIA_STATIC, taille_lisible

pytestmark = pytest.mark.django_db


def reverse(nom):
    return _reverse(nom, urlconf="config.urls_nitrates")


@pytest.fixture
def nitrates_site(settings):
    settings.ENVERGO_NITRATES_DOMAIN = "testserver"
    site, _ = Site.objects.get_or_create(domain="testserver")
    return site


def test_page_kit_media(client, nitrates_site):
    response = client.get(reverse("nitrates_kit_media"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "<h1>Kit média</h1>" in html
    assert f"/static/{KIT_MEDIA_STATIC}" in html
    assert 'download="kit-communication-nitratinfo.zip"' in html
    assert re.search(r"ZIP\s+- 1,6 Mo", html)


def test_zip_est_le_kit_valide():
    # Version validée du 14/10/2026 (3e zip de la carte #293) : la 2e avait
    # perdu la présentation pour les agriculteurs.
    chemin = finders.find(KIT_MEDIA_STATIC)
    assert chemin
    with zipfile.ZipFile(chemin) as kit:
        noms = kit.namelist()
        lisez_moi = kit.read("kit-communication-nitratinfo/LISEZ-MOI.txt")
    assert (
        "kit-communication-nitratinfo/01-textes/presentation-agriculteurs.docx" in noms
    )
    assert "Version du 14 octobre 2026" in lisez_moi.decode()


def test_lien_footer(client, nitrates_site):
    html = client.get(reverse("nitrates_cgu")).content.decode()
    assert f'href="{reverse("nitrates_kit_media")}">Kit média</a>' in html


def test_page_publique_en_lockdown(client, nitrates_site, settings):
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = False
    assert reverse("nitrates_kit_media") in PAGES_FOOTER_PUBLIQUES
    assert client.get(reverse("nitrates_kit_media")).status_code == 200


def test_kit_media_dans_sitemap(client, nitrates_site):
    html = client.get("/sitemap.xml").content.decode()
    assert "/kit-media/" in html


@pytest.mark.parametrize(
    "octets,libelle",
    [(1_628_440, "1,6 Mo"), (5_000_000, "5,0 Mo"), (850_000, "850 Ko"), (12, "1 Ko")],
)
def test_taille_lisible(octets, libelle):
    assert taille_lisible(octets) == libelle
