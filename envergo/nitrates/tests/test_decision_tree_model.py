"""Tests du modele DecisionTree : contraintes d'unicite par scope + activate()."""

import pytest
from django.db import IntegrityError, transaction

from envergo.geodata.models import MAP_TYPES, Map
from envergo.nitrates.models import DecisionTree

pytestmark = pytest.mark.django_db


def _make_zar_map(name="zar_test") -> Map:
    return Map.objects.create(
        name=name, map_type=MAP_TYPES.zone_action_renforcee, description="test"
    )


@pytest.fixture(autouse=True)
def _purge_decision_trees():
    """La migration data 0004 cree un DecisionTree au 1er migrate. On
    purge avant chaque test pour partir d'une table vide."""
    DecisionTree.objects.all().delete()


def _make_tree(**overrides) -> DecisionTree:
    defaults = {
        "name": "test_tree",
        "status": DecisionTree.STATUS_DRAFT,
        "contenu": {"arbre": {"noeud": {"id": "n_test"}}},
        "contenu_yaml_brut": "",
    }
    defaults.update(overrides)
    return DecisionTree.objects.create(**defaults)


def test_un_seul_pan_actif():
    """Contrainte (b) : un seul PAN (scope=national) actif a la fois."""
    _make_tree(name="t1", status=DecisionTree.STATUS_ACTIVE)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _make_tree(name="t2", status=DecisionTree.STATUS_ACTIVE)


def test_pan_et_par_coexistent():
    """Regression cle : PAN + PAR (region) peuvent etre actifs en parallele."""
    _make_tree(name="pan", status=DecisionTree.STATUS_ACTIVE)
    _make_tree(
        name="par_ge",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_REGION,
        region_code="44",
    )
    assert DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE).count() == 2


def test_deux_par_meme_region_sans_map_interdit():
    """Contrainte (c) : un seul PAR-hors-ZAR actif par region."""
    _make_tree(
        name="par1",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_REGION,
        region_code="44",
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _make_tree(
                name="par2",
                status=DecisionTree.STATUS_ACTIVE,
                scope=DecisionTree.SCOPE_REGION,
                region_code="44",
            )


def test_deux_par_regions_differentes_ok():
    """Deux PAR de regions differentes coexistent."""
    _make_tree(
        name="par44",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_REGION,
        region_code="44",
    )
    _make_tree(
        name="par32",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_REGION,
        region_code="32",
    )
    assert (
        DecisionTree.objects.filter(
            status=DecisionTree.STATUS_ACTIVE, scope=DecisionTree.SCOPE_REGION
        ).count()
        == 2
    )


def test_drafts_multiples_autorises():
    """Plusieurs drafts peuvent coexister librement."""
    _make_tree(name="d1", status=DecisionTree.STATUS_DRAFT)
    _make_tree(name="d2", status=DecisionTree.STATUS_DRAFT)
    _make_tree(name="d3", status=DecisionTree.STATUS_DRAFT)
    assert DecisionTree.objects.filter(status=DecisionTree.STATUS_DRAFT).count() == 3


def test_archives_multiples_autorisees():
    """Plusieurs archives peuvent coexister."""
    _make_tree(name="a1", status=DecisionTree.STATUS_ARCHIVE)
    _make_tree(name="a2", status=DecisionTree.STATUS_ARCHIVE)
    assert DecisionTree.objects.filter(status=DecisionTree.STATUS_ARCHIVE).count() == 2


def test_activate_archive_actif_courant():
    """activate() sur un draft : l'actif courant passe en archive, le draft
    devient actif, activated_at est rempli."""
    actif = _make_tree(name="ancien_actif", status=DecisionTree.STATUS_ACTIVE)
    draft = _make_tree(name="nouveau", status=DecisionTree.STATUS_DRAFT)

    draft.activate()

    actif.refresh_from_db()
    draft.refresh_from_db()

    assert actif.status == DecisionTree.STATUS_ARCHIVE
    assert draft.status == DecisionTree.STATUS_ACTIVE
    assert draft.activated_at is not None


def test_activate_idempotent():
    """Re-activer un tree deja actif ne casse pas la contrainte."""
    tree = _make_tree(status=DecisionTree.STATUS_ACTIVE)
    tree.activate()
    tree.refresh_from_db()
    assert tree.status == DecisionTree.STATUS_ACTIVE
    assert DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE).count() == 1


def test_activate_premier_tree_sans_actif_courant():
    """activate() sans actif en DB : le tree devient simplement actif."""
    draft = _make_tree(status=DecisionTree.STATUS_DRAFT)
    draft.activate()
    draft.refresh_from_db()
    assert draft.status == DecisionTree.STATUS_ACTIVE
    assert draft.activated_at is not None


def test_deux_zar_meme_map_interdit():
    """Contrainte (a) : un seul ZAR actif par couche d'activation."""
    zar_map = _make_zar_map()
    _make_tree(
        name="zar1",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_ZAR,
        region_code="44",
        activation_map=zar_map,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _make_tree(
                name="zar2",
                status=DecisionTree.STATUS_ACTIVE,
                scope=DecisionTree.SCOPE_ZAR,
                region_code="44",
                activation_map=zar_map,
            )


def test_deux_zar_maps_differentes_ok():
    """Deux ZAR sur des couches differentes coexistent."""
    _make_tree(
        name="zarA",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_ZAR,
        region_code="44",
        activation_map=_make_zar_map("zar_a"),
    )
    _make_tree(
        name="zarB",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_ZAR,
        region_code="44",
        activation_map=_make_zar_map("zar_b"),
    )
    assert (
        DecisionTree.objects.filter(
            status=DecisionTree.STATUS_ACTIVE, scope=DecisionTree.SCOPE_ZAR
        ).count()
        == 2
    )


def test_activate_archive_seulement_meme_scope():
    """activate() d'un PAR n'archive QUE l'ancien PAR de meme zone : le PAN
    et le ZAR actifs restent intacts."""
    pan = _make_tree(name="pan", status=DecisionTree.STATUS_ACTIVE)
    zar = _make_tree(
        name="zar",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_ZAR,
        region_code="44",
        activation_map=_make_zar_map(),
    )
    ancien_par = _make_tree(
        name="ancien_par",
        status=DecisionTree.STATUS_ACTIVE,
        scope=DecisionTree.SCOPE_REGION,
        region_code="44",
    )
    nouveau_par = _make_tree(
        name="nouveau_par",
        status=DecisionTree.STATUS_DRAFT,
        scope=DecisionTree.SCOPE_REGION,
        region_code="44",
    )

    nouveau_par.activate()

    pan.refresh_from_db()
    zar.refresh_from_db()
    ancien_par.refresh_from_db()
    nouveau_par.refresh_from_db()

    assert pan.status == DecisionTree.STATUS_ACTIVE  # intact
    assert zar.status == DecisionTree.STATUS_ACTIVE  # intact
    assert ancien_par.status == DecisionTree.STATUS_ARCHIVE  # archive
    assert nouveau_par.status == DecisionTree.STATUS_ACTIVE
