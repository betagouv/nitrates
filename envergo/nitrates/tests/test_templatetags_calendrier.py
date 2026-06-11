"""Tests du templatetag `calendrier_epandage`."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from envergo.nitrates.templatetags.nitrates_tags import (
    _day_of_year,
    _segment_interdit,
    calendrier_epandage,
    est_interdit_toute_lannee,
)

# La fixture session `update_default_site` (envergo/conftest.py) cree un
# Site testserver et necessite l'acces DB. On opt-in.
pytestmark = pytest.mark.django_db


# ─── Helpers internes ──────────────────────────────────────────────────────


def test_day_of_year_basique_annee_agricole():
    """L'annee agricole commence le 1er juillet (jour 0)."""
    assert _day_of_year(1, 7) == 0
    assert _day_of_year(30, 6) == 364
    # 1er janvier = 6 mois apres juillet (juil + aout + sep + oct + nov + dec)
    assert _day_of_year(1, 1) == 31 + 31 + 30 + 31 + 30 + 31  # 184


def test_segment_interdit_centre_annee_agricole():
    """Periode 15/12 -> 15/01 traverse l'annee CIVILE mais pas l'annee
    AGRICOLE -> 1 seul segment continu, centre sur la barre."""
    segs = _segment_interdit({"du": "15/12", "au": "15/01"})
    assert len(segs) == 1


def test_segment_interdit_simple():
    """Periode 15/12 -> 25/12 : 1 segment dans le meme mois."""
    segs = _segment_interdit({"du": "15/12", "au": "25/12"})
    assert len(segs) == 1
    start, width = segs[0]
    # 15/12 -> 25/12 = 11 jours
    assert width == pytest.approx(11 / 365 * 100, abs=0.01)


def test_segment_interdit_pivot_annee_agricole():
    """Periode qui traverse le 30 juin (pivot de l'annee agricole) ->
    2 segments. Ex : 15/05 -> 15/08 (mai puis aout)."""
    segs = _segment_interdit({"du": "15/05", "au": "15/08"})
    assert len(segs) == 2


def test_segment_interdit_phenologique():
    """Une borne phenologique avec date_calendrier en DB produit un vrai
    segment. Sans date_calendrier (ou evenement inconnu), retombe sur
    une liste vide."""
    # `brunissement_des_soies` a `date_calendrier: "15/08"` en DB,
    # donc on produit un segment 15/08 -> 15/02.
    segs = _segment_interdit({"du": "brunissement_des_soies", "au": "15/02"})
    assert len(segs) >= 1, "Borne phenologique connue doit produire un segment"
    # Evenement inexistant : pas de date_calendrier -> liste vide.
    segs = _segment_interdit({"du": "evenement_inexistant", "au": "15/02"})
    assert segs == []


# ─── Templatetag ───────────────────────────────────────────────────────────


def _regle(**kwargs):
    """Helper : construit un objet ressemblant a un Resultat."""
    defaults = {"type": "interdiction", "periodes": [{"du": "15/12", "au": "15/01"}]}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_calendrier_avec_regle_none():
    ctx = calendrier_epandage(None)
    assert ctx["vide"] is True


def test_calendrier_interdiction_genere_segments():
    """Une regle d'interdiction sur 15/12 -> 15/01 doit produire 1 segment
    rouge centre (annee agricole juil->juin, le 31/12 n'est pas le pivot)."""
    ctx = calendrier_epandage(
        _regle(type="interdiction", periodes=[{"du": "15/12", "au": "15/01"}])
    )
    assert ctx["vide"] is False
    assert ctx["fond"] == "vert"
    assert len(ctx["segments"]) == 1
    assert ctx["segments"][0]["couleur"] == "rouge"
    # Note 2026-05-12 : tous les types epandage utilisent un label
    # commun "Calendrier d'épandage" (UX validee par Max).
    assert "Calendrier" in ctx["label"]


def test_calendrier_libre_pas_de_zone_overlay():
    """Une regle 'libre' n'a pas de periode interdite : pas de zone overlay."""
    ctx = calendrier_epandage(_regle(type="libre", periodes=[]))
    assert ctx["fond"] == "vert"
    assert ctx["segments"] == []
    # Label unifie "Calendrier d'épandage" pour tous les types epandage.
    assert ctx["label"] == "Calendrier d'épandage"


def test_calendrier_non_applicable_fond_gris():
    ctx = calendrier_epandage(_regle(type="non_applicable", periodes=[]))
    assert ctx["fond"] == "gris"
    assert ctx["label"] == "Ne s'applique pas"


def test_calendrier_plafonnement_overlay_orange():
    ctx = calendrier_epandage(
        _regle(type="plafonnement", periodes=[{"du": "01/03", "au": "31/05"}])
    )
    assert len(ctx["segments"]) == 1
    assert ctx["segments"][0]["couleur"] == "orange"
    # Label unifie pour tous les types epandage (cf. UX 2026-05-12).
    assert ctx["label"] == "Calendrier d'épandage"


def test_calendrier_phenologique_dans_liste_a_part():
    """Une periode dont la borne est un evenement phenologique CONNU
    (avec date_calendrier dans referentiels.yaml) genere maintenant un
    vrai segment via la date conventionnelle (changement UX 2026-05-12 :
    on affiche les fenetres phenologiques en hachure orange dans la barre).
    Pour les evenements INCONNUS (typo, slug pas dans le referentiel), on
    fallback sur periodes_phenologiques (texte a part)."""
    # Evenement connu -> segment direct (sans liste phenologique).
    ctx = calendrier_epandage(
        _regle(
            type="interdiction",
            periodes=[{"du": "brunissement_des_soies", "au": "15/02"}],
        )
    )
    assert len(ctx["segments"]) >= 1
    assert ctx["segments"][0]["is_flottant"] is True

    # Evenement inconnu -> retombe sur periodes_phenologiques.
    ctx2 = calendrier_epandage(
        _regle(
            type="interdiction",
            periodes=[{"du": "evenement_inexistant", "au": "15/02"}],
        )
    )
    assert ctx2["segments"] == []
    assert len(ctx2["periodes_phenologiques"]) == 1


def test_calendrier_marqueur_today_present():
    """today_pct doit etre dans [0, 100]."""
    ctx = calendrier_epandage(_regle())
    assert 0 <= ctx["today_pct"] <= 100


def test_calendrier_today_pct_calcule_correctement():
    """En patchant la date du jour, on verifie le calcul du today_pct
    en annee agricole (juil = 0)."""
    with patch("envergo.nitrates.templatetags.nitrates_tags.date") as mock_date:
        mock_date.today.return_value = date(2026, 7, 1)  # 1er juillet
        ctx = calendrier_epandage(_regle())
        # 1er juillet = jour 0 de l'annee agricole
        assert ctx["today_pct"] == pytest.approx(0, abs=0.1)


def test_calendrier_bornes_pour_dates_limites():
    """Les bornes de chaque periode parsable sont exposees pour affichage."""
    ctx = calendrier_epandage(
        _regle(type="interdiction", periodes=[{"du": "15/12", "au": "15/01"}])
    )
    labels = [b["label"] for b in ctx["bornes"]]
    assert "15/12" in labels
    assert "15/01" in labels


def test_calendrier_a_completer_fond_gris():
    ctx = calendrier_epandage(_regle(type="a_completer", periodes=[]))
    assert ctx["fond"] == "gris"


def test_calendrier_calculatrice_orange():
    ctx = calendrier_epandage(_regle(type="calculatrice", periodes=[]))
    assert ctx["fond"] == "orange"
    assert ctx["label"] == "Calcul nécessaire"


def test_calendrier_12_mois_annee_agricole():
    """L'ordre des mois suit l'annee agricole (juil debut, juin fin)."""
    ctx = calendrier_epandage(_regle())
    assert len(ctx["mois"]) == 12
    assert ctx["mois"][0] == "Juil"
    assert ctx["mois"][-1] == "Juin"


def test_calendrier_regime_mixte_par_periode():
    """Une regle a regime mixte (cf. colza Type III note_5 du 30/04) :
    1ere periode `autorisation_sous_condition` (orange), 2e periode
    `interdiction` (rouge). Le `type` global de la regle est utilise
    comme fallback uniquement si la periode n'a pas de `regime`."""
    ctx = calendrier_epandage(
        _regle(
            type="interdiction",
            periodes=[
                {
                    "du": "01/09",
                    "au": "15/10",
                    "regime": "autorisation_sous_condition",
                },
                {"du": "15/10", "au": "15/01", "regime": "interdiction"},
            ],
        )
    )
    assert len(ctx["segments"]) == 2
    couleurs = [s["couleur"] for s in ctx["segments"]]
    assert couleurs == ["orange", "rouge"]


def test_calendrier_regime_periode_prime_sur_type_global():
    """Si une regle est de type `interdiction` mais qu'une de ses
    periodes a `regime: libre`, ce segment ne doit pas s'afficher
    (libre = etat de fond, pas d'overlay)."""
    ctx = calendrier_epandage(
        _regle(
            type="interdiction",
            periodes=[
                {"du": "01/09", "au": "15/10", "regime": "libre"},
                {
                    "du": "15/10",
                    "au": "15/01",
                },  # pas de regime -> fallback interdiction
            ],
        )
    )
    # 1 seul segment rouge (le 2e), pas de segment pour le 1er (libre)
    assert len(ctx["segments"]) == 1
    assert ctx["segments"][0]["couleur"] == "rouge"


# ─── est_interdit_toute_lannee (#85) ────────────────────────────────────────


def test_toute_lannee_vrai_pour_interdiction_01_07_30_06():
    r = _regle(type="interdiction", periodes=[{"du": "01/07", "au": "30/06"}])
    assert est_interdit_toute_lannee(r) is True


def test_toute_lannee_faux_pour_interdiction_hivernale():
    # Colza type_II : interdiction 15/12 -> 15/01, pas toute l'annee.
    r = _regle(type="interdiction", periodes=[{"du": "15/12", "au": "15/01"}])
    assert est_interdit_toute_lannee(r) is False


def test_toute_lannee_faux_si_regle_none():
    assert est_interdit_toute_lannee(None) is False


def test_toute_lannee_faux_si_autre_periode_presente():
    # Une interdiction pleine annee MAIS avec une autre periode -> pas "toute
    # l'annee" au sens simple (le calendrier nuance).
    r = _regle(
        type="mixte",
        periodes=[
            {"du": "01/07", "au": "30/06", "regime": "interdiction"},
            {"du": "15/12", "au": "15/01", "regime": "autorisation_sous_condition"},
        ],
    )
    assert est_interdit_toute_lannee(r) is False


def test_calendrier_borne_phenologique_label_resolu():
    """Le label du tick d'une borne phenologique est resolu vers son
    libelle_public lisible, pas le slug snake_case (#85)."""
    ctx = calendrier_epandage(
        _regle(
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
    )
    labels = [b["label"] for b in ctx["bornes"]]
    assert "Dernière coupe de la luzerne" in labels
    assert "derniere_coupe_luzerne" not in labels
