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
    """Point en ZV, sans reponses cascade : on est en attente d'une question
    complementaire. Depuis #112, tant qu'une QC est en attente :
      - le panneau resultat de DROITE n'est PAS rendu (colonne unique) ;
      - les QC apparaissent SOUS le formulaire (bloc .resultat-panel--questions).
    """
    response = client.get("/simulateur/?lng=4.0345&lat=49.2583")
    assert response.status_code == 200
    # Bloc QC rendu sous le formulaire (#112).
    assert b"resultat-panel--questions" in response.content
    assert b"qc-sous-form" in response.content
    assert b"Questions compl" in response.content
    # Pas de panneau resultat a droite tant qu'une QC est en attente (#112) :
    # ni la colonne result-col, ni le header du panneau resultat.
    assert b"result-col" not in response.content
    assert b"glementation nitrates applicable" not in response.content


def test_panneaux_debug_actifs_par_flag_dedie(
    client, nitrates_site, setup_geodata, settings
):
    """Le bloc Debug parcours est gate par NITRATES_FORM_DEBUG_PANELS,
    independamment de DEBUG. Permet de l'activer en staging sans DEBUG=True."""
    settings.DEBUG = False
    settings.NITRATES_FORM_DEBUG_PANELS = True
    response = client.get("/simulateur/?lng=4.0345&lat=49.2583")
    assert b"Debug parcours" in response.content


def test_panneaux_debug_caches_sans_flag(
    client, nitrates_site, setup_geodata, settings
):
    """Sans le flag, pas de bloc Debug meme si DEBUG=True (le flag est la
    seule source de verite a present)."""
    settings.DEBUG = True
    settings.NITRATES_FORM_DEBUG_PANELS = False
    response = client.get("/simulateur/?lng=4.0345&lat=49.2583")
    assert b"Debug parcours" not in response.content


def test_panel_debug_affiche_code_prescription_et_libelle(
    client, nitrates_site, setup_geodata, settings
):
    """Le panel debug affiche le(s) code(s) prescription appliqué(s) avec leur
    libellé court (mots_cles du référentiel), pour distinguer d'un coup d'oeil
    des PC au texte très proche (ex pc13 vs pc14). Colza type_III -> pc11."""
    settings.NITRATES_FORM_DEBUG_PANELS = True
    response = client.get(
        "/simulateur/?lng=4.0345&lat=49.2583"
        "&occupation_sol=culture_principale&sous_culture=colza"
        "&type_fertilisant=type_III"
    )
    assert response.status_code == 200
    html = response.content.decode()
    assert "code(s) prescription" in html
    # Code + libellé court côte à côte (pc11 = "colza" dans le référentiel).
    assert "<code>pc11</code>" in html


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
    # Note 2026-05-12 : le badge "INTERDIT" dans le header epandage a ete
    # remplace par une phrase narrative dans la simplification UX (header
    # juste "Épandage" + phrase "L'épandage est interdit..."). On verifie
    # la presence du libelle "interdit" dans la phrase.
    assert b"interdit" in response.content
    # Periode toute l'annee, ecrite en annee agricole (01/07 -> 30/06)
    # pour que le calendrier d'epandage rende une zone rouge pleine
    # sur l'axe juil-juin (cf. #54).
    assert b"01/07" in response.content
    assert b"30/06" in response.content
