"""Référencement SEO/GEO : robots.txt, sitemap.xml, llms.txt (#290, #565).

La règle verrouillée ici : ces fichiers répondent à un anonyme dans TOUTES
les configurations de lockdown. Si un de ces tests casse, ne pas l'adapter :
c'est la règle qui est violée.
"""

import json
import re

import pytest
from django.contrib.sites.models import Site

from envergo.contrib.middleware import CHEMINS_SEO_PUBLICS

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def nitrates_site(settings):
    settings.ENVERGO_NITRATES_DOMAIN = "testserver"
    site, _ = Site.objects.get_or_create(domain="testserver")
    return site


@pytest.mark.parametrize("root_ouvert", [False, True])
@pytest.mark.parametrize("chemin", CHEMINS_SEO_PUBLICS)
def test_fichiers_seo_publics_en_lockdown(client, settings, chemin, root_ouvert):
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = root_ouvert
    response = client.get(chemin)
    assert response.status_code == 200


def test_robots_hors_prod_interdit_tout(client, settings):
    settings.ENV_NAME = "staging"
    body = client.get("/robots.txt").content.decode()
    assert "Disallow: /\n" in body
    assert "Sitemap:" not in body


@pytest.mark.parametrize("env_name", ["prod", "production"])
def test_robots_prod_ouvre_et_pointe_le_sitemap(client, settings, env_name):
    settings.ENV_NAME = env_name
    settings.ENVERGO_NITRATES_DOMAIN = "nitrates.beta.gouv.fr"
    response = client.get("/robots.txt")
    body = response.content.decode()
    assert response["Content-Type"].startswith("text/plain")
    assert "Allow: /\n" in body
    assert "Disallow: /\n" not in body
    assert "Disallow: /simulateur/" in body
    assert "Sitemap: https://nitrates.beta.gouv.fr/sitemap.xml" in body
    assert "service public de l'État" in body


def test_robots_prod_ne_divulgue_pas_admin_secret(client, settings):
    settings.ENV_NAME = "prod"
    settings.ADMIN_URL = "admin-tres-secret-1234/"
    body = client.get("/robots.txt").content.decode()
    assert "tres-secret" not in body


def _locs(response):
    return re.findall(r"<loc>([^<]+)</loc>", response.content.decode())


def test_sitemap_root_ouvert_liste_home_definitions_et_prescriptions(client, settings):
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = True
    response = client.get("/sitemap.xml")
    assert response["Content-Type"].startswith("application/xml")
    locs = _locs(response)
    assert "https://testserver/" in locs
    assert "https://testserver/definitions/" in locs
    assert "https://testserver/cgu/" in locs
    assert any("/prescription/" in loc for loc in locs)
    assert not any("/simulateur/" in loc for loc in locs)


def test_sitemap_site_ferme_ne_liste_que_le_pied_de_page(client, settings):
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = False
    locs = _locs(client.get("/sitemap.xml"))
    assert "https://testserver/" not in locs
    assert "https://testserver/mentions-legales/" in locs
    assert not any("/prescription/" in loc for loc in locs)


def test_pages_du_sitemap_lisibles_en_anonyme(client, settings):
    """Le sitemap ne doit jamais pointer un robot vers un login."""
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = True
    for loc in _locs(client.get("/sitemap.xml")):
        chemin = loc.removeprefix("https://testserver")
        assert client.get(chemin).status_code == 200, chemin


def test_llms_txt_presente_le_service(client, settings):
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = True
    response = client.get("/llms.txt")
    body = response.content.decode()
    assert response["Content-Type"].startswith("text/markdown")
    assert body.startswith("# Nitrat'Info\n")
    # Qui porte le service, quoi, quel périmètre (textes des CGU, #550).
    assert "service public numérique de l'État" in body
    assert "ministère en charge de l'agriculture" in body
    assert "ministère en charge de la transition écologique" in body
    assert "Mesure 1 des programmes d'actions nitrates" in body
    assert "titre informatif" in body
    assert "pas une preuve opposable en cas de contrôle" in body
    assert "dérogations préfectorales" in body
    assert "seules les mesures 1 et 6 sont traitées" in body
    assert "conseillères et conseillers agricoles" in body
    assert "](https://testserver/definitions/)" in body
    assert "&#x27;" not in body  # pas d'échappement HTML dans du markdown


def test_balises_canonical_opengraph_jsonld(client, settings):
    settings.LOCKDOWN_BEHIND_LOGIN = False
    html = client.get("/cgu/").content.decode()
    assert '<link rel="canonical" href="https://testserver/cgu/">' in html
    assert 'property="og:url" content="https://testserver/cgu/"' in html
    assert "Service de l'État : savoir pour sa parcelle" in html  # meta
    bloc = re.search(r'<script type="application/ld\+json">(.+?)</script>', html, re.S)
    graphe = {n["@type"]: n for n in json.loads(bloc.group(1))["@graph"]}
    assert graphe["WebSite"]["url"] == "https://testserver/"
    service = graphe["GovernmentService"]
    assert "mesure 1" in service["description"]
    assert "preuve opposable" in service["description"]
    assert {p["name"] for p in service["provider"]} == {
        "Ministère en charge de l'agriculture",
        "Ministère en charge de la transition écologique",
    }


def test_meta_description_prescription(client, settings):
    settings.LOCKDOWN_BEHIND_LOGIN = False
    html = client.get("/prescription/pc5/").content.decode()
    assert 'content="Prescription conditionnée PC5' in html
