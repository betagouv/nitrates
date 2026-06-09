"""Tests de la commande management `import_decision_tree`."""

import textwrap

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from envergo.nitrates.models import DecisionTree

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _purge_decision_trees():
    """La migration data 0004 cree un DecisionTree au 1er migrate. On
    purge avant chaque test pour partir d'une table vide."""
    DecisionTree.objects.all().delete()


# Arbre minimal valide qui passe le validateur (1 noeud catalogue + 1 regle).
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


# Manque "arbre" -> validation echoue
ARBRE_INVALIDE_YAML = textwrap.dedent(
    """\
    metadata:
      version: "broken"
    """
)


@pytest.fixture
def yaml_valide(tmp_path, settings):
    settings.NITRATES_SPECS_DIR = str(tmp_path)
    path = tmp_path / "arbre.yaml"
    path.write_text(ARBRE_VALIDE_YAML, encoding="utf-8")
    return path


@pytest.fixture
def yaml_invalide(tmp_path, settings):
    settings.NITRATES_SPECS_DIR = str(tmp_path)
    path = tmp_path / "arbre.yaml"
    path.write_text(ARBRE_INVALIDE_YAML, encoding="utf-8")
    return path


# ─── Mode auto ────────────────────────────────────────────────────────────


def test_mode_auto_table_vide_cree_actif(yaml_valide):
    call_command("import_decision_tree", str(yaml_valide), "--mode", "auto")
    tree = DecisionTree.objects.get()
    assert tree.status == DecisionTree.STATUS_ACTIVE
    assert tree.activated_at is not None
    assert tree.contenu["arbre"]["noeud"]["id"] == "n_zvn"
    assert tree.contenu_yaml_brut.startswith("metadata:")


def test_mode_auto_table_non_vide_cree_draft(yaml_valide):
    DecisionTree.objects.create(
        name="existant",
        status=DecisionTree.STATUS_ACTIVE,
        contenu={},
        contenu_yaml_brut="",
    )
    call_command("import_decision_tree", str(yaml_valide), "--mode", "auto")
    drafts = DecisionTree.objects.filter(status=DecisionTree.STATUS_DRAFT)
    assert drafts.count() == 1
    assert drafts.first().parent is not None  # parent = actif courant
    # L'actif n'a pas change
    assert DecisionTree.objects.filter(status=DecisionTree.STATUS_ACTIVE).count() == 1


# ─── Mode draft ────────────────────────────────────────────────────────────


def test_mode_draft_sans_actif_echoue(yaml_valide):
    with pytest.raises(CommandError, match="Pas d'arbre actif"):
        call_command("import_decision_tree", str(yaml_valide), "--mode", "draft")
    assert not DecisionTree.objects.exists()


def test_mode_draft_avec_actif_cree_draft(yaml_valide):
    actif = DecisionTree.objects.create(
        name="existant",
        status=DecisionTree.STATUS_ACTIVE,
        contenu={},
        contenu_yaml_brut="",
    )
    call_command("import_decision_tree", str(yaml_valide), "--mode", "draft")
    drafts = DecisionTree.objects.filter(status=DecisionTree.STATUS_DRAFT)
    assert drafts.count() == 1
    assert drafts.first().parent_id == actif.pk


# ─── Mode force-active ─────────────────────────────────────────────────────


def test_mode_force_active_archive_actif_courant(yaml_valide):
    actif = DecisionTree.objects.create(
        name="ancien",
        status=DecisionTree.STATUS_ACTIVE,
        contenu={},
        contenu_yaml_brut="",
    )
    call_command("import_decision_tree", str(yaml_valide), "--mode", "force-active")
    actif.refresh_from_db()
    assert actif.status == DecisionTree.STATUS_ARCHIVE
    nouveau = DecisionTree.objects.get(status=DecisionTree.STATUS_ACTIVE)
    assert nouveau.activated_at is not None


def test_mode_force_active_table_vide(yaml_valide):
    """force-active sur table vide : devient simplement actif."""
    call_command("import_decision_tree", str(yaml_valide), "--mode", "force-active")
    tree = DecisionTree.objects.get()
    assert tree.status == DecisionTree.STATUS_ACTIVE


# ─── Erreurs ───────────────────────────────────────────────────────────────


def test_yaml_invalide_n_ecrit_rien(yaml_invalide):
    with pytest.raises(CommandError, match="invalide"):
        call_command("import_decision_tree", str(yaml_invalide), "--mode", "auto")
    assert not DecisionTree.objects.exists()


def test_fichier_introuvable_echoue(tmp_path, settings):
    settings.NITRATES_SPECS_DIR = str(tmp_path)
    inexistant = tmp_path / "nope.yaml"
    with pytest.raises(CommandError, match="introuvable"):
        call_command("import_decision_tree", str(inexistant), "--mode", "auto")
    assert not DecisionTree.objects.exists()


# ─── Option --name ─────────────────────────────────────────────────────────


def test_name_personnalise(yaml_valide):
    call_command(
        "import_decision_tree",
        str(yaml_valide),
        "--mode",
        "auto",
        "--name",
        "pan_test_2026",
    )
    tree = DecisionTree.objects.get()
    assert tree.name == "pan_test_2026"
