"""Outillage local : seed SIG des bases e2e et scan Nuclei."""

import io
import json
import subprocess

import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.management import CommandError, call_command

from envergo.geodata.models import MAP_TYPES, Department, Map, Zone
from envergo.nitrates.management.commands import nuclei_scan

pytestmark = pytest.mark.django_db


def _run(*args, **kwargs):
    out = io.StringIO()
    call_command(*args, stdout=out, stderr=io.StringIO(), **kwargs)
    return out.getvalue()


# --- seed_geodata_e2e -------------------------------------------------------


def _carte_zv():
    return Map.objects.get(map_type=MAP_TYPES.zv_nitrates)


def test_seed_geodata_e2e_cree_les_8_bassins_et_les_departements():
    out = _run("seed_geodata_e2e")

    zones = Zone.objects.filter(map=_carte_zv())
    assert zones.count() == 8
    assert {z.attributes["CdEuBassin"] for z in zones} == {
        "FRA",
        "FRB1",
        "FRB2",
        "FRC",
        "FRD",
        "FRF",
        "FRG",
        "FRH",
    }
    assert set(
        Department.objects.filter(department__in=["51", "35"]).values_list(
            "department", flat=True
        )
    ) == {"51", "35"}
    assert "8 zone(s) ZV, 2 departement(s)" in out

    # Rejouable : remplace ses propres zones.
    _run("seed_geodata_e2e")
    assert Zone.objects.filter(map=_carte_zv()).count() == 8


def test_seed_geodata_e2e_refuse_d_ecraser_une_vraie_couche():
    carte, _ = Map.objects.get_or_create(
        map_type=MAP_TYPES.zv_nitrates, defaults={"name": "ZV Sandre"}
    )
    boite = Polygon.from_bbox((0, 45, 1, 46))
    boite.srid = 4326
    Zone.objects.create(
        map=carte, geometry=MultiPolygon(boite, srid=4326), attributes={}
    )

    with pytest.raises(CommandError, match="Refus d'ecraser"):
        _run("seed_geodata_e2e")

    _run("seed_geodata_e2e", "--force")
    assert Zone.objects.filter(map=carte).count() == 8


# --- nuclei_scan ------------------------------------------------------------

FINDINGS = [
    {
        "template-id": "tech-detect",
        "info": {"name": "Tech", "severity": "info"},
        "matched-at": "http://t/",
    },
    {
        "templateID": "csp-missing",
        "info": {"name": "CSP", "severity": "high"},
        "host": "http://t/",
    },
]


@pytest.fixture
def nuclei(monkeypatch, tmp_path):
    for var in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(nuclei_scan, "REPORTS_DIR", tmp_path / "reports")
    appels = []

    def faux_run(cmd, **kwargs):
        appels.append(cmd)
        sortie = "\n".join(json.dumps(f) for f in FINDINGS) + "\nnot json\n\n"
        return subprocess.CompletedProcess(cmd, 0, stdout=sortie, stderr="")

    monkeypatch.setattr(nuclei_scan.subprocess, "run", faux_run)
    return appels, tmp_path / "reports"


def test_nuclei_scan_binaire_local_ecrit_le_rapport(nuclei, monkeypatch):
    appels, reports = nuclei
    monkeypatch.setattr(
        nuclei_scan.shutil, "which", lambda b: "/bin/nuclei" if b == "nuclei" else None
    )

    out = _run("nuclei_scan", "--target", "http://t/", "--severity", "high")

    assert appels[0][:5] == ["nuclei", "-target", "http://t/", "-severity", "high"]
    rapport = next(reports.glob("*/report.html")).read_text()
    # Tri par sévérité décroissante : le finding high avant l'info.
    assert rapport.index("csp-missing") < rapport.index("tech-detect")
    assert (reports / "latest").is_symlink()
    assert "2 finding(s)" in out


def test_nuclei_scan_bascule_sur_docker(nuclei, monkeypatch):
    appels, _ = nuclei
    monkeypatch.setattr(nuclei_scan.shutil, "which", lambda b: "/bin/" + b)

    _run("nuclei_scan", "--force-docker")

    assert appels[0][:2] == ["docker", "run"]
    assert nuclei_scan.DOCKER_IMAGE in appels[0]


def test_nuclei_scan_sans_runner(nuclei, monkeypatch):
    monkeypatch.setattr(nuclei_scan.shutil, "which", lambda b: None)
    with pytest.raises(CommandError, match="Ni `nuclei` ni `docker`"):
        _run("nuclei_scan")


def test_nuclei_scan_runner_introuvable_a_l_execution(nuclei, monkeypatch):
    monkeypatch.setattr(nuclei_scan.shutil, "which", lambda b: "/bin/" + b)

    def absent(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(nuclei_scan.subprocess, "run", absent)
    with pytest.raises(CommandError, match="Impossible de lancer le scan"):
        _run("nuclei_scan")


def test_nuclei_scan_interdit_en_ci(nuclei, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(CommandError, match="interdit en CI"):
        _run("nuclei_scan")


def test_nuclei_scan_repli_sans_symlink(nuclei, monkeypatch, tmp_path):
    _, reports = nuclei
    monkeypatch.setattr(nuclei_scan.shutil, "which", lambda b: "/bin/" + b)

    def pas_de_symlink(self, cible):
        raise OSError("symlink interdit")

    monkeypatch.setattr(type(tmp_path), "symlink_to", pas_de_symlink)
    _run("nuclei_scan")

    assert (reports / "latest.txt").read_text()
