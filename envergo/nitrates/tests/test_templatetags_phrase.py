"""Tests de `construire_phrase_explicative` (phrase contextuelle "aujourd hui").

Cf. issue #28 -- la phrase doit dire ce qui se passe AUJOURD'HUI, pas
juste decrire la regle dans l'absolu. Cas safe traites ici, regimes
mixtes / phenologiques retombent sur la phrase brute (backlog 2026-05-11
quand on traitera la grammaire des bornes souples).
"""

from datetime import date
from types import SimpleNamespace

import pytest

from envergo.nitrates.templatetags.nitrates_tags import (
    _format_jjmm_long,
    construire_phrase_explicative,
)

pytestmark = pytest.mark.django_db


def _regle(type_, periodes=None):
    return SimpleNamespace(regle_id="t", type=type_, periodes=periodes or [])


def test_format_jjmm_long():
    assert _format_jjmm_long("15/12") == "15 décembre"
    assert _format_jjmm_long("01/07") == "1er juillet"
    assert _format_jjmm_long("31/08") == "31 août"
    # Note 2026-05-12 : un evenement phenologique KNOWN avec date_calendrier
    # dans referentiels.yaml est maintenant resolu vers cette date. Si on
    # veut tester le fallback "chaine brute", il faut un slug inexistant.
    assert _format_jjmm_long("evenement_inexistant") == "evenement_inexistant"


def test_libre_sans_periode():
    r = _regle("libre")
    assert (
        construire_phrase_explicative(r, today=date(2026, 5, 7))
        == "L'épandage est autorisé toute l'année."
    )


def test_non_applicable():
    r = _regle("non_applicable")
    assert (
        construire_phrase_explicative(r, today=date(2026, 5, 7))
        == "La directive nitrates ne s'applique pas."
    )


def test_interdiction_today_hors_periode():
    """Mai = hors fenetre 15/12 -> 15/01 -> phrase 'autorise mais sera interdit'."""
    r = _regle("interdiction", [{"du": "15/12", "au": "15/01"}])
    phrase = construire_phrase_explicative(r, today=date(2026, 5, 7))
    assert phrase == (
        "Aujourd'hui, l'épandage est autorisé. "
        "Il sera interdit du 15 décembre au 15 janvier."
    )


def test_interdiction_today_dans_periode():
    """28 décembre tombe dans 15/12 -> 15/01 -> phrase 'aujourd hui interdit'."""
    r = _regle("interdiction", [{"du": "15/12", "au": "15/01"}])
    phrase = construire_phrase_explicative(r, today=date(2026, 12, 28))
    assert phrase == (
        "Aujourd'hui, l'épandage est interdit. "
        "Cette période d'interdiction court du 15 décembre au 15 janvier."
    )


def test_interdiction_2_periodes_meme_regime():
    """Deux fenetres concatenees avec ' et '."""
    r = _regle(
        "interdiction",
        [{"du": "01/07", "au": "31/08"}, {"du": "15/11", "au": "15/01"}],
    )
    phrase = construire_phrase_explicative(r, today=date(2026, 5, 7))
    assert phrase == (
        "Aujourd'hui, l'épandage est autorisé. "
        "Il sera interdit du 1er juillet au 31 août et du 15 novembre au 15 janvier."
    )


def test_autorisation_sous_condition_today_dans_periode():
    r = _regle("autorisation_sous_condition", [{"du": "15/12", "au": "15/01"}])
    phrase = construire_phrase_explicative(r, today=date(2026, 12, 28))
    assert phrase == (
        "Aujourd'hui, l'épandage est autorisé sous condition. "
        "Régime applicable du 15 décembre au 15 janvier."
    )


def test_plafonnement_today_hors_periode():
    r = _regle("plafonnement", [{"du": "01/02", "au": "31/03"}])
    phrase = construire_phrase_explicative(r, today=date(2026, 5, 7))
    assert phrase == (
        "Aujourd'hui, l'épandage est autorisé. "
        "Il sera plafonné du 1er février au 31 mars."
    )


def test_regimes_mixtes_fallback_brut():
    """Plus d'un regime distinct -> on retombe sur la phrase brute (sans
    contexte 'aujourd hui'). A retravailler quand la grammaire des bornes
    souples sera implementee (backlog 2026-05-11)."""
    r = _regle(
        "interdiction",
        [
            {"du": "01/09", "au": "15/10", "regime": "autorisation_sous_condition"},
            {"du": "15/10", "au": "15/01", "regime": "interdiction"},
        ],
    )
    phrase = construire_phrase_explicative(r, today=date(2026, 5, 7))
    # Format brut : pas de "Aujourd'hui", dates en JJ/MM, chainees.
    assert phrase.startswith("L'épandage est ")
    assert "autorisé sous condition du 01/09 au 15/10" in phrase
    assert "puis" in phrase
    assert "interdit du 15/10 au 15/01" in phrase


def test_phenologique_fallback():
    """Borne phenologique INCONNUE -> fallback brut (libelle generique).
    Note 2026-05-12 : une borne phenologique KNOWN avec date_calendrier
    dans referentiels.yaml est maintenant resolue, donc on teste avec un
    slug inexistant pour valider le fallback brut."""
    r = _regle("interdiction", [{"du": "evenement_inexistant", "au": "15/02"}])
    phrase = construire_phrase_explicative(r, today=date(2026, 5, 7))
    # Le fallback brut filtre les periodes non parsables -> liste vide ->
    # libelle generique "Interdit".
    assert phrase == "Interdit"


def test_regle_none():
    assert construire_phrase_explicative(None, today=date(2026, 5, 7)) == ""
