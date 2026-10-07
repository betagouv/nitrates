"""Couverture de envergo/nitrates/models_retour.py : __str__ et a_email."""

from datetime import datetime

import pytest
from django.utils import timezone

from envergo.nitrates.models_retour import RetourUtilisateur

pytestmark = pytest.mark.django_db


def _retour(**kwargs):
    defaults = {"cree_le": timezone.make_aware(datetime(2026, 10, 7, 12, 0))}
    defaults.update(kwargs)
    return RetourUtilisateur(**defaults)


def test_str_feedback_avec_note():
    r = _retour(type=RetourUtilisateur.Type.FEEDBACK, note=4)
    assert "Feedback 4/5" in str(r)
    assert "2026-10-07 12:00" in str(r)


def test_str_feedback_sans_note():
    r = _retour(type=RetourUtilisateur.Type.FEEDBACK, note=None)
    assert "Feedback ?/5" in str(r)


def test_str_bug_avec_commentaire():
    r = _retour(type=RetourUtilisateur.Type.BUG, commentaire="Le bouton ne marche pas")
    assert "Bug/retour « Le bouton ne marche pas »" in str(r)


def test_str_bug_sans_commentaire():
    r = _retour(type=RetourUtilisateur.Type.BUG, commentaire="")
    assert "(sans texte)" in str(r)


def test_str_bug_commentaire_tronque_a_40():
    long_texte = "x" * 100
    r = _retour(type=RetourUtilisateur.Type.BUG, commentaire=long_texte)
    s = str(r)
    assert ("x" * 40) in s
    assert ("x" * 41) not in s


def test_str_interet_region_avec_code():
    r = _retour(type=RetourUtilisateur.Type.INTERET_REGION, region_code="44")
    assert "Intérêt région 44" in str(r)


def test_str_interet_region_sans_code():
    r = _retour(type=RetourUtilisateur.Type.INTERET_REGION, region_code="")
    assert "Intérêt région ?" in str(r)


def test_a_email_true_si_email_rempli():
    assert _retour(email="x@y.fr").a_email is True


def test_a_email_false_si_vide():
    assert _retour(email="").a_email is False
