"""Tests du mapping commune INSEE -> zones maïs 1 / 2 (PAR Bretagne, annexe 7)."""

from collections import Counter

import pytest

from envergo.nitrates.yaml_admin.catalogue_refs import ResolveContext, get_resolver
from envergo.nitrates.zonage_zones_mais_bretagne import (
    _CSV_PATH,
    _mapping,
    zone_mais_bretagne,
)


def test_csv_present_et_charge():
    assert _CSV_PATH.exists()
    assert set(_mapping().values()) == {"zone_1", "zone_2"}


def test_deux_zones_listees_explicitement():
    """Zone 2 = 422 communes de l'annexe 7 ; zone 1 = les 784 autres communes
    bretonnes, listées une à une (pas de complément calculé à la volée)."""
    compte = Counter(_mapping().values())
    assert compte == {"zone_1": 784, "zone_2": 422}


def test_zone_2_aucune_commune_en_ille_et_vilaine():
    deps = {code[:2] for code, zone in _mapping().items() if zone == "zone_2"}
    assert deps == {"22", "29", "56"}


def test_couvre_toute_la_bretagne_et_rien_d_autre():
    deps = {code[:2] for code in _mapping()}
    assert deps == {"22", "29", "35", "56"}


@pytest.mark.parametrize(
    "code_insee, attendu",
    [
        ("22070", "zone_2"),  # Guingamp
        ("29019", "zone_2"),  # Brest
        ("35238", "zone_1"),  # Rennes
        ("56260", "zone_1"),  # Vannes
        ("51046", None),  # Beine-Nauroy (Grand Est)
        ("", None),
        (None, None),
    ],
)
def test_zone_mais_bretagne(code_insee, attendu):
    assert zone_mais_bretagne(code_insee) == attendu


def test_resolveur_catalogue_branche():
    resolver = get_resolver("zone_mais_bretagne")
    assert resolver is not None
    assert resolver.valeurs_branches == ("zone_1", "zone_2")
    assert (
        resolver.resolve(ResolveContext(code_insee="22070", lng_lat=None)) == "zone_2"
    )
