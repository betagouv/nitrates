"""#273 : soumission du simulateur en htmx, sans rechargement de page.

Le serveur rend toujours la page complete ; soumission_partielle.js n'en
reprend que les zones qui changent. On verifie ici le contrat cote serveur :
attributs htmx du formulaire, zones toujours presentes (meme vides), barre de
progression toujours rendue, catalog de la parcelle en JSON.
"""

import json
import re

import pytest
from django.contrib.sites.models import Site

from envergo.nitrates.tests import test_moulinette_view
from envergo.nitrates.views import catalog_pour_js

pytestmark = pytest.mark.django_db

# Meme jeu de donnees geo que les tests de la vue simulateur.
setup_geodata = test_moulinette_view.setup_geodata


@pytest.fixture
def nitrates_site(settings):
    settings.ENVERGO_NITRATES_DOMAIN = "testserver"
    site, _ = Site.objects.get_or_create(domain="testserver")
    site.name = "Simulateur nitrates"
    site.save()
    return site


def _balise_form(html):
    return re.search(r'<form id="form-simulateur"[^>]*>', html).group(0)


def test_formulaire_soumis_en_htmx_sur_la_page_courante(client, nitrates_site):
    html = client.get("/simulateur/").content.decode()
    form = _balise_form(html)
    assert 'hx-get="/simulateur/"' in form
    assert 'hx-swap="none"' in form
    assert 'hx-sync="this:replace"' in form
    assert 'hx-params="not csrfmiddlewaretoken"' in form
    # Repli sans JS : le GET natif reste en place.
    assert 'method="get"' in form
    assert 'action="/simulateur/"' in form


def test_htmx_embarque_et_historique_htmx_desactive(client, nitrates_site):
    """CSP self : htmx est servi par l'application (pas de CDN). Son historique
    est coupe (restauration par instantane incompatible avec la carte)."""
    html = client.get("/simulateur/").content.decode()
    assert "nitrates/vendor/htmx-2.0.4.min.js" in html
    assert "unpkg.com" not in html
    assert "soumission_partielle.js" in html
    assert '"historyEnabled": false' in html


def test_modules_qc_et_resultat_charges_sans_resultat(client, nitrates_site):
    """Les QC et le resultat peuvent apparaitre sans rechargement : leurs
    modules sont donc charges des la page vierge."""
    html = client.get("/simulateur/").content.decode()
    for module in (
        "qc_reponses_precedentes.js",
        "subsidiaires_cascade.js",
        "scroll_resultat.js",
        "recap_choix.js",
        "drawer_conditions.js",
        "calculatrice-calendrier.js",
    ):
        assert module in html, module
    # La reprise des reponses QC pre-coche avant que la cascade des QC ne
    # revele les questions enfants.
    assert html.index("qc_reponses_precedentes.js") < html.index(
        "subsidiaires_cascade.js"
    )


def test_zones_remplacables_presentes_sur_la_page_vierge(client, nitrates_site):
    html = client.get("/simulateur/").content.decode()
    assert 'id="zone-recap"' in html
    assert 'id="zone-qc"' in html
    assert 'id="zone-fin-simulation"' in html
    assert 'id="nitrates-soumission-chargement"' in html
    # Barre de progression rendue et visible tant qu'il n'y a pas de resultat.
    barre = re.search(r'<div id="nitrates-progress-bar"[^>]*>', html).group(0)
    assert "hidden" not in barre


def test_qc_en_attente_dans_la_zone_qc(client, nitrates_site, setup_geodata):
    html = client.get("/simulateur/?lng=4.0345&lat=49.2583").content.decode()
    zone = html.split('id="zone-qc"', 1)[1]
    assert 'id="qc-bloc"' in zone
    barre = re.search(r'<div id="nitrates-progress-bar"[^>]*>', html).group(0)
    assert "hidden" not in barre


def test_resultat_final_barre_masquee_et_fin_de_simulation(
    client, nitrates_site, setup_geodata
):
    html = client.get(
        "/simulateur/?lng=4.0345&lat=49.2583&occupation_sol=sol_non_cultive"
    ).content.decode()
    assert "result-col" in html
    barre = re.search(r'<div id="nitrates-progress-bar"[^>]*>', html).group(0)
    assert "hidden" in barre
    zone = html.split('id="zone-fin-simulation"', 1)[1]
    assert "data-nitrates-fin-simulation" in zone[:300]
    assert 'id="recap-choix"' in html.split('id="zone-recap"', 1)[1]


def test_catalog_expose_en_json(client, nitrates_site, setup_geodata):
    html = client.get("/simulateur/?lng=4.0345&lat=49.2583").content.decode()
    bloc = re.search(
        r'<script id="nitrates-catalog-data" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    assert bloc, "bloc JSON du catalog absent"
    catalog = json.loads(bloc.group(1))
    assert catalog["en_zone_vulnerable"] is True
    assert "window.NITRATES_CATALOG = JSON.parse(" in html


def test_catalog_absent_sans_parcelle(client, nitrates_site):
    html = client.get("/simulateur/").content.decode()
    assert 'id="nitrates-catalog-data"' not in html
    assert "window.NITRATES_CATALOG" not in html


def test_catalog_pour_js_donnee_indisponible():
    """Le catalog est un dict paresseux qui leve KeyError quand une donnee ne
    peut pas etre calculee : on retombe sur vide, comme le template avant."""

    class CatalogPartiel(dict):
        def __missing__(self, key):
            raise KeyError(key)

    catalog = CatalogPartiel(region_code="44", en_zone_vulnerable=True)
    assert catalog_pour_js(catalog) == {
        "department_code": "",
        "region_code": "44",
        "region_label": "",
        "en_zone_vulnerable": True,
        "bassin": "",
        "bassin_label": "",
        "en_zar": False,
        "en_grand_est": True,
        "zone_grand_est_1": False,
        "zone_grand_est_2": False,
        "en_bretagne": False,
        "zone_mais_bretagne": "",
    }


def test_racine_publique_soumet_sur_la_racine(client, settings, nitrates_site):
    settings.NITRATES_ROOT_OUVERT = True
    html = client.get("/").content.decode()
    assert 'hx-get="/"' in _balise_form(html)
