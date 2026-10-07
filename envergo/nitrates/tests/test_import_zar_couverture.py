"""Tests complémentaires de `import_nitrates_zar` : options invalides,
archive embarquée (régions réelles), téléchargement mocké, réparation de
géométrie invalide, bascule avec ancien millésime."""

import io
import zipfile

import fiona
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from fiona.crs import CRS

from envergo.geodata.models import Map
from envergo.nitrates.management.commands import import_nitrates_zar

pytestmark = pytest.mark.django_db

_CARRE_1 = "POLYGON((900000 6900000, 901000 6900000, 901000 6901000, 900000 6901000, 900000 6900000))"
_BOWTIE = (
    "POLYGON((900000 6900000, 900100 6900100, 900100 6900000, "
    "900000 6900100, 900000 6900000))"
)


def _poly(wkt):
    coords = wkt.split("((")[1].rsplit("))", 1)[0]
    pts = [tuple(map(float, p.strip().split())) for p in coords.split(",")]
    return {"type": "Polygon", "coordinates": [pts]}


def make_zar_shapefile(path, features):
    schema = {
        "geometry": "Polygon",
        "properties": {
            "NOMZAR": "str",
            "NOMCOMPL": "str",
            "TYPABRG": "str",
            "CDDEPT": "str",
        },
    }
    with fiona.open(
        str(path), "w", driver="ESRI Shapefile", crs=CRS.from_epsg(2154), schema=schema
    ) as dst:
        for wkt, props in features:
            dst.write({"geometry": _poly(wkt), "properties": props})


def _props(nom):
    return {"NOMZAR": nom, "NOMCOMPL": nom, "TYPABRG": "AAC", "CDDEPT": "08"}


# ─── Options invalides ──────────────────────────────────────────────────────


def test_all_et_region_sont_exclusifs():
    with pytest.raises(CommandError, match="exclusifs"):
        call_command("import_nitrates_zar", "--region", "grand-est", "--all")


def test_ni_all_ni_region_echoue():
    with pytest.raises(CommandError, match="--region"):
        call_command("import_nitrates_zar")


def test_file_avec_all_echoue(tmp_path):
    shp = tmp_path / "zar.shp"
    make_zar_shapefile(shp, [(_CARRE_1, _props("AAC A"))])
    with pytest.raises(CommandError, match="une seule région"):
        call_command("import_nitrates_zar", "--all", "--file", str(shp))


# ─── Archive embarquée (régions réelles, pas de réseau) ────────────────────


def test_import_all_utilise_les_archives_embarquees(capsys):
    call_command("import_nitrates_zar", "--all")
    out = capsys.readouterr().out
    assert "Archive embarquée" in out
    assert Map.objects.filter(name="zar_par7_grand_est").exists()
    assert Map.objects.filter(name="zar_hauts_de_france").exists()


def test_import_region_hdf_cle_naturelle_commune():
    call_command("import_nitrates_zar", "--region", "hauts-de-france")
    m = Map.objects.get(name="zar_hauts_de_france")
    assert m.zones.count() > 0


# ─── Téléchargement mocké (override explicite de --url) ───────────────────


class _FakeResponse:
    def __init__(self, data: bytes):
        self._data = data
        self._offset = 0
        self.headers = {"Content-Length": str(len(data))}

    def read(self, n=-1):
        debut = self._offset
        fin = None if n is None or n < 0 else debut + n
        chunk = self._data[debut:fin]
        self._offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_import_region_url_explicite_bypasse_l_archive_embarquee(
    tmp_path, monkeypatch, capsys
):
    shp = tmp_path / "zar.shp"
    make_zar_shapefile(shp, [(_CARRE_1, _props("AAC Téléchargée"))])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in shp.parent.glob("zar.*"):
            zf.write(p, p.name)

    monkeypatch.setattr(
        import_nitrates_zar, "urlopen", lambda req: _FakeResponse(buf.getvalue())
    )

    call_command(
        "import_nitrates_zar",
        "--region",
        "grand-est",
        "--url",
        "https://example.invalid/zar.zip",
    )
    out = capsys.readouterr().out
    assert "Archive embarquée" not in out
    assert "Téléchargement" in out
    m = Map.objects.get(name="zar_par7_grand_est")
    assert m.zones.first().attributes["NOMZAR"] == "AAC Téléchargée"


def test_import_zip_local_sans_shp_echoue(tmp_path):
    zip_path = tmp_path / "vide.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("readme.txt", "rien ici")
    with pytest.raises(CommandError, match="Aucun .shp"):
        call_command(
            "import_nitrates_zar", "--region", "grand-est", "--file", str(zip_path)
        )


# ─── Réparation de géométrie invalide ──────────────────────────────────────


def test_geometrie_invalide_est_reparee(tmp_path):
    shp = tmp_path / "zar.shp"
    make_zar_shapefile(shp, [(_BOWTIE, _props("AAC Bowtie"))])
    call_command("import_nitrates_zar", "--region", "grand-est", "--file", str(shp))
    m = Map.objects.get(name="zar_par7_grand_est")
    z = m.zones.first()
    assert z.geometry.valid


# ─── Bascule avec ancien millésime ─────────────────────────────────────────


def test_import_desactive_ancien_millesime_et_log(tmp_path, capsys):
    Map.objects.filter(name="zar_par7_grand_est").delete()
    ancienne = Map.objects.create(
        name="zar_par7_grand_est",
        version="2024",
        is_active=True,
    )
    shp = tmp_path / "zar.shp"
    make_zar_shapefile(shp, [(_CARRE_1, _props("AAC A"))])
    call_command(
        "import_nitrates_zar",
        "--region",
        "grand-est",
        "--file",
        str(shp),
        "--millesime",
        "2026",
    )
    ancienne.refresh_from_db()
    assert ancienne.is_active is False
    out = capsys.readouterr().out
    assert "Désactivé" in out


def test_no_activate_laisse_le_millesime_inactif(tmp_path, capsys):
    shp = tmp_path / "zar.shp"
    make_zar_shapefile(shp, [(_CARRE_1, _props("AAC A"))])
    call_command(
        "import_nitrates_zar",
        "--region",
        "grand-est",
        "--file",
        str(shp),
        "--millesime",
        "2099",
        "--no-activate",
    )
    m = Map.objects.get(name="zar_par7_grand_est", version="2099")
    assert m.is_active is False
    assert "--no-activate" in capsys.readouterr().out
