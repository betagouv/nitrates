"""Récapitulatif des questions complémentaires déjà répondues (panneau de
gauche du simulateur, #271 / #408)."""

from urllib.parse import urlencode

import pytest

from envergo.nitrates.tests.test_moulinette_view import (  # noqa: F401
    nitrates_site,
    setup_geodata,
)

pytestmark = pytest.mark.django_db

PARCOURS = {
    "lng": "4.0345",
    "lat": "49.2583",
    "occupation_sol": "culture_principale",
    "sous_culture": "culture_printemps",
    "type_fertilisant": "type_II",
}


def _get(client, **reponses):
    return client.get("/simulateur/?" + urlencode(dict(PARCOURS, **reponses)))


def test_qc_en_attente_pas_encore_dans_le_recap(
    client, nitrates_site, setup_geodata  # noqa: F811
):
    r = _get(client)
    assert r.context["qc_actifs"] == ["fertirrigation"]
    assert r.context["qc_repondues"] == []


@pytest.mark.parametrize("valeur", ["true", "True"])
def test_qc_repondue_dans_le_recap_avec_son_libelle(
    client, nitrates_site, setup_geodata, valeur  # noqa: F811
):
    r = _get(client, fertirrigation=valeur)

    assert "fertirrigation" not in r.context["qc_actifs"]
    recap = {q["champ"]: q for q in r.context["qc_repondues"]}
    assert "fertirrigation" in recap
    qc = recap["fertirrigation"]
    assert qc["valeur"] == valeur
    # #408 : un booléen arrivé en minuscules dans l'URL retrouve le libellé du
    # choix, au lieu d'afficher la valeur brute « true ».
    assert qc["libelle"] != valeur
    assert qc["libelle"] in {c["libelle"] for c in qc["choix"]}
    assert all(isinstance(c["valeur"], str) for c in qc["choix"])
    assert r.context["qc_repondues_champs"] == list(recap)
