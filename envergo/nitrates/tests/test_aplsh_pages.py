"""Tests des pages POC APLSH / Météo (seed, calculette, tableau météo).

Les API externes (Open-Meteo, SoilGrids) sont simulées.
"""

from datetime import date, timedelta
from unittest import mock

import pytest
from django.core.management import call_command
from django.urls import reverse

from envergo.nitrates import meteo_aplsh
from envergo.nitrates.models_aplsh import ReferentielAPLSH
from envergo.nitrates.views_admin_aplsh import AUTRE_PRODUIT, PRODUIT_MINERAL

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_nitrates")]


@pytest.fixture(autouse=True)
def poc_actif(settings):
    settings.NITRATES_POC_APLSH = True
    meteo_aplsh._cache.clear()
    yield
    meteo_aplsh._cache.clear()


@pytest.fixture
def referentiels():
    call_command("seed_aplsh")
    return {r.region_code: r for r in ReferentielAPLSH.objects.all()}


@pytest.fixture
def staff_client(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        email="staff-poc@example.org", password="x", name="Staff"
    )
    client.force_login(user)
    return client


def _previsions(pluie=0.5, temp=8.0, vent=12.0):
    debut = date.today()
    heures = [
        f"{debut + timedelta(days=j)}T{h:02d}:00" for j in range(11) for h in range(24)
    ]
    jours = [str(debut + timedelta(days=j)) for j in range(11)]
    hourly = {"time": heures}
    daily = {"time": jours}
    for m in meteo_aplsh.MODELES:
        hourly[f"temperature_2m_{m}"] = [temp - (i % 24 < 6) * 9 for i in range(264)]
        hourly[f"precipitation_{m}"] = [pluie * (i % 7 == 0) for i in range(264)]
        hourly[f"wind_speed_10m_{m}"] = [vent + i % 10 for i in range(264)]
        daily[f"sunrise_{m}"] = [f"{j}T07:50" for j in jours]
        daily[f"sunset_{m}"] = [f"{j}T18:40" for j in jours]
    return {"hourly": hourly, "daily": daily}


def _sol(ph=65, argile=250, sable=300):
    valeurs = {"phh2o": ph, "clay": argile, "sand": sable, "soc": 150}
    return {
        "properties": {
            "layers": [
                {"name": k, "depths": [{"values": {"mean": v}}]}
                for k, v in valeurs.items()
            ]
        }
    }


def _faux_get(previsions=None, sol=None):
    def get(url, params=None, timeout=None):
        reponse = mock.Mock()
        reponse.raise_for_status.return_value = None
        if "isric" in url:
            reponse.json.return_value = sol or _sol()
        else:
            reponse.json.return_value = previsions or _previsions()
        return reponse

    return get


# ─── Seed ─────────────────────────────────────────────────────────────────


def test_seed_idempotent(referentiels):
    assert set(referentiels) == {"32", "44"}
    assert referentiels["44"].tableau_produits_parse
    assert referentiels["44"].tableau_generique_parse
    call_command("seed_aplsh")
    assert ReferentielAPLSH.objects.count() == 2


def test_produits_tries_avec_libelle(referentiels):
    produits = referentiels["44"].produits()
    libelles = [p["libelle"].lower() for p in produits]
    assert libelles == sorted(libelles)
    assert str(referentiels["44"])


# ─── Calculette ───────────────────────────────────────────────────────────


def test_calculette_sans_referentiel(staff_client):
    response = staff_client.get(reverse("nitrates_admin_aplsh_index"))
    assert response.status_code == 200
    assert "seed_aplsh" in response.content.decode()


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"produit": "0", "date_apport": "2026-08-15", "dose": "20"},
        {"produit": "0", "date_apport": "2026-10-15", "dose": "500"},
        {"produit": AUTRE_PRODUIT, "cn": "12", "nmin_ntot": "40", "n_total": "6"},
        {"produit": AUTRE_PRODUIT},
        {"produit": PRODUIT_MINERAL, "n_total": "335", "date_apport": "bidon"},
        {"produit": PRODUIT_MINERAL},
    ],
)
def test_calculette_grand_est(staff_client, referentiels, params):
    params = {"referentiel": referentiels["44"].pk, **params}
    response = staff_client.get(reverse("nitrates_admin_aplsh_index"), params)
    assert response.status_code == 200


@pytest.mark.parametrize("produit", ["0", "3"])
def test_calculette_hdf_sans_teneur(staff_client, referentiels, produit):
    # HdF ne publie pas les teneurs N : la page propose une fourchette.
    params = {"referentiel": referentiels["32"].pk, "produit": produit}
    response = staff_client.get(reverse("nitrates_admin_aplsh_index"), params)
    assert response.status_code == 200


# ─── Météo ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"produit": "0", "modele": "moyenne"},
        {"produit": "5", "modele": "inconnu"},
        {"produit": PRODUIT_MINERAL, "forme": "uree_solide"},
        {"produit": PRODUIT_MINERAL, "forme": "bidon"},
        {"sol_argile": "50", "sol_sable": "20", "sol_ph": "8"},
        {"lat": "49.5", "lon": "3.1", "sol_argile": "5", "sol_sable": "80"},
    ],
)
def test_page_meteo(staff_client, referentiels, params):
    params = {"referentiel": referentiels["44"].pk, **params}
    with mock.patch.object(meteo_aplsh.requests, "get", _faux_get()):
        response = staff_client.get(reverse("nitrates_admin_meteo_index"), params)
    assert response.status_code == 200


def test_page_meteo_api_injoignable(staff_client):
    with mock.patch.object(
        meteo_aplsh.requests, "get", side_effect=ConnectionError("down")
    ):
        response = staff_client.get(reverse("nitrates_admin_meteo_index"))
    assert response.status_code == 200


def test_tableau_meteo_scores():
    with mock.patch.object(meteo_aplsh.requests, "get", _faux_get()):
        tableau = meteo_aplsh.tableau_meteo(48.7, 5.6, "sensible")
    assert len(tableau["jours"]) == 7
    assert tableau["meilleur"]["heure"] in meteo_aplsh.HEURES_VERDICT
    tranche = tableau["jours"][0]["tranches"][0]
    assert tranche["gel"] is True
    assert tranche["scores"]["ruissellement"] == 0.0
    assert tableau["jours"][0]["soleil"] == "07:50 → 18:40"


@pytest.mark.parametrize(
    "sol, texture, note_ph",
    [
        ({"ph": 8.0, "argile": 50, "sable": 10}, "argileux", 3),
        ({"ph": 7.2, "argile": 5, "sable": 80}, "sableux", 2),
        ({"ph": 6.0, "argile": 10, "sable": 10}, "limoneux", 0),
        (None, "franc", 0),
    ],
)
def test_tableau_meteo_selon_sol(sol, texture, note_ph):
    previsions = _previsions(pluie=12, temp=14)
    with mock.patch.object(meteo_aplsh.requests, "get", _faux_get(previsions)):
        tableau = meteo_aplsh.tableau_meteo(48.7, 5.6, "modere", "icon_seamless", sol)
    tranche = tableau["jours"][1]["tranches"][4]
    assert tranche["texture"] == texture
    assert tranche["note_ph"] == note_ph


def test_tableau_meteo_previsions_vides():
    previsions = _previsions()
    previsions["hourly"]["time"] = previsions["hourly"]["time"][:10]
    with mock.patch.object(meteo_aplsh.requests, "get", _faux_get(previsions)):
        assert "erreur" in meteo_aplsh.tableau_meteo(48.7, 5.6)


def test_sol_au_point():
    with mock.patch.object(meteo_aplsh.requests, "get", _faux_get()) as _:
        sol = meteo_aplsh.sol_au_point(48.7, 5.6)
    assert sol == {"ph": 6.5, "argile": 25.0, "sable": 30.0, "carbone": 15.0}
    # Deuxième appel servi par le cache, sans réseau.
    with mock.patch.object(meteo_aplsh.requests, "get", side_effect=AssertionError):
        assert meteo_aplsh.sol_au_point(48.7, 5.6) == sol


def test_sol_au_point_valeur_manquante():
    reponse = _sol()
    reponse["properties"]["layers"][0]["depths"][0]["values"]["mean"] = None
    with mock.patch.object(meteo_aplsh.requests, "get", _faux_get(sol=reponse)):
        assert meteo_aplsh.sol_au_point(45.0, 1.0) is None
