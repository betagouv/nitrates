from envergo.nitrates.bassins import BASSIN_NAMES, bassin_name


def test_bassin_name_known_code():
    assert bassin_name("FRH") == "Seine-Normandie"


def test_bassin_name_uses_fallback_when_unknown():
    assert bassin_name("XXX", "fallback nom") == "fallback nom"


def test_bassin_name_default_when_no_fallback():
    assert bassin_name("XXX") == "bassin XXX"


def test_bassin_name_empty_code():
    assert bassin_name("") == "bassin inconnu"
    assert bassin_name(None) == "bassin inconnu"


def test_bassin_name_known_code_ignores_fallback():
    """Le nom officiel prime sur le NomZoneVul du shapefile, qui peut être
    moche (ex: 'rhône-méd2021' tel quel dans la source Sandre)."""
    assert bassin_name("FRD", "rhône-méd2021") == "Rhône-Méditerranée"


def test_all_8_bassins_have_a_name():
    expected = {"FRA", "FRB1", "FRB2", "FRC", "FRD", "FRF", "FRG", "FRH"}
    assert set(BASSIN_NAMES.keys()) == expected
