"""Couleurs des zones de la carte, éditables dans l'admin (CouleurZone)."""

import json
import re

import pytest
from django.contrib.sites.models import Site
from django.core.exceptions import ValidationError

from envergo.geodata.models import MAP_TYPES
from envergo.nitrates.models import CouleurZone
from envergo.nitrates.models_carto import couleurs_par_cle

pytestmark = pytest.mark.django_db


@pytest.fixture
def nitrates_site(settings):
    settings.ENVERGO_NITRATES_DOMAIN = "testserver"
    site, _ = Site.objects.get_or_create(domain="testserver")
    site.name = "Simulateur nitrates"
    site.save()
    return site


def test_seed_artois_picardie_meme_couleur():
    """Escaut (FRA) et Sambre (FRB2) forment un seul bassin à l'écran."""
    c = couleurs_par_cle(MAP_TYPES.zv_nitrates)
    assert c["FRA"] == c["FRB2"]


def test_seed_bassins_voisins_distincts():
    c = couleurs_par_cle(MAP_TYPES.zv_nitrates)
    for code in ("FRA", "FRB1-FRC", "FRD", "FRF", "FRG", "FRH"):
        assert code in c
    distinctes = {c[k] for k in ("FRA", "FRB1-FRC", "FRD", "FRF", "FRG", "FRH")}
    assert len(distinctes) == 6


def test_couleur_hex_validee():
    cz = CouleurZone(map_type=MAP_TYPES.zv_nitrates, cle="TEST", couleur="bleu")
    with pytest.raises(ValidationError):
        cz.full_clean()


def test_couleur_injectee_dans_la_page(client, settings, nitrates_site):
    """La couleur éditée dans l'admin est servie à la page suivante, sans
    passer par le GeoJSON (caché 24 h)."""
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = True
    CouleurZone.objects.filter(map_type=MAP_TYPES.zv_nitrates, cle="FRH").update(
        couleur="#123456"
    )

    resp = client.get("/")

    assert resp.status_code == 200
    m = re.search(
        r'<script id="nitrates-zv-couleurs" type="application/json">(.*?)</script>',
        resp.content.decode(),
    )
    assert m
    assert json.loads(m.group(1))["FRH"] == "#123456"
