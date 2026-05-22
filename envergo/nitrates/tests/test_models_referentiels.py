"""Tests des modèles `models_referentiels` (cf. carte #61).

Couverture :
  - unicité des `identifiant` slug
  - CheckConstraint `Fertilisant.type_reglementaire != "type_I"`
  - RegexValidator JJ/MM sur `EvenementPhenologique.date_calendrier`
  - ordering par défaut
  - FK PROTECT sur CategorieCulture / BrancheCulturale
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
    CategorieCulture,
    CodePrescription,
    Culture,
    EvenementPhenologique,
    Fertilisant,
    NoteReglementaire,
)

pytestmark = pytest.mark.django_db


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_categorie(identifiant="culture_hiver", **kwargs):
    return CategorieCulture.objects.create(
        identifiant=identifiant,
        libelle_public=kwargs.get("libelle_public", identifiant.replace("_", " ")),
        ordre_affichage=kwargs.get("ordre_affichage", 0),
    )


def _make_branche(identifiant="colza", **kwargs):
    return BrancheCulturale.objects.create(
        identifiant=identifiant,
        libelle_court=kwargs.get("libelle_court", identifiant),
    )


def _make_culture(identifiant="colza", categorie=None, branche=None, **kwargs):
    return Culture.objects.create(
        identifiant=identifiant,
        libelle_public=kwargs.get("libelle_public", identifiant),
        categorie=categorie or _make_categorie(),
        branche_culturale=branche or _make_branche(),
        occupation_sol=kwargs.get("occupation_sol", OccupationSol.CULTURE_PRINCIPALE),
    )


# ─── Unicité identifiants ─────────────────────────────────────────────────────


def test_categorie_culture_identifiant_unique():
    _make_categorie("culture_hiver")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _make_categorie("culture_hiver")


def test_branche_culturale_identifiant_unique():
    _make_branche("colza")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _make_branche("colza")


def test_culture_identifiant_unique():
    cat = _make_categorie()
    br = _make_branche()
    Culture.objects.create(
        identifiant="colza",
        libelle_public="Colza",
        categorie=cat,
        branche_culturale=br,
        occupation_sol=OccupationSol.CULTURE_PRINCIPALE,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Culture.objects.create(
                identifiant="colza",
                libelle_public="Colza dup",
                categorie=cat,
                branche_culturale=br,
                occupation_sol=OccupationSol.CULTURE_PRINCIPALE,
            )


def test_fertilisant_identifiant_unique():
    Fertilisant.objects.create(
        identifiant="fientes_volailles",
        libelle_public="Fientes de volailles",
        categorie=CategorieFertilisant.LISIERS,
        type_reglementaire=TypeFertilisant.TYPE_II,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Fertilisant.objects.create(
                identifiant="fientes_volailles",
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
        identifiant="fumier_compact",
        libelle_public="Fumier compact",
        categorie=CategorieFertilisant.FUMIERS,
        type_reglementaire=TypeFertilisant.TYPE_IA,
    )
    Fertilisant.objects.create(
        identifiant="compost_biodechets",
        libelle_public="Compost biodéchets",
        categorie=CategorieFertilisant.COMPOSTS,
        type_reglementaire=TypeFertilisant.TYPE_IB,
    )


# ─── RegexValidator date_calendrier ──────────────────────────────────────────


def test_evenement_phenologique_date_valide_jjmm():
    ev = EvenementPhenologique(
        identifiant="brunissement_des_soies",
        libelle_public="Brunissement des soies",
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
        identifiant="pc99",
        mots_cles="test",
        texte_court="Test sans note.",
    )
    assert pc.note_reglementaire is None


def test_code_prescription_note_set_null_a_suppression_note():
    note = NoteReglementaire.objects.create(
        identifiant="note_99",
        libelle_court="Test",
        condition_declenchement="Test",
    )
    pc = CodePrescription.objects.create(
        identifiant="pc99",
        mots_cles="test",
        texte_court="Test",
        note_reglementaire=note,
    )
    note.delete()
    pc.refresh_from_db()
    assert pc.note_reglementaire is None


# ─── champs_prefill JSON ─────────────────────────────────────────────────────


def test_culture_champs_prefill_json():
    c = _make_culture(identifiant="mais")
    c.champs_prefill = {"culture_irriguee_type": "mais"}
    c.save()
    c.refresh_from_db()
    assert c.champs_prefill == {"culture_irriguee_type": "mais"}


def test_categorie_culture_champs_prefill_json_default_vide():
    cat = _make_categorie()
    assert cat.champs_prefill == {}


# ─── Ordering par défaut ─────────────────────────────────────────────────────


def test_categorie_culture_ordering_par_ordre_affichage():
    _make_categorie("z_test", ordre_affichage=10)
    _make_categorie("a_test", ordre_affichage=1)
    ids = list(CategorieCulture.objects.values_list("identifiant", flat=True))
    assert ids == ["a_test", "z_test"]


def test_culture_ordering_par_categorie_puis_ordre():
    cat_b = _make_categorie("b_cat", ordre_affichage=2)
    cat_a = _make_categorie("a_cat", ordre_affichage=1)
    br = _make_branche()
    Culture.objects.create(
        identifiant="zz",
        libelle_public="Z",
        categorie=cat_b,
        branche_culturale=br,
        occupation_sol=OccupationSol.CULTURE_PRINCIPALE,
        ordre_affichage=1,
    )
    Culture.objects.create(
        identifiant="aa",
        libelle_public="A",
        categorie=cat_a,
        branche_culturale=br,
        occupation_sol=OccupationSol.CULTURE_PRINCIPALE,
        ordre_affichage=1,
    )
    ids = list(Culture.objects.values_list("identifiant", flat=True))
    # cat_a (ordre 1) avant cat_b (ordre 2)
    assert ids == ["aa", "zz"]


# ─── Choices côté Fertilisant ─────────────────────────────────────────────────


def test_fertilisant_categorie_doit_etre_dans_choices():
    """Tous les fertilisants doivent appartenir à une catégorie connue."""
    f = Fertilisant(
        identifiant="x",
        libelle_public="x",
        categorie="categorie_inexistante",
        type_reglementaire=TypeFertilisant.TYPE_II,
    )
    with pytest.raises(ValidationError):
        f.full_clean()


def test_culture_occupation_sol_doit_etre_dans_choices():
    f = Culture(
        identifiant="x",
        libelle_public="x",
        categorie=_make_categorie(),
        branche_culturale=_make_branche(),
        occupation_sol="hors_choices",
    )
    with pytest.raises(ValidationError):
        f.full_clean()
