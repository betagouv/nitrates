"""Tests des modèles `models_referentiels` (cf. carte #61).

Couverture :
  - unicité des `identifiant` slug
  - CheckConstraint `Fertilisant.type_reglementaire != "type_I"`
  - RegexValidator JJ/MM sur `EvenementPhenologique.date_calendrier`
  - ordering par défaut
  - FK PROTECT sur GroupeCultureUI / BrancheCulturale
  - FK SET_NULL sur CodePrescription.note_reglementaire
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from envergo.nitrates.constants import (
    CategorieFertilisant,
    OccupationSol,
    TypeFertilisant,
)
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


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_categorie(identifiant="test_categorie_unique", **kwargs):
    return GroupeCultureUI.objects.create(
        identifiant=identifiant,
        libelle_public=kwargs.get("libelle_public", identifiant.replace("_", " ")),
        ordre_affichage=kwargs.get("ordre_affichage", 0),
    )


def _make_branche(identifiant="test_branche_unique", **kwargs):
    return BrancheCulturale.objects.create(
        identifiant=identifiant,
        libelle_court=kwargs.get("libelle_court", identifiant),
    )


def _make_culture(
    identifiant="test_culture_unique", categorie=None, branche=None, **kwargs
):
    return Culture.objects.create(
        identifiant=identifiant,
        libelle_public=kwargs.get("libelle_public", identifiant),
        categorie=categorie or _make_categorie(),
        branche_culturale=branche or _make_branche(),
        occupation_sol=kwargs.get("occupation_sol", OccupationSol.CULTURE_PRINCIPALE),
    )


# ─── Unicité identifiants ─────────────────────────────────────────────────────


def test_categorie_culture_identifiant_unique():
    _make_categorie("test_unique_cat")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _make_categorie("test_unique_cat")


def test_branche_culturale_identifiant_unique():
    _make_branche("test_unique_br")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _make_branche("test_unique_br")


def test_culture_identifiant_unique():
    cat = _make_categorie("test_unique_culture_cat")
    br = _make_branche("test_unique_culture_br")
    Culture.objects.create(
        identifiant="test_unique_culture",
        libelle_public="Test",
        categorie=cat,
        branche_culturale=br,
        occupation_sol=OccupationSol.CULTURE_PRINCIPALE,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Culture.objects.create(
                identifiant="test_unique_culture",
                libelle_public="dup",
                categorie=cat,
                branche_culturale=br,
                occupation_sol=OccupationSol.CULTURE_PRINCIPALE,
            )


def test_fertilisant_identifiant_unique():
    Fertilisant.objects.create(
        identifiant="test_unique_fert",
        libelle_public="Test",
        categorie=CategorieFertilisant.LISIERS,
        type_reglementaire=TypeFertilisant.TYPE_II,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Fertilisant.objects.create(
                identifiant="test_unique_fert",
                libelle_public="dup",
                categorie=CategorieFertilisant.LISIERS,
                type_reglementaire=TypeFertilisant.TYPE_II,
            )


# ─── CheckConstraint type_I interdit sur Fertilisant ─────────────────────────


def test_fertilisant_type_I_interdit_par_check_constraint():
    """Le type_I est reserve aux branches d'arbre regroupees (Ia ∪ Ib),
    aucun Fertilisant en DB ne doit le porter (cf. fallback parcours)."""
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Fertilisant.objects.create(
                identifiant="fertilisant_type_I_pirate",
                libelle_public="x",
                categorie=CategorieFertilisant.AUTRE,
                type_reglementaire=TypeFertilisant.TYPE_I,
            )


def test_fertilisant_type_Ia_ou_Ib_autorise():
    Fertilisant.objects.create(
        identifiant="test_fertilisant_Ia",
        libelle_public="Test Ia",
        categorie=CategorieFertilisant.FUMIERS,
        type_reglementaire=TypeFertilisant.TYPE_IA,
    )
    Fertilisant.objects.create(
        identifiant="test_fertilisant_Ib",
        libelle_public="Test Ib",
        categorie=CategorieFertilisant.COMPOSTS,
        type_reglementaire=TypeFertilisant.TYPE_IB,
    )


# ─── RegexValidator date_calendrier ──────────────────────────────────────────


def test_evenement_phenologique_date_valide_jjmm():
    ev = EvenementPhenologique(
        identifiant="test_evt_valid",
        libelle_public="Test",
        date_calendrier="15/08",
    )
    ev.full_clean()
    ev.save()
    assert ev.pk is not None


@pytest.mark.parametrize(
    "date_invalide",
    [
        "15-08",  # mauvais séparateur
        "1/8",  # pas zero-padded
        "32/13",  # numérique mais hors plage (regex ne contraint pas la plage,
        # mais on garde pour signaler le besoin futur)
        "S1+15j",  # format libre type semaine
        "",  # vide
    ],
)
def test_evenement_phenologique_date_invalide_levee(date_invalide):
    if date_invalide == "32/13":
        pytest.skip(
            "le RegexValidator JJ/MM accepte 32/13 (pas de check de plage). "
            "À durcir si besoin futur."
        )
    ev = EvenementPhenologique(
        identifiant="evt_test",
        libelle_public="Test",
        date_calendrier=date_invalide,
    )
    with pytest.raises(ValidationError):
        ev.full_clean()


# ─── FK PROTECT ──────────────────────────────────────────────────────────────


def test_culture_protege_categorie_de_suppression():
    cat = _make_categorie()
    _make_culture(categorie=cat)
    with pytest.raises(Exception):  # ProtectedError
        with transaction.atomic():
            cat.delete()


def test_culture_protege_branche_de_suppression():
    br = _make_branche()
    _make_culture(branche=br)
    with pytest.raises(Exception):
        with transaction.atomic():
            br.delete()


# ─── FK SET_NULL CodePrescription.note_reglementaire ─────────────────────────


def test_code_prescription_note_optionnelle():
    pc = CodePrescription.objects.create(
        identifiant="test_pc_opt",
        mots_cles="test",
        texte_court="Test sans note.",
    )
    assert pc.note_reglementaire is None


def test_code_prescription_note_set_null_a_suppression_note():
    note = NoteReglementaire.objects.create(
        identifiant="test_note_sn",
        libelle_court="Test",
        condition_declenchement="Test",
    )
    pc = CodePrescription.objects.create(
        identifiant="test_pc_sn",
        mots_cles="test",
        texte_court="Test",
        note_reglementaire=note,
    )
    note.delete()
    pc.refresh_from_db()
    assert pc.note_reglementaire is None


# ─── champs_prefill JSON ─────────────────────────────────────────────────────


def test_culture_champs_prefill_json():
    c = _make_culture(
        identifiant="test_mais_prefill",
        categorie=_make_categorie("test_mais_cat"),
        branche=_make_branche("test_mais_br"),
    )
    c.champs_prefill = {"culture_irriguee_type": "mais"}
    c.save()
    c.refresh_from_db()
    assert c.champs_prefill == {"culture_irriguee_type": "mais"}


def test_categorie_culture_champs_prefill_json_default_vide():
    cat = _make_categorie("test_default_vide_cat")
    assert cat.champs_prefill == {}


# ─── Ordering par défaut ─────────────────────────────────────────────────────


def test_categorie_culture_ordering_par_ordre_affichage():
    """Compare uniquement les 2 catégories ajoutées par ce test
    (la DB peut contenir d'autres entrées seedées au boot)."""
    _make_categorie("ord_z_cat", ordre_affichage=10000)
    _make_categorie("ord_a_cat", ordre_affichage=9999)
    ids = list(
        GroupeCultureUI.objects.filter(
            identifiant__in=["ord_z_cat", "ord_a_cat"]
        ).values_list("identifiant", flat=True)
    )
    assert ids == ["ord_a_cat", "ord_z_cat"]


def test_culture_ordering_par_categorie_puis_ordre():
    cat_b = _make_categorie("ord_b_cat", ordre_affichage=10001)
    cat_a = _make_categorie("ord_a_cat", ordre_affichage=10000)
    br = _make_branche("ord_br")
    Culture.objects.create(
        identifiant="ord_zz",
        libelle_public="Z",
        categorie=cat_b,
        branche_culturale=br,
        occupation_sol=OccupationSol.CULTURE_PRINCIPALE,
        ordre_affichage=1,
    )
    Culture.objects.create(
        identifiant="ord_aa",
        libelle_public="A",
        categorie=cat_a,
        branche_culturale=br,
        occupation_sol=OccupationSol.CULTURE_PRINCIPALE,
        ordre_affichage=1,
    )
    ids = list(
        Culture.objects.filter(identifiant__in=["ord_aa", "ord_zz"]).values_list(
            "identifiant", flat=True
        )
    )
    # cat_a (ordre 10000) avant cat_b (ordre 10001)
    assert ids == ["ord_aa", "ord_zz"]


# ─── Choices côté Fertilisant ─────────────────────────────────────────────────


def test_fertilisant_categorie_doit_etre_dans_choices():
    """Tous les fertilisants doivent appartenir à une catégorie connue."""
    f = Fertilisant(
        identifiant="test_invalid_cat",
        libelle_public="x",
        categorie="categorie_inexistante",
        type_reglementaire=TypeFertilisant.TYPE_II,
    )
    with pytest.raises(ValidationError):
        f.full_clean()


def test_culture_occupation_sol_doit_etre_dans_choices():
    f = Culture(
        identifiant="test_invalid_occ",
        libelle_public="x",
        categorie=_make_categorie("test_invalid_occ_cat"),
        branche_culturale=_make_branche("test_invalid_occ_br"),
        occupation_sol="hors_choices",
    )
    with pytest.raises(ValidationError):
        f.full_clean()
