"""Tests de la commande `provision_carte_98`.

Valide que le provisionnement :
  - crée les deux nouveaux fertilisants (issus / non issus d'élevage) ;
  - supprime l'ancien effluents_peu_charges_autre s'il subsiste ;
  - est idempotent (rejouable sans erreur, état final stable) ;
  - --dry-run n'écrit rien.
"""

from io import StringIO

import pytest
from django.core.management import call_command

from envergo.nitrates.models import Fertilisant

pytestmark = pytest.mark.django_db


def _provision(dry_run=False):
    out, err = StringIO(), StringIO()
    args = ["provision_carte_98"]
    if dry_run:
        args.append("--dry-run")
    call_command(*args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def test_provision_cree_les_deux_nouveaux():
    _provision()
    elevage = Fertilisant.objects.get(identifiant="effluents_peu_charges_elevage")
    non_elevage = Fertilisant.objects.get(
        identifiant="effluents_peu_charges_non_elevage"
    )
    assert elevage.type_reglementaire == "type_II"
    assert non_elevage.type_reglementaire == "type_II"
    assert elevage.champs_prefill["effluent_peu_charge_elevage"] == "true"
    assert non_elevage.champs_prefill["effluent_peu_charge_elevage"] == "false"


def test_provision_supprime_ancien_fertilisant():
    # Simule un staging qui porte encore l'ancien fertilisant.
    Fertilisant.objects.create(
        identifiant="effluents_peu_charges_autre",
        libelle_public="Effluents peu chargés",
        categorie="autre",
        type_reglementaire="type_II",
    )
    out, _ = _provision()
    assert not Fertilisant.objects.filter(
        identifiant="effluents_peu_charges_autre"
    ).exists()
    assert "Supprimé" in out


def test_provision_idempotent():
    _provision()
    count_first = Fertilisant.objects.count()
    out, _ = _provision()
    count_second = Fertilisant.objects.count()
    assert count_first == count_second
    # Au 2e passage l'ancien est déjà absent.
    assert "déjà absent" in out


def test_provision_dry_run_n_ecrit_rien():
    Fertilisant.objects.create(
        identifiant="effluents_peu_charges_autre",
        libelle_public="Effluents peu chargés",
        categorie="autre",
        type_reglementaire="type_II",
    )
    avant = set(Fertilisant.objects.values_list("identifiant", flat=True))
    _provision(dry_run=True)
    apres = set(Fertilisant.objects.values_list("identifiant", flat=True))
    assert avant == apres  # rien créé, rien supprimé
