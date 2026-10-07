"""Provisioning des liens syndiqués dans les PC (#467 / #254).

remplir_liens_pc_467 (annexes PAR Grand Est) et provisionner_pc_hdf_467
(déclinaisons Hauts-de-France).
"""

import io

import pytest
from django.core.management import call_command

from envergo.nitrates.constants import SCOPE_REGION
from envergo.nitrates.models import CodePrescription, LienReference

pytestmark = pytest.mark.django_db

ITEM_DISPOSITIF = (
    "Mettre en place un dispositif de suivi des reliquats azotés sur l'îlot."
)


def _run(*args, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    call_command(*args, stdout=out, stderr=err, **kwargs)
    return out.getvalue(), err.getvalue()


def _pc(identifiant, blocs):
    pc, _ = CodePrescription.objects.update_or_create(
        identifiant=identifiant, defaults={"blocs": blocs}
    )
    return pc


# --- remplir_liens_pc_467 ---------------------------------------------------


@pytest.fixture
def pc_ge():
    CodePrescription.objects.update(blocs=[])
    LienReference.objects.filter(identifiant__startswith="par-ge-").delete()
    reliquats = _pc(
        "pc_test_ge_reliquats",
        [
            {
                "texte": "Suivi obligatoire (pour connaître le dispositif de suivi "
                "à mettre en place en Grand Est, cliquez ici :  ) chaque année."
            }
        ],
    )
    sols = _pc(
        "pc_test_ge_sols",
        [{"items": [{"texte": "(pour connaître les sols concernés, cliquez ici : )"}]}],
    )
    ancien = _pc(
        "pc_test_ge_ancien",
        [
            {
                "lien": "/static/nitrates/documents/"
                "par-ge-annexe2-modalites-reliquats.pdf",
                "texte": "annexe",
            }
        ],
    )
    return reliquats, sols, ancien


def test_remplir_liens_syndique_les_trois_formes(pc_ge):
    reliquats, sols, ancien = pc_ge

    out, _ = _run("remplir_liens_pc_467")

    assert LienReference.objects.filter(identifiant="par-ge-annexe2-reliquats").exists()
    assert LienReference.objects.filter(identifiant="par-ge-annexe3-sols").exists()
    for pc in pc_ge:
        pc.refresh_from_db()
    segments = reliquats.blocs[0]["texte"]
    assert segments[0]["texte"].startswith("Suivi obligatoire (pour connaître")
    assert segments[1]["lien_ref"] == "par-ge-annexe2-reliquats"
    assert segments[2]["texte"] == ") chaque année."
    assert sols.blocs[0]["items"][0]["texte"][1]["lien_ref"] == "par-ge-annexe3-sols"
    assert ancien.blocs[0] == {
        "texte": "annexe",
        "lien_ref": "par-ge-annexe2-reliquats",
    }
    assert "3 PC modifiée(s)." in out

    # Idempotent.
    out, _ = _run("remplir_liens_pc_467")
    assert "0 PC modifiée(s)." in out


def test_remplir_liens_dry_run(pc_ge):
    reliquats, _, _ = pc_ge
    blocs_avant = reliquats.blocs

    out, _ = _run("remplir_liens_pc_467", "--dry-run")

    reliquats.refresh_from_db()
    assert reliquats.blocs == blocs_avant
    assert not LienReference.objects.filter(identifiant__startswith="par-ge-").exists()
    assert "[dry-run] LienReference par-ge-annexe2-reliquats : à créer" in out
    assert "[dry-run] 3 PC modifiée(s)." in out


# --- provisionner_pc_hdf_467 ------------------------------------------------


@pytest.fixture
def bases_hdf():
    CodePrescription.objects.filter(identifiant__endswith="_hdf").delete()
    LienReference.objects.filter(identifiant="par-hdf-annexe1-reliquats").delete()
    avec_dispositif = _pc("pc1", [{"items": [{"texte": ITEM_DISPOSITIF}]}])
    sans_dispositif = _pc("pc3", [{"texte": "Rien à voir."}])
    # pc4 absente : on la renomme (des déclinaisons la référencent en PROTECT).
    CodePrescription.objects.filter(identifiant="pc4").update(identifiant="pc4_x")
    return avec_dispositif, sans_dispositif


def test_provisionner_hdf_cree_la_declinaison_avec_lien(bases_hdf):
    base, _ = bases_hdf

    out, err = _run("provisionner_pc_hdf_467")

    variante = CodePrescription.objects.get(identifiant="pc1_hdf")
    assert variante.variante_de == base
    assert (variante.scope, variante.region_code) == (SCOPE_REGION, "32")
    segments = variante.blocs[0]["items"][0]["texte"]
    assert segments[1]["lien_ref"] == "par-hdf-annexe1-reliquats"
    assert segments[2]["texte"] == ")."
    # La base n'est pas modifiée.
    base.refresh_from_db()
    assert base.blocs[0]["items"][0]["texte"] == ITEM_DISPOSITIF
    assert LienReference.objects.filter(
        identifiant="par-hdf-annexe1-reliquats"
    ).exists()
    assert "pc1_hdf : créée (1 lien(s) inséré(s))" in out
    assert "pc3_hdf : aucun item" in err
    assert "PC de base absente : pc4" in err
    assert not CodePrescription.objects.filter(identifiant="pc3_hdf").exists()

    out, _ = _run("provisionner_pc_hdf_467")
    assert "pc1_hdf : existe déjà, ignoré" in out


def test_provisionner_hdf_dry_run(bases_hdf):
    out, _ = _run("provisionner_pc_hdf_467", "--dry-run")

    assert not CodePrescription.objects.filter(identifiant="pc1_hdf").exists()
    assert "[dry-run] pc1_hdf : créée" in out
