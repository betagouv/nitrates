"""Tests de l'endpoint /api/referentiels/ qui expose le YAML referentiels."""

import pytest
from django.contrib.sites.models import Site

pytestmark = pytest.mark.django_db


@pytest.fixture
def nitrates_site(settings):
    settings.ENVERGO_NITRATES_DOMAIN = "testserver"
    site, _ = Site.objects.get_or_create(domain="testserver")
    site.name = "Simulateur nitrates"
    site.save()
    return site


def test_referentiels_endpoint_renvoie_json(client, nitrates_site):
    response = client.get("/api/referentiels/")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"


def test_referentiels_contient_listes_fermees(client, nitrates_site):
    response = client.get("/api/referentiels/")
    data = response.json()
    # Cles principales utilisees par la cascade JS et l'arbre.
    for key in (
        "types_fertilisants",
        "occupations_sol",
        "cultures",
        "codes_prescription",
        "notes",
        "evenements_phenologiques",
        "sous_fertilisants",
        "mapping_sous_fertilisant_vers_type",
    ):
        assert key in data, f"Cle {key!r} manquante dans referentiels.json"


def test_referentiels_types_fertilisants_structure(client, nitrates_site):
    """Verifie qu'un type de fertilisant a bien les champs attendus
    (libelle_public sert a l'affichage front)."""
    response = client.get("/api/referentiels/")
    data = response.json()
    type_0 = data["types_fertilisants"]["type_0"]
    assert "libelle_public" in type_0
    assert isinstance(type_0["libelle_public"], str)


def test_arbre_endpoint_renvoie_json(client, nitrates_site):
    response = client.get("/api/arbre/")
    assert response.status_code == 200
    data = response.json()
    assert "arbre" in data
    assert data["arbre"]["noeud"]["id"] == "n_zvn"
