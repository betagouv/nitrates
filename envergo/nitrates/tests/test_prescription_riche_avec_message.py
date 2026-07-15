"""Regression #216 : le contenu riche d'une PC (blocs) doit s'afficher meme
quand la regle porte un `message` narratif.

Cas signale (CIE courte types 0/I/II) : regle type=libre avec message +
code_prescription pc15. Avant le fix, la condition `not ev.regle.message`
sautait TOUT le bloc PC -> la fiche PC15 (detail du plafond 70 kg N/ha) ne
s'affichait pas. Le fix affiche toujours les blocs riches ; seul le fallback
`texte_court` lapidaire (ex pc5) reste masque en presence d'un message.
"""

from types import SimpleNamespace

import pytest
from django.template.loader import render_to_string

pytestmark = pytest.mark.django_db


def _contexte(regle, pc_par_code):
    """Contexte minimal pour rendre _panneau_resultat.html avec un seul
    evenement resolu (ev.regle) + le dict codes_prescription."""
    ev = SimpleNamespace(
        regle=regle,
        result="autorise",
        catalogue_manquant=None,
    )
    entry = SimpleNamespace(criterion=None, evaluator=ev)
    moulinette = SimpleNamespace(catalog={"en_zone_vulnerable": True, "en_zar": False})
    return {
        "regulations_evaluees": [entry],
        "codes_prescription": pc_par_code,
        "notes_referentiel": {},
        "moulinette": moulinette,
        "debug": False,
    }


def _regle(**kw):
    base = dict(
        id="r_test",
        type="libre",
        message=None,
        codes_prescription=[],
        note=None,
        texte=None,
        composant=None,
        plafond_azote_kg_n_ha=None,
        a_completer=False,
        periodes=[{"du": "01/07", "au": "30/06", "regime": "libre"}],
    )
    base.update(kw)
    return SimpleNamespace(**base)


PC_RICHE = SimpleNamespace(
    identifiant="pc15",
    mots_cles="Plafond CIE courte",
    texte_court="Cumul de 70 kg d'azote par hectare.",
    texte_redaction_initiale="Detail...",
    blocs={
        "blocs": [{"type": "titre_principal", "data": {"texte": "MARQUEUR_BLOC_RICHE"}}]
    },
)
PC_LAPIDAIRE = SimpleNamespace(
    identifiant="pc5",
    mots_cles="Engrais mineraux",
    texte_court="MARQUEUR_TEXTE_COURT_LAPIDAIRE",
    texte_redaction_initiale=None,
    blocs=None,
)


def test_blocs_riches_affiches_meme_avec_message():
    """Regle avec message + PC riche -> les blocs s'affichent (fix #216)."""
    regle = _regle(
        message="Couvert d'interculture courte exporte.", codes_prescription=["pc15"]
    )
    html = render_to_string(
        "nitrates/fragments/_panneau_resultat.html",
        _contexte(regle, {"pc15": PC_RICHE}),
    )
    assert (
        "MARQUEUR_BLOC_RICHE" in html
    ), "les blocs riches de la PC doivent s'afficher malgre le message de la regle"


def test_texte_court_lapidaire_masque_si_message():
    """Regle avec message + PC SANS blocs (pc5) -> le texte_court lapidaire
    reste masque (anti-doublon preserve)."""
    regle = _regle(
        type="libre",
        message="Apport d'engrais mineraux autorise (message narratif).",
        codes_prescription=["pc5"],
    )
    html = render_to_string(
        "nitrates/fragments/_panneau_resultat.html",
        _contexte(regle, {"pc5": PC_LAPIDAIRE}),
    )
    assert (
        "MARQUEUR_TEXTE_COURT_LAPIDAIRE" not in html
    ), "le texte_court lapidaire ne doit pas doublonner le message de la regle"


def test_texte_court_affiche_si_pas_de_message():
    """Sans message, le texte_court d'une PC sans blocs s'affiche (comportement
    historique inchange)."""
    regle = _regle(type="libre", message=None, codes_prescription=["pc5"])
    html = render_to_string(
        "nitrates/fragments/_panneau_resultat.html",
        _contexte(regle, {"pc5": PC_LAPIDAIRE}),
    )
    assert "MARQUEUR_TEXTE_COURT_LAPIDAIRE" in html
