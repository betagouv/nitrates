"""Tests de la commande `seed_referentiels` (cf. carte #61).

Valide :
  - le seed produit le bon volume (counts) depuis le YAML packagé
  - la commande est idempotente (2e passage = 0 created, X updated)
  - les FK Culture→GroupeCultureUI / BrancheCulturale sont cohérentes
  - le dédoublonnage brunissement_soies → brunissement_des_soies
  - le mapping mais → champs_prefill {culture_irriguee_type: mais}
  - la note_5 a bien ses régions/dépts JSONField
"""

from io import StringIO

import pytest
from django.core.management import call_command

from envergo.nitrates.models import (
    BrancheCulturale,
    CodePrescription,
    Culture,
    EvenementPhenologique,
    Fertilisant,
    GroupeCultureUI,
    NoteReglementaire,
)

pytestmark = pytest.mark.django_db


def _seed():
    """Helper : lance la commande, retourne stdout."""
    out = StringIO()
    call_command("seed_referentiels", stdout=out, stderr=StringIO())
    return out.getvalue()


def _reset():
    """Vide les 7 tables pour partir d'une base propre."""
    CodePrescription.objects.all().delete()
    NoteReglementaire.objects.all().delete()
    EvenementPhenologique.objects.all().delete()
    Fertilisant.objects.all().delete()
    Culture.objects.all().delete()
    BrancheCulturale.objects.all().delete()
    GroupeCultureUI.objects.all().delete()


# ─── Volumes ─────────────────────────────────────────────────────────────────


def test_seed_produit_volumes_attendus():
    _reset()
    _seed()
    # Volumes attendus selon le YAML packagé actuel.
    # BrancheCulturale = 12 depuis l'aplatissement des couverts
    # (spec_refactor_couverts) : les 6 variantes cie/cine remplacent les
    # 2 ex-branches interculture_longue/interculture_courte.
    assert GroupeCultureUI.objects.count() == 7
    assert BrancheCulturale.objects.count() == 12
    assert Culture.objects.count() == 19
    # 30 depuis la carte #98 : l'ancien effluents_peu_charges_autre (1) est
    # remplacé par effluents_peu_charges_elevage + _non_elevage (2).
    assert Fertilisant.objects.count() == 30
    assert NoteReglementaire.objects.count() == 13
    assert CodePrescription.objects.count() == 16
    # 7 dans le YAML mais on retire brunissement_soies (doublon).
    assert EvenementPhenologique.objects.count() == 6


# ─── Idempotence ─────────────────────────────────────────────────────────────


def test_seed_idempotent():
    _reset()
    _seed()
    count_first = GroupeCultureUI.objects.count()
    out = _seed()
    count_second = GroupeCultureUI.objects.count()
    assert count_first == count_second
    # Le 2e passage doit dire "X mis à jour", pas "X créés"
    assert "0 créé(s), 7 mis à jour" in out


# ─── FK Culture cohérentes ───────────────────────────────────────────────────


def test_culture_colza_categorie_et_branche():
    _reset()
    _seed()
    colza = Culture.objects.get(identifiant="colza")
    assert colza.categorie.identifiant == "culture_hiver"
    assert colza.branche_culturale.identifiant == "colza"
    assert colza.occupation_sol == "culture_principale"


def test_culture_mais_a_champs_prefill_culture_irriguee_type():
    _reset()
    _seed()
    mais = Culture.objects.get(identifiant="mais")
    assert mais.champs_prefill == {"culture_irriguee_type": "mais"}


def test_culture_prairie_permanente_a_flag():
    _reset()
    _seed()
    pp = Culture.objects.get(identifiant="prairie_permanente")
    assert pp.champs_prefill.get("prairie_permanente") is True


# ─── Dédoublonnage brunissement ──────────────────────────────────────────────


def test_evenement_brunissement_dedoublonne():
    _reset()
    _seed()
    idents = set(EvenementPhenologique.objects.values_list("identifiant", flat=True))
    # On garde le slug avec "des" (référencé dans l'arbre).
    assert "brunissement_des_soies" in idents
    assert "brunissement_soies" not in idents


def test_evenement_brunissement_date_mi_aout():
    _reset()
    _seed()
    brn = EvenementPhenologique.objects.get(identifiant="brunissement_des_soies")
    assert brn.date_calendrier == "15/08"


# ─── Note 5 géographique ─────────────────────────────────────────────────────


def test_note_5_a_regions_et_departements():
    _reset()
    _seed()
    n5 = NoteReglementaire.objects.get(identifiant="note_5")
    assert "R93" in n5.regions_concernees
    assert "R76" in n5.regions_concernees
    assert "24" in n5.departements_concernes
    assert "64" in n5.departements_concernes


# ─── Fertilisants type_reglementaire ─────────────────────────────────────────


def test_fertilisant_engrais_azote_mineral_type_III():
    _reset()
    _seed()
    f = Fertilisant.objects.get(identifiant="engrais_azote_mineral")
    assert f.type_reglementaire == "type_III"
    assert f.categorie == "engrais_mineral"


def test_fertilisant_fumier_compact_type_Ia():
    _reset()
    _seed()
    f = Fertilisant.objects.get(identifiant="fumier_compact_non_susceptible_ecoulement")
    assert f.type_reglementaire == "type_Ia"
    assert f.categorie == "fumiers"


# ─── Carte #98 : scission effluents peu chargés ──────────────────────────────


def test_effluents_peu_charges_scindes_en_deux():
    """L'ancien effluents_peu_charges_autre a disparu du YAML, remplacé par
    deux sous-fertilisants type II dans la catégorie autre."""
    _reset()
    _seed()
    assert not Fertilisant.objects.filter(
        identifiant="effluents_peu_charges_autre"
    ).exists()
    for slug in (
        "effluents_peu_charges_elevage",
        "effluents_peu_charges_non_elevage",
    ):
        f = Fertilisant.objects.get(identifiant=slug)
        assert f.type_reglementaire == "type_II"
        assert f.categorie == "autre"


def test_effluents_peu_charges_elevage_prefill():
    """« Issus d'élevage » pré-remplit effluent_peu_charge ET
    effluent_peu_charge_elevage=true → l'arbre infère les deux réponses."""
    _reset()
    _seed()
    f = Fertilisant.objects.get(identifiant="effluents_peu_charges_elevage")
    assert f.champs_prefill == {
        "effluent_peu_charge": "true",
        "effluent_peu_charge_elevage": "true",
    }


def test_effluents_peu_charges_non_elevage_prefill():
    """« Non issus d'élevage » : effluent_peu_charge=true mais
    effluent_peu_charge_elevage=false."""
    _reset()
    _seed()
    f = Fertilisant.objects.get(identifiant="effluents_peu_charges_non_elevage")
    assert f.champs_prefill == {
        "effluent_peu_charge": "true",
        "effluent_peu_charge_elevage": "false",
    }


# ─── Sol non cultivé ─────────────────────────────────────────────────────────


def test_categorie_sol_non_cultive_a_champs_prefill():
    """Catégorie spéciale qui n'a pas de Cultures filles : pré-remplit
    directement occupation_sol pour la cascade frontend."""
    _reset()
    _seed()
    cat = GroupeCultureUI.objects.get(identifiant="sol_non_cultive")
    assert cat.champs_prefill == {"occupation_sol": "sol_non_cultive"}


# ─── Codes prescription ──────────────────────────────────────────────────────


def test_code_prescription_pc1_seede():
    _reset()
    _seed()
    pc1 = CodePrescription.objects.get(identifiant="pc1")
    assert pc1.mots_cles == "ICPE A"
    assert pc1.texte_court  # non vide
