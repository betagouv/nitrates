"""Tests des champs glossaire de ContenuRichDSFR + loader caché (carte #110)."""

import pytest
from django.core.exceptions import ValidationError

from envergo.nitrates.contenu_rich.glossaire import (
    invalider_cache_glossaire,
    load_definitions,
    load_index_termes,
)
from envergo.nitrates.models import ContenuRichDSFR
from envergo.nitrates.models_contenu_rich import TYPE_DEFINITION, TYPE_GENERAL

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _cache_glossaire_propre():
    """Chaque test part d'une table ET d'un cache vides.

    La fixture `initial_referentiels.json` (chargée par la fixture session
    `seed_referentiels_nitrates`) embarque désormais les contenus riches, dont
    les 17 définitions seedées. Ces tests raisonnent sur un glossaire qu'ils
    construisent eux-mêmes : on vide la table d'abord, sinon les clés entrent
    en collision et l'index contient des termes non prévus."""
    ContenuRichDSFR.objects.all().delete()
    invalider_cache_glossaire()
    yield
    invalider_cache_glossaire()


def _definition(cle, titre, termes=None, **kwargs):
    return ContenuRichDSFR.objects.create(
        cle=cle,
        libelle_admin=titre,
        type_contenu=TYPE_DEFINITION,
        titre_public=titre,
        termes_declencheurs=termes or [],
        blocs={
            "schema": 1,
            "blocs": [{"type": "paragraphe", "data": {"texte": "Def."}}],
        },
        **kwargs,
    )


# ─── Modèle ──────────────────────────────────────────────────────────────────


def test_defaut_type_general():
    c = ContenuRichDSFR.objects.create(cle="zone.test", libelle_admin="Zone")
    assert c.type_contenu == TYPE_GENERAL
    assert c.termes_declencheurs == []
    assert c.titre_public == ""
    assert c.categorie == ""


def test_clean_definition_sans_titre_refusee():
    c = ContenuRichDSFR(
        cle="definition.sans-titre",
        libelle_admin="Sans titre",
        type_contenu=TYPE_DEFINITION,
    )
    with pytest.raises(ValidationError) as exc:
        c.full_clean()
    assert "titre_public" in exc.value.message_dict


def test_clean_general_sans_titre_ok():
    c = ContenuRichDSFR(cle="zone.libre", libelle_admin="Zone libre")
    c.full_clean()  # ne lève pas


def test_ancre_derivee_de_la_cle():
    c = ContenuRichDSFR(cle="definition.azote-efficace")
    assert c.ancre == "azote-efficace"
    # Un éventuel sous-niveau pointé reste un id/fragment valide.
    c2 = ContenuRichDSFR(cle="definition.types.fertilisants")
    assert c2.ancre == "types-fertilisants"


def test_liste_termes_tolerante():
    c = ContenuRichDSFR(termes_declencheurs=["C/N", "  ", "rapport C/N"])
    assert c.liste_termes == ["C/N", "rapport C/N"]
    c2 = ContenuRichDSFR(termes_declencheurs=None)
    assert c2.liste_termes == []


# ─── Loader glossaire ────────────────────────────────────────────────────────


def test_load_definitions_filtre_les_general():
    _definition("definition.azote-efficace", "Azote efficace")
    ContenuRichDSFR.objects.create(cle="resultat.zone-x", libelle_admin="Zone X")
    invalider_cache_glossaire()
    cles = [d.cle for d in load_definitions()]
    assert "definition.azote-efficace" in cles
    assert "resultat.zone-x" not in cles


def test_index_termes_longest_first_et_titre_inclus():
    _definition("definition.interculture", "Interculture")
    _definition(
        "definition.interculture-longue",
        "Interculture longue",
        termes=["IC longue"],
    )
    invalider_cache_glossaire()
    variantes = [v for v, _ in load_index_termes()]
    # Le titre public matche toujours, les variantes s'ajoutent.
    assert "Interculture" in variantes
    assert "Interculture longue" in variantes
    assert "IC longue" in variantes
    # Tri longest-first : la variante longue précède la courte.
    assert variantes.index("Interculture longue") < variantes.index("Interculture")


def test_index_termes_dedoublonne_titre_repete():
    # Titre répété dans les termes déclencheurs (erreur de saisie courante).
    _definition("definition.icpe", "ICPE", termes=["icpe", "ICPE"])
    invalider_cache_glossaire()
    variantes = [v.lower() for v, _ in load_index_termes()]
    assert variantes.count("icpe") == 1


def test_admin_form_termes_une_variante_par_ligne():
    # Le form admin convertit textarea "une variante par ligne" <-> liste JSON.
    from envergo.nitrates.admin import ContenuRichDSFRForm

    form = ContenuRichDSFRForm(
        data={
            "cle": "definition.c-n",
            "libelle_admin": "C/N",
            "blocs": "{}",
            "type_contenu": TYPE_DEFINITION,
            "titre_public": "C / N",
            "categorie": "fertilisants-effluents",
            "termes_declencheurs": "C/N\n  \nrapport C/N\n",
        }
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["termes_declencheurs"] == ["C/N", "rapport C/N"]
    obj = form.save()
    # Ré-ouverture : l'initial re-présente une variante par ligne.
    form2 = ContenuRichDSFRForm(instance=obj)
    assert form2.initial["termes_declencheurs"] == "C/N\nrapport C/N"


def test_cache_invalide_par_save():
    # Le signal post_save (apps.py) doit invalider le cache sans restart.
    assert load_definitions() == []
    _definition("definition.ismo", "ISMO")
    assert [d.cle for d in load_definitions()] == ["definition.ismo"]
