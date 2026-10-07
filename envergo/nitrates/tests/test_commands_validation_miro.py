"""Commandes d'alimentation du dashboard de validation des branches.

Captures Playwright (attach_*, ingest_captures_couvert), crops du board Miro
(ingest_crops_miro_*) et mapping des widgets Miro (ingest_miro_widget_ids*).
Toutes ciblent des `BrancheValidation` par regle_id (ou pk), dans un périmètre
propre à chaque arbre : marqueur de chemin couvert pour le PAN, scope pour les
PAR / ZAR.
"""

import io
import json

import pytest
from django.core.management import CommandError, call_command
from PIL import Image

from envergo.nitrates.models import BrancheValidation

pytestmark = pytest.mark.django_db

CHEMIN_COUVERT = "n_zvn/q_couvert_sous_culture/r_couvert"


@pytest.fixture(autouse=True)
def media_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")


def _png(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(buf, format="PNG")
    path.write_bytes(buf.getvalue())
    return path


def _branche(chemin, regle_id="r_test", **kwargs):
    return BrancheValidation.objects.create(
        chemin_yaml=chemin, regle_id=regle_id, **kwargs
    )


def _run(*args, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    call_command(*args, stdout=out, stderr=err, **kwargs)
    return out.getvalue(), err.getvalue()


# --- attach_validation_screenshot -------------------------------------------


def test_attach_validation_screenshot_playwright_date_le_run(tmp_path):
    b = _branche("a/b")
    png = _png(tmp_path / "capture.png")

    out, _ = _run("attach_validation_screenshot", b.pk, "playwright", str(png))

    b.refresh_from_db()
    assert b.screenshot_playwright.name.endswith(".png")
    assert b.playwright_run_at is not None
    assert f"branche #{b.pk}" in out


def test_attach_validation_screenshot_autre_champ_sans_date(tmp_path):
    b = _branche("a/b")
    png = _png(tmp_path / "miro.png")

    _run("attach_validation_screenshot", b.pk, "miro", str(png))

    b.refresh_from_db()
    assert b.screenshot_miro
    assert b.playwright_run_at is None


def test_attach_validation_screenshot_fichier_absent(tmp_path):
    b = _branche("a/b")
    with pytest.raises(CommandError, match="Fichier introuvable"):
        _run("attach_validation_screenshot", b.pk, "miro", str(tmp_path / "x.png"))


def test_attach_validation_screenshot_branche_absente(tmp_path):
    png = _png(tmp_path / "c.png")
    with pytest.raises(CommandError, match="introuvable"):
        _run("attach_validation_screenshot", 999999, "miro", str(png))


# --- attach_couvert_screenshots ---------------------------------------------


def test_attach_couvert_screenshots_attache_toutes_les_feuilles(tmp_path):
    b1 = _branche(CHEMIN_COUVERT + "/icpe", regle_id="r_couvert")
    b2 = _branche(CHEMIN_COUVERT + "/iaa", regle_id="r_couvert")
    hors_couvert = _branche("n_zvn/q_culture/r_couvert", regle_id="r_couvert")
    _png(tmp_path / "caps" / "r_couvert.png")
    _png(tmp_path / "caps" / "r_orphelin.png")

    out, _ = _run("attach_couvert_screenshots", "playwright", str(tmp_path / "caps"))

    for b in (b1, b2):
        b.refresh_from_db()
        assert b.screenshot_playwright
        assert b.playwright_run_at is not None
    hors_couvert.refresh_from_db()
    assert not hors_couvert.screenshot_playwright
    assert "1 PNG sans feuille couvert" in out
    assert "1 PNG -> 2 feuilles couvert" in out


def test_attach_couvert_screenshots_yaml_viewer_sans_date(tmp_path):
    b = _branche(CHEMIN_COUVERT, regle_id="r_couvert")
    _png(tmp_path / "r_couvert.png")

    _run("attach_couvert_screenshots", "yaml_viewer", str(tmp_path))

    b.refresh_from_db()
    assert b.screenshot_yaml_viewer
    assert b.playwright_run_at is None


def test_attach_couvert_screenshots_dry_run_n_ecrit_rien(tmp_path):
    b = _branche(CHEMIN_COUVERT, regle_id="r_couvert")
    _png(tmp_path / "r_couvert.png")

    out, _ = _run(
        "attach_couvert_screenshots", "playwright", str(tmp_path), "--dry-run"
    )

    b.refresh_from_db()
    assert not b.screenshot_playwright
    assert "[dry-run] r_couvert.png -> 1 feuille(s)" in out
    assert "attacherait" in out


def test_attach_couvert_screenshots_dossier_absent_ou_vide(tmp_path):
    with pytest.raises(CommandError, match="Dossier introuvable"):
        _run("attach_couvert_screenshots", "playwright", str(tmp_path / "nope"))
    with pytest.raises(CommandError, match="Aucun PNG"):
        _run("attach_couvert_screenshots", "playwright", str(tmp_path))


# --- ingest_captures_couvert ------------------------------------------------


def test_ingest_captures_couvert_calendrier_et_yaml(tmp_path):
    b = _branche(CHEMIN_COUVERT)
    _png(tmp_path / f"{b.pk}_calendrier.png")
    _png(tmp_path / f"{b.pk}_yaml.png")
    _png(tmp_path / "999999_calendrier.png")
    (tmp_path / "manifeste.json").write_text("{}")

    out, _ = _run("ingest_captures_couvert", "--dir", str(tmp_path))

    b.refresh_from_db()
    assert b.screenshot_playwright
    assert b.screenshot_yaml_viewer
    assert b.playwright_run_at is not None
    assert "1 calendriers, 1 yaml viewer" in out
    assert "1 pk sans BrancheValidation" in out


def test_ingest_captures_couvert_dry_run(tmp_path):
    b = _branche(CHEMIN_COUVERT)
    _png(tmp_path / f"{b.pk}_yaml.png")

    out, _ = _run("ingest_captures_couvert", "--dir", str(tmp_path), "--dry-run")

    b.refresh_from_db()
    assert not b.screenshot_yaml_viewer
    assert f"[dry-run] pk={b.pk}" in out


def test_ingest_captures_couvert_dossier_absent(tmp_path):
    _, err = _run("ingest_captures_couvert", "--dir", str(tmp_path / "nope"))
    assert "Dossier introuvable" in err


# --- ingest_crops_miro_* ----------------------------------------------------

CROPS = [
    # (commande, kwargs de la branche ciblée, kwargs d'une branche hors périmètre)
    (
        "ingest_crops_miro_couvert",
        {"chemin": CHEMIN_COUVERT},
        {"chemin": "n_zvn/q_culture/r_test"},
    ),
    (
        "ingest_crops_miro_par",
        {"chemin": "par/a", "scope": BrancheValidation.SCOPE_PAR_GRAND_EST},
        {"chemin": "zar/a", "scope": BrancheValidation.SCOPE_ZAR_GRAND_EST},
    ),
    (
        "ingest_crops_miro_zar",
        {"chemin": "zar/a", "scope": BrancheValidation.SCOPE_ZAR_GRAND_EST},
        {"chemin": "par/a", "scope": BrancheValidation.SCOPE_PAR_GRAND_EST},
    ),
]


@pytest.mark.parametrize("commande,cible,hors", CROPS)
def test_ingest_crops_miro_attache_dans_le_perimetre(tmp_path, commande, cible, hors):
    b = _branche(**cible)
    autre = _branche(**hors)
    _png(tmp_path / "r_test.png")
    _png(tmp_path / "r_orphelin.png")

    out, _ = _run(commande, "--dir", str(tmp_path))

    b.refresh_from_db()
    autre.refresh_from_db()
    assert b.screenshot_miro
    assert not autre.screenshot_miro
    assert "1 screenshot_miro attachés (1 regle_id, 1 orphelins)" in out


@pytest.mark.parametrize("commande,cible,hors", CROPS)
def test_ingest_crops_miro_dry_run(tmp_path, commande, cible, hors):
    b = _branche(**cible)
    _png(tmp_path / "r_test.png")

    out, _ = _run(commande, "--dir", str(tmp_path), "--dry-run")

    b.refresh_from_db()
    assert not b.screenshot_miro
    assert f"[dry-run] r_test -> pk={b.pk}" in out


@pytest.mark.parametrize("commande", [c[0] for c in CROPS])
def test_ingest_crops_miro_dossier_absent_ou_vide(tmp_path, commande):
    _, err = _run(commande, "--dir", str(tmp_path / "nope"))
    assert "Dossier introuvable" in err
    _, err = _run(commande, "--dir", str(tmp_path))
    assert "Aucun PNG" in err


# --- ingest_miro_widget_ids* ------------------------------------------------

WIDGETS = [
    ("ingest_miro_widget_ids", {"chemin": CHEMIN_COUVERT}),
    (
        "ingest_miro_widget_ids_par_ge",
        {"chemin": "par/a", "scope": BrancheValidation.SCOPE_PAR_GRAND_EST},
    ),
    (
        "ingest_miro_widget_ids_zar",
        {"chemin": "zar/a", "scope": BrancheValidation.SCOPE_ZAR_GRAND_EST},
    ),
]


def _mapping(tmp_path, **par_regle):
    f = tmp_path / "mapping.json"
    f.write_text(json.dumps(par_regle), encoding="utf-8")
    return str(f)


@pytest.mark.parametrize("commande,cible", WIDGETS)
def test_ingest_widget_ids_remplit_les_champs_vides(tmp_path, commande, cible):
    b = _branche(**cible)
    fichier = _mapping(
        tmp_path,
        r_test={"widget_id": "w1", "resultat": "Interdit", "code_pc": "pc1"},
        r_orphelin={"widget_id": "w2"},
    )

    out, _ = _run(commande, "--file", fichier)

    b.refresh_from_db()
    assert (b.miro_widget_id, b.resultat_miro, b.code_pc_miro) == (
        "w1",
        "Interdit",
        "pc1",
    )
    assert "1 regle_id, 1 orphelins" in out


@pytest.mark.parametrize("commande,cible", WIDGETS)
def test_ingest_widget_ids_preserve_la_saisie_sauf_force(tmp_path, commande, cible):
    b = _branche(**cible, resultat_miro="Reformulé", code_pc_miro="pc_manuel")
    fichier = _mapping(
        tmp_path, r_test={"widget_id": "w1", "resultat": "Brut", "code_pc": "pc1"}
    )

    _run(commande, "--file", fichier)
    b.refresh_from_db()
    assert (b.miro_widget_id, b.resultat_miro, b.code_pc_miro) == (
        "w1",
        "Reformulé",
        "pc_manuel",
    )

    _run(commande, "--file", fichier, "--force")
    b.refresh_from_db()
    assert (b.resultat_miro, b.code_pc_miro) == ("Brut", "pc1")


@pytest.mark.parametrize("commande,cible", WIDGETS)
def test_ingest_widget_ids_dry_run(tmp_path, commande, cible):
    b = _branche(**cible)
    fichier = _mapping(tmp_path, r_test={"widget_id": "w1"})

    out, _ = _run(commande, "--file", fichier, "--dry-run")

    b.refresh_from_db()
    assert b.miro_widget_id == ""
    assert f"[dry-run] r_test pk={b.pk} -> miro_widget_id" in out


@pytest.mark.parametrize("commande", [c[0] for c in WIDGETS])
def test_ingest_widget_ids_mapping_absent(tmp_path, commande):
    _, err = _run(commande, "--file", str(tmp_path / "nope.json"))
    assert "Mapping introuvable" in err
