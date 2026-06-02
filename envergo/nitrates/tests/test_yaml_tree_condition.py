"""Tests du parser/validateur du mini-DSL `condition` sur les periodes
calculatrice (cf. spec_extension_grammaire_condition)."""

import pytest

from envergo.nitrates.yaml_tree.condition import (
    Condition,
    ConditionParseError,
    parse_condition,
    validate_condition,
)

# ─── parse_condition ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("date_x < 05/12", Condition("date_x", "<", "05/12")),
        ("date_x<=05/12", Condition("date_x", "<=", "05/12")),
        ("  date_x  >=  31/12  ", Condition("date_x", ">=", "31/12")),
        ("a == 01/01", Condition("a", "==", "01/01")),
        ("a_b_c != 15/08", Condition("a_b_c", "!=", "15/08")),
        (
            "date_destruction_couvert > 30/06",
            Condition("date_destruction_couvert", ">", "30/06"),
        ),
    ],
)
def test_parse_condition_valides(raw, expected):
    assert parse_condition(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "date_x 05/12",  # operateur manquant
        "date_x ~ 05/12",  # operateur inconnu
        "Date < 05/12",  # majuscule au debut de l'id
        "1date < 05/12",  # chiffre au debut
        "date < 5/12",  # date sans 0 leading
        "date < 05",  # date incomplete
        "date < 05/12 extra",  # tokens en trop
    ],
)
def test_parse_condition_invalides(raw):
    with pytest.raises(ConditionParseError):
        parse_condition(raw)


def test_parse_condition_priorite_op_2chars():
    """`<=` doit etre matche avant `<` (idem pour `>=`)."""
    cond = parse_condition("date_x <= 05/12")
    assert cond.op == "<="
    cond = parse_condition("date_x >= 05/12")
    assert cond.op == ">="


def test_condition_normalise_format_canonique():
    """normalise() produit une forme stable peu importe l'espacement."""
    a = parse_condition("date_x<=05/12")
    b = parse_condition("  date_x <=    05/12   ")
    assert a.normalise() == b.normalise() == "date_x <= 05/12"


# ─── validate_condition ────────────────────────────────────────────────────


def _inputs_date():
    return [
        {"id": "date_semis", "label": "Semis", "type": "date"},
        {"id": "date_destruction", "label": "Destruction", "type": "date"},
    ]


def test_validate_condition_valide():
    cond, err = validate_condition("date_semis >= 01/09", _inputs_date())
    assert err is None
    assert cond.input_id == "date_semis"
    assert cond.op == ">="
    assert cond.date_litterale == "01/09"


def test_validate_condition_input_inconnu():
    cond, err = validate_condition("date_inconnu < 05/12", _inputs_date())
    assert cond is None
    assert "date_inconnu" in err
    assert "inputs_requis" in err


def test_validate_condition_input_type_non_date():
    inputs = [{"id": "foo", "label": "Foo", "type": "texte"}]
    cond, err = validate_condition("foo < 05/12", inputs)
    assert cond is None
    assert "date" in err


def test_validate_condition_date_jour_invalide():
    cond, err = validate_condition("date_semis < 99/12", _inputs_date())
    assert cond is None
    assert "99/12" in err


def test_validate_condition_mois_invalide():
    cond, err = validate_condition("date_semis < 15/13", _inputs_date())
    assert cond is None


def test_validate_condition_format_invalide():
    cond, err = validate_condition("totalement faux", _inputs_date())
    assert cond is None
    assert "format" in err or "operateurs" in err


def test_validate_condition_inputs_vide():
    cond, err = validate_condition("date_x < 05/12", [])
    assert cond is None
    assert "date_x" in err
