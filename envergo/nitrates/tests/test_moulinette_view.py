"""Tests de la vue /simulateur/ : rendu form, rendu resultat, integration
avec MoulinetteNitrates."""

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.contrib.sites.models import Site

from envergo.geodata.models import MAP_TYPES, Department, Map, Zone
from envergo.moulinette.models import Criterion, Regulation

pytestmark = pytest.mark.django_db


@pytest.fixture
def nitrates_site(settings):
    settings.ENVERGO_NITRATES_DOMAIN = "testserver"
    site, _ = Site.objects.get_or_create(domain="testserver")
    site.name = "Simulateur nitrates"
    site.save()
    return site


@pytest.fixture
def setup_geodata():
    Department.objects.create(
        department="51",
        geometry=MultiPolygon(Polygon.from_bbox((3.5, 48.7, 5.0, 49.7))),
    )
    m, _ = Map.objects.get_or_create(
        map_type=MAP_TYPES.zv_nitrates,
        defaults={"name": "ZV test", "description": "test"},
    )
    Zone.objects.create(
        map=m,
        geometry=MultiPolygon(Polygon.from_bbox((3.5, 48.7, 5.0, 49.7))),
        attributes={"CdEuBassin": "FRB1", "NomZoneVul": "Test"},
    )
    regulation, _ = Regulation.objects.get_or_create(
        regulation="directive_nitrates",
        defaults={
            "evaluator": (
                "envergo.nitrates.regulations.directive_nitrates."
                "DirectiveNitratesEvaluator"
            ),
        },
    )
    Criterion.objects.get_or_create(
        regulation=regulation,
        evaluator=(
            "envergo.nitrates.regulations.arbre_decision.ArbreDecisionEvaluator"
        ),
        defaults={
            "backend_title": "Arbre",
            "title": "Periodes epandage",
            "activation_map": m,
        },
    )
    return m


def test_form_rendu_sans_params(client, nitrates_site):
    response = client.get("/simulateur/")
    assert response.status_code == 200
    assert b"Simulateur nitrates" in response.content
    assert b'name="lng"' in response.content
    assert b'name="lat"' in response.content


def test_form_inclut_carte_et_simulator_js(client, nitrates_site):
    """La carte cliquable et son JS doivent etre presents pour permettre
    de saisir lat/lng par clic."""
    response = client.get("/simulateur/")
    assert b'id="nitrates-map"' in response.content
    assert b"simulator.js" in response.content
    assert b"NITRATES_DEBUG_URL" in response.content


def test_resultat_rendu_avec_lat_lng_en_zv(client, nitrates_site, setup_geodata):
    """Point en ZV, sans reponses cascade : on doit voir des questions
    subsidiaires."""
    response = client.get("/simulateur/?lng=4.0345&lat=49.2583")
    assert response.status_code == 200
    # Header du panneau resultat
    assert b"glementations applicables" in response.content
    # Questions complementaires affichees
    assert b"Questions compl" in response.content


def test_resultat_rendu_hors_zv(client, nitrates_site, setup_geodata):
    """Point offshore : pas en ZV, message clair."""
    response = client.get("/simulateur/?lng=-30&lat=30")
    assert response.status_code == 200
    assert b"Hors zone vuln" in response.content


def test_resultat_rendu_chemin_complet_sol_non_cultive(
    client, nitrates_site, setup_geodata
):
    """sol_non_cultive court-circuite : on atteint un resultat directement
    avec des periodes, sans avoir besoin de fournir sous_culture."""
    response = client.get(
        "/simulateur/?lng=4.0345&lat=49.2583&occupation_sol=sol_non_cultive"
    )
    assert response.status_code == 200
    assert b"r_sol_non_cultive" in response.content
    assert b"interdiction" in response.content
