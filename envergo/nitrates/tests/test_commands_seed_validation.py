"""Seeds du dashboard de validation et export des manifestes de capture.

Les seeds énumèrent les feuilles des arbres canoniques (PAN, PAR et ZAR
Grand Est) et créent une `BrancheValidation` par feuille ; les exports
produisent le manifeste JSON que lisent les specs Playwright `capture_*`.
On les joue sur les vrais arbres de `specs/arbres_actifs/` : c'est leur
seul usage, et c'est ce qui casse quand la grammaire évolue.
"""

import io
import json
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command

from envergo.geodata.tests.factories import MapFactory
from envergo.nitrates.models import BrancheValidation, DecisionTree

pytestmark = pytest.mark.django_db

ARBRES = Path(settings.NITRATES_SPECS_DIR) / "arbres_actifs"


def _run(*args, **kwargs):
    out = io.StringIO()
    call_command(*args, stdout=out, stderr=io.StringIO(), **kwargs)
    return out.getvalue()


@pytest.fixture
def arbre_national():
    _run(
        "import_decision_tree",
        str(ARBRES / "national.yaml"),
        mode="force-active",
        name="arbre_decision_national",
    )


@pytest.fixture
def arbre_par_ge():
    _run(
        "import_decision_tree",
        str(ARBRES / "region_44.yaml"),
        mode="force-active",
        scope=DecisionTree.SCOPE_REGION,
        region_code="44",
        name="PAR Grand Est",
    )


@pytest.fixture
def arbre_zar_ge():
    carte = MapFactory(name="ZAR Grand Est")
    _run(
        "import_decision_tree",
        str(ARBRES / "zar_44.yaml"),
        mode="force-active",
        scope=DecisionTree.SCOPE_ZAR,
        region_code="44",
        activation_map=str(carte.pk),
        name="ZAR Grand Est",
    )


def _lignes(**filtre):
    return BrancheValidation.objects.filter(**filtre)


# --- seeds -------------------------------------------------------------------


def test_seed_culture_principale_pan(arbre_national):
    out = _run("seed_branches_validation")

    lignes = _lignes(scope=BrancheValidation.SCOPE_NATIONAL)
    assert lignes.exists()
    assert all(b.url_simulateur for b in lignes), [
        b.chemin_yaml for b in lignes if not b.url_simulateur
    ][:3]
    assert any(b.yaml_snapshot for b in lignes)
    assert "q_couvert_sous_culture" not in "".join(b.chemin_yaml for b in lignes)
    assert out


def test_seed_culture_principale_pan_idempotent_et_preserve_la_saisie(
    arbre_national,
):
    _run("seed_branches_validation")
    nb = _lignes().count()
    b = _lignes().first()
    b.statut = "valide"
    b.note_verif = "vu"
    b.save()

    _run("seed_branches_validation")

    assert _lignes().count() == nb
    b.refresh_from_db()
    assert (b.statut, b.note_verif) == ("valide", "vu")


def test_seed_culture_principale_pan_dry_run_et_reset(arbre_national):
    _run("seed_branches_validation", "--dry-run")
    assert not _lignes().exists()

    _run("seed_branches_validation")
    BrancheValidation.objects.create(chemin_yaml="obsolete/feuille")
    _run("seed_branches_validation", "--reset")
    assert not _lignes(chemin_yaml="obsolete/feuille").exists()


def test_seed_couvert_pan(arbre_national):
    _run("seed_branches_validation_couvert")

    lignes = _lignes(nature=BrancheValidation.NATURE_COUVERT)
    assert lignes.exists()
    assert all("q_couvert_sous_culture" in b.chemin_yaml for b in lignes)
    # Saisie manuelle laissée vide par construction.
    assert not any(b.resultat_miro or b.miro_widget_id for b in lignes)


def test_seed_couvert_pan_dry_run(arbre_national):
    _run("seed_branches_validation_couvert", "--dry-run")
    assert not _lignes().exists()


def test_seed_par_ge(arbre_national, arbre_par_ge):
    _run("seed_branches_validation_couvert")
    nb_pan = _lignes(scope=BrancheValidation.SCOPE_NATIONAL).count()

    _run("seed_branches_validation_par_ge")

    par = _lignes(scope=BrancheValidation.SCOPE_PAR_GRAND_EST)
    assert par.filter(nature=BrancheValidation.NATURE_CULTURE_PRINCIPALE).exists()
    assert par.filter(nature=BrancheValidation.NATURE_COUVERT).exists()
    assert _lignes(scope=BrancheValidation.SCOPE_NATIONAL).count() == nb_pan

    _run("seed_branches_validation_par_ge", "--reset")
    assert _lignes(scope=BrancheValidation.SCOPE_NATIONAL).count() == nb_pan


def test_seed_par_ge_sans_arbre_par():
    with pytest.raises(RuntimeError, match="PAR"):
        _run("seed_branches_validation_par_ge")


def test_seed_zar_ge(arbre_zar_ge):
    _run("seed_branches_validation_zar_ge")

    zar = _lignes(scope=BrancheValidation.SCOPE_ZAR_GRAND_EST)
    assert zar.exists()
    assert not _lignes().exclude(scope=BrancheValidation.SCOPE_ZAR_GRAND_EST).exists()

    nb = zar.count()
    _run("seed_branches_validation_zar_ge")
    assert zar.count() == nb


# --- export des manifestes de capture ---------------------------------------


def test_export_manifeste_couvert(arbre_national, tmp_path):
    _run("seed_branches_validation_couvert")
    sortie = tmp_path / "out" / "manifeste.json"

    out = _run("export_manifeste_capture_couvert", "--out", str(sortie))

    manifeste = json.loads(sortie.read_text())
    assert len(manifeste) == _lignes(nature=BrancheValidation.NATURE_COUVERT).count()
    entree = manifeste[0]
    assert set(entree) == {"pk", "regle_id", "url", "qc"}
    assert all(isinstance(v, str) for v in entree["qc"].values())
    assert f"{len(manifeste)} feuilles" in out


def test_export_manifeste_couvert_signale_les_feuilles_non_seedees(
    arbre_national, tmp_path
):
    sortie = tmp_path / "m.json"
    out = _run(
        "export_manifeste_capture_couvert", "--out", str(sortie), "--only-courte"
    )
    assert json.loads(sortie.read_text()) == []
    assert "sans BrancheValidation" in out


def test_export_manifeste_par_ge(arbre_national, arbre_par_ge, tmp_path):
    _run("seed_branches_validation_par_ge")
    sortie = tmp_path / "par.json"

    _run("export_manifeste_capture_par_ge", "--out", str(sortie))

    manifeste = json.loads(sortie.read_text())
    assert (
        len(manifeste) == _lignes(scope=BrancheValidation.SCOPE_PAR_GRAND_EST).count()
    )
    assert {"pk", "regle_id", "url", "qc", "yaml_url"} <= set(manifeste[0])
    par = DecisionTree.objects.get(name="PAR Grand Est", status="active")
    assert f"tree_id={par.pk}" in manifeste[0]["yaml_url"]


def test_export_manifeste_zar_ge(arbre_zar_ge, tmp_path):
    _run("seed_branches_validation_zar_ge")
    sortie = tmp_path / "zar.json"

    _run("export_manifeste_capture_zar", "--out", str(sortie))

    manifeste = json.loads(sortie.read_text())
    assert (
        len(manifeste) == _lignes(scope=BrancheValidation.SCOPE_ZAR_GRAND_EST).count()
    )
    zar = DecisionTree.objects.get(name="ZAR Grand Est", status="active")
    assert {e["tree_id"] for e in manifeste} == {zar.pk}
    assert all(e["qc"].get("en_zar") == "True" for e in manifeste)


@pytest.mark.parametrize(
    "commande", ["export_manifeste_capture_zar", "export_manifeste_capture_par_ge"]
)
def test_export_manifeste_sans_arbre_regional(commande, tmp_path):
    with pytest.raises((CommandError, RuntimeError)):
        _run(commande, "--out", str(tmp_path / "x.json"))
