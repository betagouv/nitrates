"""Tests du chemin téléchargement+décompression de `import_nitrates_departments`.

Le réseau est intégralement mocké (monkeypatch de `urlopen`) : on construit un
.zip en mémoire contenant un DEPARTEMENT.shp fabriqué via fiona.
"""

import io
import zipfile

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from envergo.geodata.models import Department
from envergo.nitrates.management.commands import import_nitrates_departments
from envergo.nitrates.tests.test_import_commands import make_department_shp

pytestmark = pytest.mark.django_db


class _FakeResponse:
    def __init__(self, data: bytes):
        self._data = data
        self._offset = 0
        self.headers = {"Content-Length": str(len(data))}

    def read(self, n=-1):
        if n is None or n < 0:
            debut = self._offset
            chunk = self._data[debut:]
        else:
            debut, fin = self._offset, self._offset + n
            chunk = self._data[debut:fin]
        self._offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _zip_of_shp(shp_path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in shp_path.parent.glob(shp_path.stem + ".*"):
            zf.write(p, p.name)
    return buf.getvalue()


def test_telecharge_et_importe_le_departement(tmp_path, monkeypatch):
    shp = tmp_path / "DEPARTEMENT.shp"
    make_department_shp(
        shp,
        [
            (
                "51",
                "POLYGON((775000 6900000, 800000 6900000, 800000 6920000, 775000 6920000, 775000 6900000))",
            )
        ],
    )
    data = _zip_of_shp(shp)
    monkeypatch.setattr(
        import_nitrates_departments, "urlopen", lambda req: _FakeResponse(data)
    )

    call_command(
        "import_nitrates_departments", "--url", "https://example.invalid/dep.zip"
    )
    assert Department.objects.filter(department="51").exists()


def test_plusieurs_shp_departement_prend_le_premier(tmp_path, monkeypatch, capsys):
    shp1 = tmp_path / "a" / "DEPARTEMENT.shp"
    shp2 = tmp_path / "b" / "DEPARTEMENT.shp"
    shp1.parent.mkdir()
    shp2.parent.mkdir()
    make_department_shp(
        shp1,
        [
            (
                "51",
                "POLYGON((775000 6900000, 800000 6900000, 800000 6920000, 775000 6920000, 775000 6900000))",
            )
        ],
    )
    make_department_shp(
        shp2,
        [
            (
                "35",
                "POLYGON((330000 6780000, 360000 6780000, 360000 6800000, 330000 6800000, 330000 6780000))",
            )
        ],
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for sub, shp in (("a", shp1), ("b", shp2)):
            for p in shp.parent.glob(shp.stem + ".*"):
                zf.write(p, f"{sub}/{p.name}")
    monkeypatch.setattr(
        import_nitrates_departments,
        "urlopen",
        lambda req: _FakeResponse(buf.getvalue()),
    )

    call_command(
        "import_nitrates_departments", "--url", "https://example.invalid/dep.zip"
    )
    assert "Plusieurs candidats" in capsys.readouterr().out
    assert Department.objects.count() == 1


def test_archive_sans_departement_shp_echoue(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "rien ici")
    monkeypatch.setattr(
        import_nitrates_departments,
        "urlopen",
        lambda req: _FakeResponse(buf.getvalue()),
    )
    with pytest.raises(CommandError, match="Aucun DEPARTEMENT.shp"):
        call_command(
            "import_nitrates_departments", "--url", "https://example.invalid/dep.zip"
        )
