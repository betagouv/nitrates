"""Tests de la page « Aide & définitions » (cartes #110 / #288)."""

import pytest
from django.contrib.sites.models import Site

from envergo.nitrates.contenu_rich.glossaire import invalider_cache_glossaire
from envergo.nitrates.models import ContenuRichDSFR
from envergo.nitrates.models_contenu_rich import TYPE_DEFINITION

pytestmark = pytest.mark.django_db


@pytest.fixture
def nitrates_site(settings):
    settings.ENVERGO_NITRATES_DOMAIN = "testserver"
    site, _ = Site.objects.get_or_create(domain="testserver")
    site.name = "Simulateur nitrates"
    site.save()
    return site


@pytest.fixture(autouse=True)
def _cache_glossaire_propre():
    invalider_cache_glossaire()
    yield
    invalider_cache_glossaire()


def _definition(cle, titre, categorie="fertilisants-effluents", blocs=None):
    return ContenuRichDSFR.objects.create(
        cle=cle,
        libelle_admin=titre,
        type_contenu=TYPE_DEFINITION,
        titre_public=titre,
        categorie=categorie,
        blocs={
            "schema": 1,
            "blocs": blocs
            or [{"type": "paragraphe", "data": {"texte": f"Définition de {titre}."}}],
        },
    )


def test_page_definitions_200(client, nitrates_site):
    response = client.get("/definitions/")
    assert response.status_code == 200
    assert "Aide & définitions" in response.content.decode()


def test_page_vide_sans_500(client, nitrates_site):
    response = client.get("/definitions/")
    assert response.status_code == 200
    assert "bientôt disponibles" in response.content.decode()


def test_definitions_groupees_par_categorie_et_ancrees(client, nitrates_site):
    _definition("definition.azote-efficace", "Azote efficace", "azote-bilans")
    _definition("definition.fertirrigation", "Fertirrigation")
    response = client.get("/definitions/")
    html = response.content.decode()
    assert 'id="section-azote-bilans"' in html
    assert 'id="section-fertilisants-effluents"' in html
    assert 'id="azote-efficace"' in html
    assert "Définition de Azote efficace." in html
    # Section sans contenu absente (pas de section « Pratique » vide).
    assert 'id="section-pratique-documents"' not in html


def test_definition_sans_categorie_reste_visible(client, nitrates_site):
    _definition("definition.ismo", "ISMO", categorie="")
    response = client.get("/definitions/")
    html = response.content.decode()
    assert "Autres définitions" in html
    assert 'id="ismo"' in html


def test_faq_absente_si_aucune_entree(client, nitrates_site):
    _definition("definition.icpe", "ICPE")
    response = client.get("/definitions/")
    html = response.content.decode()
    assert 'id="section-faq"' not in html
    assert "Questions fréquentes" not in html


def test_faq_presente_si_entrees(client, nitrates_site):
    ContenuRichDSFR.objects.create(
        cle="faq.zone-vulnerable",
        libelle_admin="Mon exploitation est-elle en zone vulnérable ?",
        titre_public="Mon exploitation est-elle en zone vulnérable ?",
        blocs={
            "schema": 1,
            "blocs": [{"type": "paragraphe", "data": {"texte": "Réponse."}}],
        },
    )
    response = client.get("/definitions/")
    html = response.content.decode()
    assert 'id="section-faq"' in html
    assert "Mon exploitation est-elle en zone vulnérable ?" in html


def test_accordeons_id_prefix_par_definition(client, nitrates_site):
    # Deux définitions avec foldable « détail réglementaire » : leurs ids
    # d'accordéon ne doivent JAMAIS entrer en collision (carte #157).
    foldable = [
        {
            "type": "foldable",
            "data": {
                "titre": "Voir le détail réglementaire",
                "blocs": [{"type": "paragraphe", "data": {"texte": "Détail."}}],
            },
        }
    ]
    _definition("definition.interculture", "Interculture", blocs=foldable)
    _definition("definition.epandage", "Épandage", blocs=foldable)
    html = client.get("/definitions/").content.decode()
    assert 'id="def-interculture-accordion-1"' in html
    assert 'id="def-epandage-accordion-1"' in html


def test_nav_onglets_presente_et_active(client, nitrates_site):
    # Barre d'onglets héritée par toutes les pages nitrates ; aria-current
    # sur l'onglet correspondant à la page.
    html_home = client.get("/").content.decode()
    assert 'aria-label="Menu principal"' in html_home
    assert "Aide & définitions" in html_home

    html_defs = client.get("/definitions/").content.decode()
    assert 'aria-label="Menu principal"' in html_defs
    # L'onglet actif de /definitions/ est « Aide & définitions ».
    assert 'aria-current="page">Aide & définitions</a>' in html_defs
    assert 'aria-current="page">Simulateur</a>' not in html_defs
    # Et inversement sur la home.
    assert 'aria-current="page">Simulateur</a>' in html_home


def test_exemption_lockdown_root_ouvert(client, nitrates_site, settings):
    # LE piège silencieux : sans exemption, OK en local mais redirect login
    # sur staging public (lockdown ProConnect).
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = True
    response = client.get("/definitions/")
    assert response.status_code == 200


def test_lockdown_ferme_sans_root_ouvert(client, nitrates_site, settings):
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = False
    response = client.get("/definitions/")
    assert response.status_code == 302
