"""Tests du mapping commune INSEE -> zones Est 1 / Est 2 (PAR7 Grand Est)
+ idempotence de la commande de provisioning depuis l'Excel juriste."""

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from envergo.nitrates.zonage_zones_est import (
    _CSV_PATH,
    _mapping,
    est_zone_grand_est_1,
    est_zone_grand_est_2,
)

# ─── Mapping CSV ────────────────────────────────────────────────────────


def test_csv_genere_present_et_charge():
    """Le CSV provisionne est committe et chargeable."""
    assert _CSV_PATH.exists()
    mapping = _mapping()
    assert set(mapping) == {"est_1", "est_2"}


def test_est_1_compte_720_communes_et_3_departements():
    """Annexe 1 : 720 communes listees (08/51/52/57) + depts 54/55/88 entiers."""
    est_1 = _mapping()["est_1"]
    assert len(est_1["communes"]) == 720
    assert est_1["departements"] == frozenset({"54", "55", "88"})


def test_est_2_quatre_departements_aucune_commune():
    """Est 2 (vigne) : 4 departements entiers, pas d'annexe commune."""
    est_2 = _mapping()["est_2"]
    assert est_2["communes"] == frozenset()
    assert est_2["departements"] == frozenset({"08", "10", "51", "52"})


# ─── Zone Est 1 (mais / prairies / luzerne) ─────────────────────────────


def test_commune_listee_est_1():
    # Baâlons (08041), listee explicitement en Annexe 1.
    assert est_zone_grand_est_1("08041") is True


def test_commune_dept_57_listee_est_1():
    # Une commune de Moselle (57) figurant dans l'annexe.
    est_1 = _mapping()["est_1"]
    code_57 = next(c for c in est_1["communes"] if c.startswith("57"))
    assert est_zone_grand_est_1(code_57) is True


def test_departement_entier_est_1():
    # Meurthe-et-Moselle (54) : tout le departement -> n'importe quelle 54xxx.
    assert est_zone_grand_est_1("54395") is True
    # Vosges (88) et Meuse (55) aussi.
    assert est_zone_grand_est_1("88001") is True
    assert est_zone_grand_est_1("55001") is True


def test_commune_dept_08_non_listee_pas_est_1():
    # Les Ardennes (08) ne sont PAS un dept entier en Est 1 : une commune 08
    # absente de l'annexe ne doit pas matcher.
    est_1 = _mapping()["est_1"]
    assert "08999" not in est_1["communes"]
    assert est_zone_grand_est_1("08999") is False


def test_hors_zone_est_1():
    # Paris (75056), hors perimetre Grand Est.
    assert est_zone_grand_est_1("75056") is False


# ─── Zone Est 2 (vigne) ─────────────────────────────────────────────────


def test_departement_entier_est_2():
    # Aube (10) : tout le departement en Est 2 (vigne).
    assert est_zone_grand_est_2("10001") is True
    # Ardennes / Marne / Haute-Marne aussi.
    assert est_zone_grand_est_2("08999") is True
    assert est_zone_grand_est_2("51001") is True
    assert est_zone_grand_est_2("52001") is True


def test_dept_57_pas_est_2():
    # Moselle (57) est en Est 1 mais PAS en Est 2.
    assert est_zone_grand_est_2("57001") is False


def test_aube_10_pas_est_1_mais_est_2():
    """L'Aube (10) est volontairement absente d'Est 1, presente en Est 2."""
    assert est_zone_grand_est_1("10001") is False
    assert est_zone_grand_est_2("10001") is True


def test_recouvrement_08_51_52():
    """08/51/52 peuvent etre Est 1 (commune listee) ET Est 2 (dept vigne)."""
    # Baâlons 08041 : listee Est 1, et 08 est dept entier Est 2.
    assert est_zone_grand_est_1("08041") is True
    assert est_zone_grand_est_2("08041") is True


# ─── Robustesse ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("code", [None, "", "   "])
def test_code_vide_renvoie_false(code):
    assert est_zone_grand_est_1(code) is False
    assert est_zone_grand_est_2(code) is False


# ─── Commande de provisioning ───────────────────────────────────────────


def test_provision_check_passe_sur_csv_committe():
    """--check ne doit pas lever : le CSV committe est aligne sur l'Excel."""
    out = StringIO()
    call_command("provision_zones_est", "--check", stdout=out)
    assert "a jour" in out.getvalue()


def test_provision_idempotent(tmp_path, monkeypatch):
    """Deux runs successifs produisent un CSV byte-identique."""
    import envergo.nitrates.management.commands.provision_zones_est as cmd_mod

    target = tmp_path / "out.csv"
    monkeypatch.setattr(cmd_mod, "CSV_PATH", target)

    call_command("provision_zones_est")
    first = target.read_bytes()
    call_command("provision_zones_est")
    second = target.read_bytes()
    assert first == second
    # Et identique au CSV committe.
    assert first == Path(_CSV_PATH).read_bytes()


def test_provision_excel_manquant_erreur(tmp_path):
    with pytest.raises(CommandError, match="introuvable"):
        call_command("provision_zones_est", "--file", str(tmp_path / "nope.xlsx"))
