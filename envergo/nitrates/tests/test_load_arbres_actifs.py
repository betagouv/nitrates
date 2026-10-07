"""Tests de `load_arbres_actifs` (chargement des arbres canoniques en DB,
pour une base neuve : CI, e2e, poste local)."""

import textwrap

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from envergo.nitrates.models import DecisionTree

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _purge_decision_trees():
    DecisionTree.objects.all().delete()


ARBRE_VALIDE_YAML = textwrap.dedent(
    """\
    metadata:
      version: "0.0.1-test"
    arbre:
      noeud:
        type_noeud: "catalogue"
        id: "n_zvn"
        champ: "en_zone_vulnerable"
        source: "sig"
        reference: "zone_vulnerable_nitrates"
        branches:
          - valeur: false
            regle:
              id: "r_hors_zvn"
              type: "non_applicable"
              message: "ZV non concernee."
          - valeur: true
            regle:
              id: "r_en_zvn"
              type: "non_applicable"
              message: "Reglementation nitrates applicable."
    """
)


def _write(dir_, name, text=ARBRE_VALIDE_YAML):
    arbres_dir = dir_ / "arbres_actifs"
    arbres_dir.mkdir(exist_ok=True)
    (arbres_dir / name).write_text(text, encoding="utf-8")


def test_repertoire_introuvable_leve_erreur(tmp_path):
    with pytest.raises(CommandError, match="introuvable"):
        call_command("load_arbres_actifs", "--dir", str(tmp_path))


def test_aucun_fichier_yaml_leve_erreur(tmp_path):
    (tmp_path / "arbres_actifs").mkdir()
    with pytest.raises(CommandError, match="Aucun fichier"):
        call_command("load_arbres_actifs", "--dir", str(tmp_path))


def test_charge_un_arbre_national_en_actif(tmp_path, capsys):
    _write(tmp_path, "national.yaml")
    call_command("load_arbres_actifs", "--dir", str(tmp_path))
    tree = DecisionTree.objects.get(status=DecisionTree.STATUS_ACTIVE)
    assert tree.scope == DecisionTree.SCOPE_NATIONAL
    assert "1 chargé" in capsys.readouterr().out


def test_nom_hors_convention_leve_erreur(tmp_path):
    _write(tmp_path, "bizarre.yaml")
    with pytest.raises(CommandError, match="hors convention"):
        call_command("load_arbres_actifs", "--dir", str(tmp_path))


def test_only_charge_un_seul_fichier(tmp_path):
    _write(tmp_path, "national.yaml")
    _write(tmp_path, "region_44.yaml")
    call_command("load_arbres_actifs", "--dir", str(tmp_path), "--only", "region_44")
    assert DecisionTree.objects.filter(
        scope=DecisionTree.SCOPE_REGION, region_code="44"
    ).exists()
    assert not DecisionTree.objects.filter(scope=DecisionTree.SCOPE_NATIONAL).exists()


def test_only_fichier_introuvable_leve_erreur(tmp_path):
    (tmp_path / "arbres_actifs").mkdir()
    with pytest.raises(CommandError, match="introuvable"):
        call_command(
            "load_arbres_actifs", "--dir", str(tmp_path), "--only", "region_99"
        )


def test_zar_sans_activation_map_deductible_leve_erreur(tmp_path):
    _write(tmp_path, "zar_08.yaml")
    with pytest.raises(CommandError, match="activation_map déductible"):
        call_command("load_arbres_actifs", "--dir", str(tmp_path))


def test_zar_sans_activation_map_est_skip_avec_option(tmp_path, capsys):
    _write(tmp_path, "zar_08.yaml")
    call_command("load_arbres_actifs", "--dir", str(tmp_path), "--skip-zar-sans-carte")
    out = capsys.readouterr().out
    assert "skip — ZAR sans activation_map" in out
    assert not DecisionTree.objects.filter(scope=DecisionTree.SCOPE_ZAR).exists()


def test_skip_si_identique_ne_recree_pas_de_version(tmp_path, capsys):
    """Le fichier canonique doit être celui dumpé depuis l'actif (même ordre
    de clés) pour que la comparaison `--skip-si-identique` matche : un YAML
    écrit à la main, même sémantiquement identique, a un ordre de clés
    différent de celui stocké par `import_decision_tree` et ne « matche »
    donc pas tel quel. On repart du dump canonique, comme le ferait le
    GitOps réel (dump_active_trees -> commit -> reload)."""
    _write(tmp_path, "national.yaml")
    call_command("load_arbres_actifs", "--dir", str(tmp_path))
    assert DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE).count() == 1

    capsys.readouterr()
    call_command("dump_active_trees", "--dir", str(tmp_path))

    call_command("load_arbres_actifs", "--dir", str(tmp_path), "--skip-si-identique")
    out = capsys.readouterr().out
    assert "skip — identique à l'actif" in out, out
    # Toujours un seul actif, pas de doublon de version.
    assert DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE).count() == 1
