"""Provisionnement des PC du PAR Bretagne modifié (specs/pc_bretagne.json)."""

import json
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command

from envergo.nitrates.models_referentiels import CodePrescription

pytestmark = pytest.mark.django_db

SOURCE = Path(settings.NITRATES_SPECS_DIR) / "pc_bretagne.json"


@pytest.fixture
def bases():
    for ident in ("pc6", "pc7"):
        CodePrescription.objects.get_or_create(
            identifiant=ident, defaults={"texte_court": ident}
        )


def _identifiants():
    return {pc["identifiant"] for pc in json.loads(SOURCE.read_text())}


def test_cree_les_pc_bretagne_en_region_53(bases):
    call_command("provisionner_pc_bretagne")
    pcs = CodePrescription.objects.filter(identifiant__in=_identifiants())
    assert pcs.count() == 8
    assert set(pcs.values_list("scope", "region_code").distinct()) == {("region", "53")}
    assert (
        CodePrescription.objects.get(identifiant="pc6_bzh").variante_de.identifiant
        == "pc6"
    )
    assert all(pc.blocs for pc in pcs)


def test_idempotent_sans_ecraser_une_retouche(bases):
    call_command("provisionner_pc_bretagne")
    CodePrescription.objects.filter(identifiant="pc_bzh_derobees").update(
        texte_court="retouche juriste"
    )
    call_command("provisionner_pc_bretagne")
    assert (
        CodePrescription.objects.get(identifiant="pc_bzh_derobees").texte_court
        == "retouche juriste"
    )


def test_maj_ecrase(bases):
    call_command("provisionner_pc_bretagne")
    CodePrescription.objects.filter(identifiant="pc_bzh_derobees").update(
        texte_court="x"
    )
    call_command("provisionner_pc_bretagne", maj=True)
    assert (
        CodePrescription.objects.get(identifiant="pc_bzh_derobees").texte_court != "x"
    )


def test_dry_run_ne_cree_rien(bases):
    call_command("provisionner_pc_bretagne", dry_run=True)
    assert not CodePrescription.objects.filter(identifiant__in=_identifiants()).exists()
