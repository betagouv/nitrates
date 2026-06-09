"""Tests du parser/validateur du mini-DSL `condition` sur les periodes
calculatrice (cf. spec_extension_grammaire_condition)."""

import pytest

from envergo.nitrates.yaml_tree.condition import (
    ConditionParseError,
    parse_condition,
    parse_condition_expr,
    validate_condition,
)

# ─── parse_condition : forme historique (event < date) ──────────────────────


@pytest.mark.parametrize(
    "raw,g_event,op,d_date",
    [
        ("date_x < 05/12", "date_x", "<", "05/12"),
        ("date_x<=05/12", "date_x", "<=", "05/12"),
        ("  date_x  >=  31/12  ", "date_x", ">=", "31/12"),
        ("a == 01/01", "a", "==", "01/01"),
        ("a_b_c != 15/08", "a_b_c", "!=", "15/08"),
        ("date_destruction_couvert > 30/06", "date_destruction_couvert", ">", "30/06"),
    ],
)
def test_parse_condition_event_vs_date(raw, g_event, op, d_date):
    c = parse_condition(raw)
    assert c.gauche.is_event and c.gauche.event == g_event
    assert c.op == op
    assert c.droite.is_date and c.droite.date == d_date


# ─── parse_condition : nouvelle grammaire (terme±offset des 2 cotes) ─────────


def test_parse_condition_event_offset_gauche():
    """date_semis_couvert+4semaines > 15/12 : event+offset a gauche, date a droite."""
    c = parse_condition("date_semis_couvert+4semaines > 15/12")
    assert c.gauche.is_event
    assert c.gauche.event == "date_semis_couvert"
    assert c.gauche.sign == "+" and c.gauche.n == 4 and c.gauche.unit == "semaines"
    assert c.op == ">"
    assert c.droite.is_date and c.droite.date == "15/12"


def test_parse_condition_event_offset_negatif():
    """date_destruction_couvert-20jours < 15/01."""
    c = parse_condition("date_destruction_couvert-20jours < 15/01")
    assert c.gauche.event == "date_destruction_couvert"
    assert c.gauche.sign == "-" and c.gauche.n == 20 and c.gauche.unit == "jours"
    assert c.op == "<"
    assert c.droite.is_date and c.droite.date == "15/01"


def test_parse_condition_date_a_gauche():
    """15/12 <= date_destruction_couvert : date a gauche, event a droite."""
    c = parse_condition("15/12 <= date_destruction_couvert")
    assert c.gauche.is_date and c.gauche.date == "15/12"
    assert c.op == "<="
    assert c.droite.is_event and c.droite.event == "date_destruction_couvert"


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


# ─── validate_condition : nouvelle grammaire ────────────────────────────────


def test_validate_condition_event_offset_valide():
    cond, err = validate_condition("date_semis+4semaines > 15/12", _inputs_date())
    assert err is None
    assert cond.gauche.event == "date_semis"
    assert cond.gauche.n == 4 and cond.gauche.unit == "semaines"
    assert cond.droite.date == "15/12"


def test_validate_condition_event_offset_negatif_valide():
    cond, err = validate_condition("date_destruction-20jours < 15/01", _inputs_date())
    assert err is None
    assert cond.gauche.event == "date_destruction"
    assert cond.gauche.sign == "-" and cond.gauche.n == 20


def test_validate_condition_date_a_gauche_valide():
    cond, err = validate_condition("15/12 <= date_destruction", _inputs_date())
    assert err is None
    assert cond.gauche.date == "15/12"
    assert cond.droite.event == "date_destruction"


def test_validate_condition_deux_dates_fixes_rejete():
    """Comparer deux dates fixes = condition constante -> rejete."""
    cond, err = validate_condition("15/12 < 15/01", _inputs_date())
    assert cond is None
    assert "event" in err


def test_validate_condition_offset_event_inconnu():
    cond, err = validate_condition("date_inconnu+4semaines > 15/12", _inputs_date())
    assert cond is None
    assert "date_inconnu" in err


def test_validate_condition_normalise_offset():
    """normalise() preserve l'offset des 2 cotes."""
    c = parse_condition("date_semis+4semaines>15/12")
    assert c.normalise() == "date_semis+4semaines > 15/12"


# ─── conjonction `&&` (ET) ──────────────────────────────────────────────────


def test_parse_condition_expr_simple_une_comparaison():
    """Sans &&, une seule comparaison ; les proprietes de compat delèguent."""
    expr = parse_condition_expr("date_x < 05/12")
    assert len(expr.comparaisons) == 1
    assert expr.input_id == "date_x"
    assert expr.op == "<"
    assert expr.date_litterale == "05/12"


def test_parse_condition_expr_deux_comparaisons():
    expr = parse_condition_expr("date_semis > 15/09 && date_semis < 15/11")
    assert len(expr.comparaisons) == 2
    c1, c2 = expr.comparaisons
    assert (
        c1.gauche.event == "date_semis" and c1.op == ">" and c1.droite.date == "15/09"
    )
    assert (
        c2.gauche.event == "date_semis" and c2.op == "<" and c2.droite.date == "15/11"
    )


def test_parse_condition_expr_normalise():
    """normalise() reassemble les comparaisons avec ' && ' canonique."""
    expr = parse_condition_expr("date_x<05/12&&date_y>=01/01")
    assert expr.normalise() == "date_x < 05/12 && date_y >= 01/01"


@pytest.mark.parametrize(
    "raw",
    [
        "date_x < 05/12 && ",  # part droite vide
        " && date_x < 05/12",  # part gauche vide
        "date_x < 05/12 && && date_y > 01/01",  # part du milieu vide
        "date_x < 05/12 && pas une comparaison",  # 2e part mal formee
    ],
)
def test_parse_condition_expr_invalides(raw):
    with pytest.raises(ConditionParseError):
        parse_condition_expr(raw)


def test_validate_condition_et_valide():
    expr, err = validate_condition(
        "date_semis > 15/09 && date_semis < 15/11", _inputs_date()
    )
    assert err is None
    assert len(expr.comparaisons) == 2


def test_validate_condition_et_part_event_inconnu():
    """Une part reference un input absent -> tout est rejete."""
    expr, err = validate_condition(
        "date_semis > 15/09 && date_inconnu < 15/11", _inputs_date()
    )
    assert expr is None
    assert "date_inconnu" in err


def test_validate_condition_et_part_constante_rejetee():
    """Une part comparant deux dates fixes (constante) -> rejete, meme si les
    autres parts sont valides."""
    expr, err = validate_condition(
        "date_semis > 15/09 && 15/12 < 31/01", _inputs_date()
    )
    assert expr is None
    assert "event" in err


def test_validate_condition_et_mix_offset():
    expr, err = validate_condition(
        "date_semis+4semaines > 15/12 && date_destruction-20jours < 15/01",
        _inputs_date(),
    )
    assert err is None
    assert len(expr.comparaisons) == 2
    assert expr.comparaisons[0].gauche.n == 4
    assert expr.comparaisons[1].gauche.sign == "-"
