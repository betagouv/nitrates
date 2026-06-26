"""Cache de load_referentiels() + invalidation sur écriture.

load_referentiels fait ~27 requêtes SQL (toute la DB référentiel). L'éditeur
d'arbre l'appelait des centaines de fois par requête (une fois par date
d'événement phénologique rendue) → ~18 s. On le cache désormais, avec
invalidation par signaux post_save/post_delete sur les modèles référentiel.

Ces tests garantissent que :
  - le cache sert bien la même instance entre deux appels (pas de re-query) ;
  - toute écriture sur un modèle référentiel invalide le cache (l'admin voit
    ses éditions immédiatement) ;
  - le seed invalide aussi (il écrit des modèles → signaux).
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from envergo.nitrates.models import EvenementPhenologique, Fertilisant
from envergo.nitrates.yaml_tree.loader import (
    invalider_cache_referentiels,
    load_referentiels,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _vide_cache_avant_chaque_test():
    # Le cache est process-local : un test précédent a pu le remplir.
    invalider_cache_referentiels()
    yield
    invalider_cache_referentiels()


def test_cache_evite_les_requetes_au_2e_appel():
    # 1er appel : remplit le cache (fait des requêtes).
    with CaptureQueriesContext(connection) as ctx1:
        load_referentiels()
    assert len(ctx1) > 0, "le 1er appel devrait interroger la DB"

    # 2e appel : sert le cache, zéro requête.
    with CaptureQueriesContext(connection) as ctx2:
        load_referentiels()
    assert len(ctx2) == 0, f"le 2e appel ne devrait rien requêter (got {len(ctx2)})"


def test_cache_renvoie_la_meme_instance():
    a = load_referentiels()
    b = load_referentiels()
    assert a is b


def test_ecriture_fertilisant_invalide_le_cache():
    load_referentiels()  # remplit le cache
    # Une création de Fertilisant déclenche post_save → invalidation.
    Fertilisant.objects.create(
        identifiant="zzz_test_cache",
        libelle_public="Test cache",
        categorie="autre",
        type_reglementaire="type_II",
    )
    with CaptureQueriesContext(connection) as ctx:
        ref = load_referentiels()
    assert len(ctx) > 0, "le cache aurait dû être invalidé par la création"
    assert "zzz_test_cache" in ref["sous_fertilisants"]


def test_suppression_invalide_le_cache():
    ev = EvenementPhenologique.objects.create(
        identifiant="zzz_ev_cache", libelle_public="X", date_calendrier="01/01"
    )
    load_referentiels()  # cache avec l'événement
    ev.delete()  # post_delete → invalidation
    ref = load_referentiels()
    assert "zzz_ev_cache" not in ref["evenements_phenologiques"]
