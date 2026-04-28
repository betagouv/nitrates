"""Tests de la commande import_rpg_cultures (insert / override / fichier)."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from envergo.nitrates.models import RpgCulture

pytestmark = pytest.mark.django_db


def _make_csv(tmp_path, rows):
    """Genere un CSV au format IGN: separateur ';', header de 4 colonnes."""
    p = tmp_path / "ref.csv"
    lines = ["CODE_CULTURE;LIBELLE_CULTURE;CODE_GROUPE_CULTURE;LIBELLE_GROUPE_CULTURE"]
    for r in rows:
        lines.append(";".join(r))
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def test_import_creates_all_rows(tmp_path):
    csv = _make_csv(
        tmp_path,
        [
            ("BTH", "Ble tendre", "1", "Cereales a paille"),
            ("MIS", "Mais grain", "2", "Mais"),
        ],
    )
    call_command("import_rpg_cultures", "--file", str(csv))

    assert RpgCulture.objects.count() == 2
    bth = RpgCulture.objects.get(pk="BTH")
    assert bth.libelle == "Ble tendre"
    assert bth.code_groupe == "1"
    assert bth.libelle_groupe == "Cereales a paille"


def test_import_insert_mode_skips_existing(tmp_path):
    RpgCulture.objects.create(
        code="BTH", libelle="ANCIEN", code_groupe="X", libelle_groupe="X"
    )
    csv = _make_csv(
        tmp_path,
        [
            ("BTH", "Ble tendre", "1", "Cereales a paille"),
            ("MIS", "Mais grain", "2", "Mais"),
        ],
    )
    call_command("import_rpg_cultures", "--file", str(csv), "--mode", "insert")

    bth = RpgCulture.objects.get(pk="BTH")
    # mode insert: pas touche au libelle existant
    assert bth.libelle == "ANCIEN"
    # mais MIS a bien ete cree
    assert RpgCulture.objects.filter(pk="MIS").exists()


def test_import_override_mode_updates_existing(tmp_path):
    RpgCulture.objects.create(
        code="BTH", libelle="ANCIEN", code_groupe="X", libelle_groupe="X"
    )
    csv = _make_csv(tmp_path, [("BTH", "Ble tendre", "1", "Cereales a paille")])
    call_command("import_rpg_cultures", "--file", str(csv), "--mode", "override")

    bth = RpgCulture.objects.get(pk="BTH")
    assert bth.libelle == "Ble tendre"
    assert bth.code_groupe == "1"
    assert bth.libelle_groupe == "Cereales a paille"


def test_import_default_mode_is_insert(tmp_path):
    RpgCulture.objects.create(
        code="BTH", libelle="ANCIEN", code_groupe="", libelle_groupe=""
    )
    csv = _make_csv(tmp_path, [("BTH", "NOUVEAU", "1", "Cereales")])
    call_command("import_rpg_cultures", "--file", str(csv))

    assert RpgCulture.objects.get(pk="BTH").libelle == "ANCIEN"


def test_import_default_csv_is_the_embedded_asset():
    """Sans --file, on utilise REF_CULTURES_GROUPES_CULTURES_2024.csv embarque."""
    call_command("import_rpg_cultures")
    # 144 codes officiels dans le CSV asset 2024
    assert RpgCulture.objects.count() == 144
    # sanity check sur 1 code connu
    assert RpgCulture.objects.filter(pk="BTH").exists()


def test_import_missing_file_raises(tmp_path):
    with pytest.raises(CommandError, match="introuvable"):
        call_command("import_rpg_cultures", "--file", str(tmp_path / "nope.csv"))
