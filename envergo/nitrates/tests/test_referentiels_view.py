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
        "categories_cultures",
        "sous_cultures",
        "mapping_sous_culture_vers_branche",
        "categories_fertilisants",
        "sous_fertilisants",
        "mapping_sous_fertilisant_vers_type",
        "codes_prescription",
        "notes",
        "evenements_phenologiques",
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


def test_sous_fertilisant_expose_flags_prefill(client, nitrates_site):
    """Carte #98 : les flags de pré-remplissage d'un sous-fertilisant
    (effluent_peu_charge…) sont exposés au front pour que la cascade JS les
    pousse en hidden inputs et auto-résolve les questions complémentaires."""
    from django.core.cache import cache
    from django.core.management import call_command

    call_command("seed_referentiels")
    # L'endpoint est cache_page en non-DEBUG : un test antérieur a pu mettre
    # en cache une réponse pré-seed. On vide pour lire l'état à jour.
    cache.clear()
    response = client.get("/api/referentiels/")
    data = response.json()
    elevage = data["sous_fertilisants"]["effluents_peu_charges_elevage"]
    assert elevage["flags"] == {
        "effluent_peu_charge": "true",
        "effluent_peu_charge_elevage": "true",
    }


def test_arbre_endpoint_renvoie_json(client, nitrates_site):
    response = client.get("/api/arbre/")
    assert response.status_code == 200
    data = response.json()
    assert "arbre" in data
    assert data["arbre"]["noeud"]["id"] == "n_zvn"
