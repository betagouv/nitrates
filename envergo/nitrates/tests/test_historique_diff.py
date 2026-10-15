"""Mise à plat, différences et annulation ligne à ligne (historique_diff)."""

import copy
import json
from pathlib import Path

import pytest

from envergo.nitrates.historique_diff import (
    Conflit,
    annuler,
    differences,
    libelle,
    lignes_annulables,
    lineariser,
    reconstruire,
)

# Logique pure, mais marqué django_db comme le reste de la suite : sans test
# en base, pytest-django ne bascule pas sur la base de test et les fixtures
# automatiques du projet toucheraient la base réelle.
pytestmark = pytest.mark.django_db

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "initial_referentiels.json"

PRINCIPE = {"type": "titre_paragraphe", "data": {"texte": "Le principe"}}
VOLET = {
    "type": "foldable",
    "data": {
        "titre": "Précisions sur le suivi",
        "blocs": [
            {"type": "titre_paragraphe", "data": {"texte": "Le protocole"}},
            {
                "type": "liste",
                "data": {"items": [{"texte": "céréales"}, {"texte": "oléagineux"}]},
            },
        ],
    },
}


def liste(*items):
    return {"type": "liste", "data": {"items": list(items)}}


AVEC_SOUS_PUCES = liste(
    {
        "texte": "les conditions du PAR, notamment sur :",
        "enfants": [{"texte": "la durée du couvert"}, {"texte": "le plafonnement"}],
    },
    {"texte": "un dispositif de suivi"},
)
SANS_SOUS_PUCES = liste(
    {"texte": "les conditions du PAR, notamment sur :"},
    {"texte": "un dispositif de suivi"},
)


def ops(lignes, genre=None):
    return [
        lg["op"]
        for lg in lignes
        if lg["op"] and (genre is None or lg["genre"] == genre)
    ]


def test_mise_a_plat_reversible_sur_toute_la_fixture():
    n = 0
    for o in json.loads(FIXTURE.read_text()):
        blocs = o["fields"].get("blocs") or {}
        blocs = blocs.get("blocs") if isinstance(blocs, dict) else blocs
        if blocs:
            n += 1
            assert reconstruire(lineariser(blocs)) == blocs, o["fields"].get(
                "identifiant"
            )
    assert n > 40


def test_differences_ajout_retrait_modif():
    base = [
        PRINCIPE,
        {
            "type": "paragraphe",
            "data": {"texte": "L'épandage est autorisé, le cas échéant."},
        },
        AVEC_SOUS_PUCES,
    ]
    cible = [
        PRINCIPE,
        {
            "type": "paragraphe",
            "data": {"texte": "L'épandage est autorisé, sous condition."},
        },
        SANS_SOUS_PUCES,
    ]
    _, _, lignes = differences(base, cible)
    genres = [lg["genre"] for lg in lignes if lg["genre"] != "egal"]
    assert genres == ["modif", "retrait", "retrait"]


def test_annuler_la_perte_des_sous_puces():
    base, cible = [PRINCIPE, AVEC_SOUS_PUCES], [PRINCIPE, SANS_SOUS_PUCES]
    _, _, lignes = differences(base, cible)
    assert annuler(base, cible, cible, ops(lignes)) == base


def test_annuler_une_seule_ligne():
    base, cible = [PRINCIPE, AVEC_SOUS_PUCES], [PRINCIPE, SANS_SOUS_PUCES]
    ub, _, lignes = differences(base, cible)
    premiere = next(lg for lg in lignes if lg["genre"] == "retrait")
    resultat = annuler(base, cible, cible, [premiere["op"]])
    assert resultat[1]["data"]["items"][0]["enfants"] == [
        {"texte": "la durée du couvert"}
    ]


def test_patch_inverse_sur_une_version_qui_a_evolue_depuis():
    base = [PRINCIPE, {"type": "paragraphe", "data": {"texte": "Ancien titre"}}]
    cible = [PRINCIPE, {"type": "paragraphe", "data": {"texte": "Nouveau titre"}}]
    actuel = copy.deepcopy(cible) + [
        {"type": "paragraphe", "data": {"texte": "Ajouté plus tard"}}
    ]
    _, _, lignes = differences(base, cible)
    assert annuler(base, cible, actuel, ops(lignes)) == base + [actuel[-1]]


def test_conflit_si_la_ligne_a_change_depuis():
    base = [PRINCIPE, {"type": "paragraphe", "data": {"texte": "Version 1"}}]
    cible = [PRINCIPE, {"type": "paragraphe", "data": {"texte": "Version 2"}}]
    actuel = [
        PRINCIPE,
        {"type": "paragraphe", "data": {"texte": "Version 3, réécrite depuis"}},
    ]
    _, _, lignes = lignes_annulables(base, cible, actuel)
    modif = next(lg for lg in lignes if lg["genre"] == "modif")
    assert modif["annulable"] is False
    with pytest.raises(Conflit):
        annuler(base, cible, actuel, [modif["op"]])


def test_annuler_la_suppression_d_un_volet_le_restaure_en_entier():
    base, cible = [PRINCIPE, VOLET], [PRINCIPE]
    ub, _, lignes = differences(base, cible)
    titre = next(
        lg
        for lg in lignes
        if lg["genre"] == "retrait" and ub[lg["base"]]["k"] == "volet"
    )
    assert annuler(base, cible, cible, [titre["op"]]) == base


def test_annuler_l_ajout_d_un_volet_le_retire_en_entier():
    base, cible = [PRINCIPE], [PRINCIPE, VOLET]
    _, uc, lignes = differences(base, cible)
    titre = next(
        lg
        for lg in lignes
        if lg["genre"] == "ajout" and uc[lg["cible"]]["k"] == "volet"
    )
    assert annuler(base, cible, cible, [titre["op"]]) == base


def test_enveloppe_schema_conservee():
    base = {"schema": 1, "blocs": [PRINCIPE, AVEC_SOUS_PUCES]}
    cible = {"schema": 1, "blocs": [PRINCIPE, SANS_SOUS_PUCES]}
    _, _, lignes = differences(base, cible)
    assert annuler(base, cible, cible, ops(lignes)) == base


def test_libelles_lisibles():
    u = lineariser([AVEC_SOUS_PUCES])
    textes = [libelle(x).strip() for x in u if x["k"] == "item"]
    assert textes == [
        "• les conditions du PAR, notamment sur :",
        "◦ la durée du couvert",
        "◦ le plafonnement",
        "• un dispositif de suivi",
    ]


def test_retrait_deja_retabli_n_est_pas_annulable():
    base, cible = [PRINCIPE, AVEC_SOUS_PUCES], [PRINCIPE, SANS_SOUS_PUCES]
    actuel = [PRINCIPE, AVEC_SOUS_PUCES]  # sous-puces remises depuis
    _, _, lignes = lignes_annulables(base, cible, actuel)
    retraits = [lg for lg in lignes if lg["genre"] == "retrait"]
    assert retraits and all(lg["deja"] and not lg["annulable"] for lg in retraits)
    with pytest.raises(Conflit):
        annuler(base, cible, actuel, [lg["op"] for lg in retraits])


def test_deux_phrases_differentes_ne_sont_pas_une_modification():
    fragment = (
        "70 kg d'azote potentiellement libéré jusqu'en sortie d'hiver par hectare"
    )
    avertissement = (
        f"⚠️ Ces apports comptent dans le plafond sur couvert, fixé à {fragment}."
    )
    base = [{"type": "paragraphe", "data": {"texte": avertissement}}]
    cible = [{"type": "paragraphe", "data": {"texte": f"{fragment} au total."}}]
    _, _, lignes = differences(base, cible)
    assert [lg["genre"] for lg in lignes] == ["retrait", "ajout"]


def test_une_reformulation_reste_une_modification():
    base = [
        {
            "type": "titre_principal",
            "data": {
                "texte": "Plafonnement annuel des apports azotés sur l'année d'implantation du couvert d'interculture"
            },
        }
    ]
    cible = [
        {
            "type": "titre_principal",
            "data": {
                "texte": "Plafonnement des apports azotés pour les couverts d'interculture"
            },
        }
    ]
    _, _, lignes = differences(base, cible)
    assert [lg["genre"] for lg in lignes] == ["modif"]
