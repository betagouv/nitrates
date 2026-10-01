"""Pages du pied de page en contenu riche, publiques en lockdown (#550)."""

import pytest
from django.contrib.sites.models import Site
from django.urls import reverse as _reverse

from envergo.contrib.middleware import PAGES_FOOTER_PUBLIQUES
from envergo.nitrates.contenu_rich.compilateur import compile_dsfr
from envergo.nitrates.contenu_rich.loader import invalider_cache_contenu_rich
from envergo.nitrates.models import ContenuRichDSFR

pytestmark = pytest.mark.django_db


def reverse(nom):
    # urlconf nitrates pose par le middleware, pas le ROOT_URLCONF des tests
    return _reverse(nom, urlconf="config.urls_nitrates")


PAGES = [
    ("nitrates_mentions_legales", "page.mentions_legales", "Ruche numérique"),
    ("nitrates_cgu", "page.cgu", "Article 7"),
    ("nitrates_accessibilite", "page.accessibilite", "non conforme"),
    ("contact_us", "page.contact", "nitrates@beta.gouv.fr"),
    ("nitrates_donnees_personnelles", "page.donnees_personnelles", "BIGOT-DEKEYZER"),
]


@pytest.fixture
def nitrates_site(settings):
    settings.ENVERGO_NITRATES_DOMAIN = "testserver"
    site, _ = Site.objects.get_or_create(domain="testserver")
    return site


@pytest.fixture(autouse=True)
def _cache_propre():
    invalider_cache_contenu_rich()
    yield
    invalider_cache_contenu_rich()


@pytest.mark.parametrize("nom,cle,extrait", PAGES)
def test_page_rendue_depuis_contenu_seede(client, nitrates_site, nom, cle, extrait):
    # la migration 0035 seede les page.* : rien a creer ici
    assert ContenuRichDSFR.objects.filter(cle=cle).exists()
    response = client.get(reverse(nom))
    assert response.status_code == 200
    html = response.content.decode()
    assert extrait in html
    assert "<h1>" in html


def test_page_sans_contenu_pas_de_500(client, nitrates_site):
    ContenuRichDSFR.objects.filter(cle="page.cgu").delete()
    response = client.get(reverse("nitrates_cgu"))
    assert response.status_code == 200
    assert "Contenu bientôt disponible" in response.content.decode()


def test_edition_admin_prise_en_compte(client, nitrates_site):
    c = ContenuRichDSFR.objects.get(cle="page.contact")
    c.blocs = {
        "schema": 1,
        "blocs": [{"type": "paragraphe", "data": {"texte": "Edite"}}],
    }
    c.save()
    html = client.get(reverse("contact_us")).content.decode()
    assert "<p>Edite</p>" in html


@pytest.mark.parametrize("nom,cle,extrait", PAGES)
def test_chemins_exemptes_coherents_avec_urls(nom, cle, extrait):
    assert reverse(nom) in PAGES_FOOTER_PUBLIQUES


@pytest.mark.parametrize("path", list(PAGES_FOOTER_PUBLIQUES))
def test_pages_footer_publiques_en_lockdown(client, nitrates_site, settings, path):
    # meme root ferme : ce sont des obligations legales
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = False
    assert client.get(path).status_code == 200


def test_lockdown_ferme_toujours_le_simulateur(client, nitrates_site, settings):
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = False
    assert client.get("/definitions/").status_code == 302


def test_footer_liste_les_pages(client, nitrates_site):
    html = client.get(reverse("nitrates_cgu")).content.decode()
    for nom, _, _ in PAGES:
        assert f'href="{reverse(nom)}"' in html


def test_bandeau_nitrat_info(client, nitrates_site):
    html = client.get(reverse("nitrates_cgu")).content.decode()
    assert '<p class="fr-header__service-title">Nitrat\'Info</p>' in html


def test_titres_page_demarrent_en_h2():
    html = compile_dsfr(
        [{"type": "titre_principal", "data": {"texte": "Article 1"}}], niveau_base=2
    )
    assert '<h2 class="fr-h2">Article 1</h2>' in html


def test_lien_mailto_sans_nouvel_onglet():
    html = compile_dsfr(
        [
            {
                "type": "paragraphe",
                "data": {"texte": [{"texte": "nous", "lien": "mailto:a@b.fr"}]},
            }
        ]
    )
    assert '<a href="mailto:a@b.fr" class="fr-link">nous</a>' in html


def test_titre_onglet_nitrat_info(client, nitrates_site):
    html = client.get(reverse("nitrates_cgu")).content.decode()
    assert "— Nitrat'Info" in html
