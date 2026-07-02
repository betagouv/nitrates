"""Tests de `periode_phrase` et de la resolution des libelles phenologiques
(#85 : plus de slug snake_case a l'ecran, on resout le libelle_public)."""

from types import SimpleNamespace

import pytest

from envergo.nitrates.templatetags.nitrates_tags import (
    _date_lisible,
    _libelle_phenologique,
    _minuscule_initiale,
    periode_autorisation_phrase,
    periode_phrase,
    periodes_datees,
    periodes_par_section,
)


def _regle(**kwargs):
    defaults = {"type": "interdiction", "periodes": []}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# load_referentiels lit l'arbre/referentiel actif en DB.
pytestmark = pytest.mark.django_db


def test_periode_phrase_bornes_fixes():
    # Format date lisible : mois en toutes lettres (#159), plus de JJ/MM.
    assert (
        periode_phrase({"du": "15/07", "au": "15/02"}) == "du 15 juillet au 15 février"
    )


def test_periode_phrase_borne_pheno_debut_resout_libelle():
    # `derniere_coupe_luzerne` -> "Dernière coupe de la luzerne", minuscule
    # initiale car insere en milieu de phrase. Plus aucun slug ni guillemet.
    phrase = periode_phrase({"du": "derniere_coupe_luzerne", "au": "15/01"})
    assert phrase == "de dernière coupe de la luzerne au 15 janvier"
    assert "_" not in phrase
    assert "«" not in phrase


def test_periode_phrase_borne_pheno_fin_resout_libelle():
    phrase = periode_phrase({"du": "15/07", "au": "brunissement_des_soies"})
    assert phrase == "du 15 juillet au brunissement des soies (maïs)"
    assert "_" not in phrase


def test_libelle_phenologique_fallback_slug_inconnu():
    # Slug absent du referentiel : fallback lisible (underscores -> espaces),
    # jamais le snake_case brut.
    assert _libelle_phenologique("slug_inexistant_xyz") == "slug inexistant xyz"


def test_minuscule_initiale():
    assert _minuscule_initiale("Dernière coupe") == "dernière coupe"
    assert _minuscule_initiale("Brunissement (maïs)") == "brunissement (maïs)"
    assert _minuscule_initiale("") == ""


# ─── periode_autorisation_phrase : periode d'autorisation pure (#85) ─────────


def test_date_lisible_format_unifie():
    # Mois en toutes lettres (#159).
    assert _date_lisible(15, 7) == "15 juillet"
    assert _date_lisible(1, 2) == "1er février"  # 1er du mois
    assert _date_lisible(30, 6) == "30 juin"
    assert _date_lisible(31, 8) == "31 août"


def test_autorisation_interdiction_simple_wrap():
    # Interdit 15/10 -> 31/01 (wrap annee) -> autorise le reste 01/02 -> 14/10.
    r = _regle(type="interdiction", periodes=[{"du": "15/10", "au": "31/01"}])
    assert periode_autorisation_phrase(r) == "du 1er février au 14 octobre"


def test_autorisation_toute_lannee_interdite_vide():
    # Interdit 01/07 -> 30/06 : aucun jour autorise -> "".
    r = _regle(type="interdiction", periodes=[{"du": "01/07", "au": "30/06"}])
    assert periode_autorisation_phrase(r) == ""


def test_autorisation_deux_plages_jointes_par_et():
    # Deux interdictions disjointes -> deux plages d'autorisation, l'une
    # enjambant le pivot juillet (wrap fusionne).
    r = _regle(
        type="interdiction",
        periodes=[{"du": "01/08", "au": "31/08"}, {"du": "01/11", "au": "30/11"}],
    )
    phrase = periode_autorisation_phrase(r)
    assert " et " in phrase
    assert phrase.count("du ") == 2


def test_autorisation_mixte_soustrait_asc_et_interdiction():
    # ASC (date_calendrier derniere coupe = 20/12) + interdiction 15/12->15/01
    # -> autorisation = le complement.
    r = _regle(
        type="mixte",
        periodes=[
            {"du": "15/12", "au": "15/01", "regime": "interdiction"},
            {
                "du": "derniere_coupe_luzerne",
                "au": "15/01",
                "regime": "autorisation_sous_condition",
            },
        ],
    )
    phrase = periode_autorisation_phrase(r)
    assert phrase.startswith("du ")
    assert "/" not in phrase  # format unifie, pas de JJ/MM


def test_autorisation_regle_none_vide():
    assert periode_autorisation_phrase(None) == ""


# ─── periodes_datees : ordre des puces (#85) ────────────────────────────────


def test_periodes_datees_ordre_interdiction_asc_autorisation():
    # Ordre attendu : interdiction d'abord, puis ASC, puis autorisation pure.
    r = _regle(
        type="mixte",
        periodes=[
            {"du": "15/12", "au": "15/01", "regime": "interdiction"},
            {
                "du": "derniere_coupe_luzerne",
                "au": "15/01",
                "regime": "autorisation_sous_condition",
            },
        ],
    )
    labels = [p["label"] for p in periodes_datees(r)]
    assert labels == [
        "Interdiction",
        "Autorisé sous conditions",
        "Période d'autorisation",
    ]


def test_periodes_datees_interdiction_simple_sans_regime():
    # type=interdiction, periode sans regime explicite -> puce "Interdiction"
    # + l'autorisation pure (complement).
    r = _regle(type="interdiction", periodes=[{"du": "15/10", "au": "31/01"}])
    labels = [p["label"] for p in periodes_datees(r)]
    assert labels == ["Interdiction", "Période d'autorisation"]


def test_periodes_datees_regle_none():
    assert periodes_datees(None) == []


# ─── periodes_par_section : regroupement par section + justification (#159) ──


def test_periodes_par_section_groupe_et_ordonne():
    # interdiction + ASC -> 3 sections (interdiction, ASC, autorisation pure).
    r = _regle(
        type="mixte",
        texte_condition="Interdit du 15/12 au 15/01.",
        periodes=[
            {"du": "15/12", "au": "15/01", "regime": "interdiction"},
            {
                "du": "derniere_coupe_luzerne",
                "au": "15/01",
                "regime": "autorisation_sous_condition",
            },
        ],
    )
    sections = periodes_par_section(r)
    titres = [s["titre"] for s in sections]
    assert titres == ["Interdiction", "Autorisé sous conditions", "Autorisé"]
    # Mois en toutes lettres dans les phrases.
    assert sections[0]["periodes"][0]["phrase"] == "du 15 décembre au 15 janvier"
    # La justification (texte_condition) est portee par les sections non-libres.
    assert sections[0]["periodes"][0]["justification"] == "Interdit du 15/12 au 15/01."
    # L'autorisation pure n'a pas de justification.
    assert sections[-1]["titre"] == "Autorisé"
    assert sections[-1]["periodes"][0]["justification"] is None


def test_periodes_par_section_sans_texte_condition():
    # Pas de texte_condition -> justification None (pas de ⓘ cote template).
    r = _regle(type="interdiction", periodes=[{"du": "15/10", "au": "31/01"}])
    sections = periodes_par_section(r)
    assert sections[0]["titre"] == "Interdiction"
    assert sections[0]["periodes"][0]["justification"] is None


def test_periodes_par_section_regle_none():
    assert periodes_par_section(None) == []
