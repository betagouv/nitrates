"""Tests complémentaires de la commande `millesimes_sig` : purge, erreurs,
et garde-fou « plusieurs millésimes actifs »."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from envergo.geodata.models import MAP_TYPES, Map

pytestmark = pytest.mark.django_db

COUCHE = "zar_test_millesimes_cmd"


def _millesime(version, actif=False):
    return Map.objects.create(
        name=COUCHE,
        version=version,
        map_type=MAP_TYPES.zone_action_renforcee,
        is_active=actif,
        description="x",
    )


def test_commande_purger_supprime_le_millesime(capsys):
    _millesime("2024")
    call_command("millesimes_sig", "--couche", COUCHE, "--purger", "2024")
    assert not Map.objects.filter(name=COUCHE, version="2024").exists()
    assert "supprimé" in capsys.readouterr().out


def test_commande_purger_refuse_le_millesime_actif():
    _millesime("2026", actif=True)
    with pytest.raises(CommandError, match="2026"):
        call_command("millesimes_sig", "--couche", COUCHE, "--purger", "2026")
    assert Map.objects.filter(name=COUCHE, version="2026").exists()


def test_commande_purger_exige_couche():
    with pytest.raises(CommandError, match="--couche"):
        call_command("millesimes_sig", "--purger", "2024")


def test_commande_activer_millesime_inconnu_leve_erreur_explicite():
    _millesime("2024", actif=True)
    with pytest.raises(CommandError, match="inconnu"):
        call_command("millesimes_sig", "--couche", COUCHE, "--activer", "1999")


def test_commande_purger_millesime_inconnu_leve_erreur_explicite():
    with pytest.raises(CommandError, match="inconnu"):
        call_command("millesimes_sig", "--couche", COUCHE, "--purger", "1999")


def test_commande_sans_couche_ni_filtre_liste_tout(capsys):
    _millesime("2024", actif=True)
    call_command("millesimes_sig")
    out = capsys.readouterr().out
    assert COUCHE in out


def test_commande_couche_inexistante_affiche_aucune_couche(capsys):
    call_command("millesimes_sig", "--couche", "couche_qui_n_existe_pas_du_tout")
    assert "Aucune couche" in capsys.readouterr().out


def test_commande_signale_plusieurs_millesimes_actifs(capsys):
    """Garde-fou : deux millésimes actifs simultanés pour la même couche
    (incohérence) doivent être signalés en erreur à l'affichage."""
    _millesime("2024", actif=True)
    _millesime("2026", actif=True)
    call_command("millesimes_sig", "--couche", COUCHE)
    out = capsys.readouterr().out
    assert "PLUSIEURS millésimes actifs" in out
