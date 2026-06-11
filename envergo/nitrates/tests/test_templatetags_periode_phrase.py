"""Tests de `periode_phrase` et de la resolution des libelles phenologiques
(#85 : plus de slug snake_case a l'ecran, on resout le libelle_public)."""

import pytest

from envergo.nitrates.templatetags.nitrates_tags import (
    _libelle_phenologique,
    _minuscule_initiale,
    periode_phrase,
)

# load_referentiels lit l'arbre/referentiel actif en DB.
pytestmark = pytest.mark.django_db


def test_periode_phrase_bornes_fixes():
    assert periode_phrase({"du": "15/07", "au": "15/02"}) == "du 15/07 au 15/02"


def test_periode_phrase_borne_pheno_debut_resout_libelle():
    # `derniere_coupe_luzerne` -> "Dernière coupe de la luzerne", minuscule
    # initiale car insere en milieu de phrase. Plus aucun slug ni guillemet.
    phrase = periode_phrase({"du": "derniere_coupe_luzerne", "au": "15/01"})
    assert phrase == "de dernière coupe de la luzerne au 15/01"
    assert "_" not in phrase
    assert "«" not in phrase


def test_periode_phrase_borne_pheno_fin_resout_libelle():
    phrase = periode_phrase({"du": "15/07", "au": "brunissement_des_soies"})
    assert phrase == "du 15/07 au brunissement des soies (maïs)"
    assert "_" not in phrase


def test_libelle_phenologique_fallback_slug_inconnu():
    # Slug absent du referentiel : fallback lisible (underscores -> espaces),
    # jamais le snake_case brut.
    assert _libelle_phenologique("slug_inexistant_xyz") == "slug inexistant xyz"


def test_minuscule_initiale():
    assert _minuscule_initiale("Dernière coupe") == "dernière coupe"
    assert _minuscule_initiale("Brunissement (maïs)") == "brunissement (maïs)"
    assert _minuscule_initiale("") == ""
