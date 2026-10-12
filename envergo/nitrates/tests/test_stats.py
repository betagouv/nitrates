"""Page statistiques (#517) : simulations lues dans Matomo, API mockée."""

from datetime import date
from unittest import mock

import pytest
import requests
from django.contrib.sites.models import Site
from django.core.cache import cache
from django.urls import reverse as _reverse

from envergo.contrib.middleware import PAGES_FOOTER_PUBLIQUES
from envergo.nitrates import stats_matomo
from envergo.nitrates.contenu_rich.loader import invalider_cache_contenu_rich
from envergo.nitrates.models import ContenuRichDSFR
from envergo.nitrates.stats_matomo import (
    StatsIndisponibles,
    parse_events,
    simulations_par_periode,
)
from envergo.nitrates.views_stats import _pas_axe, geometrie

pytestmark = pytest.mark.django_db


def reverse(nom):
    return _reverse(nom, urlconf="config.urls_nitrates")


# Extrait réel d'une réponse Events.getAction (site 276), nb_events tantôt
# en str, tantôt en int selon les lignes.
REPONSE_SEMAINES = {
    "2026-09-28,2026-10-04": [
        {"label": "SimulationLancee", "nb_events": "2", "nb_visits": "1"},
    ],
    "2026-10-05,2026-10-11": [
        {"label": "RechercheCommune", "nb_events": "2", "nb_visits": "1"},
        {"label": "SimulationLancee", "nb_events": 6, "nb_visits": "2"},
    ],
    "2026-10-12,2026-10-18": [],
}


@pytest.fixture(autouse=True)
def matomo(settings):
    settings.ANALYTICS = {
        **settings.ANALYTICS,
        "NITRATES": {
            "TRACKER_ENABLED": False,
            "TRACKER_URL": "https://stats.example/",
            "SITE_ID": "276",
            "SECURITY_TOKEN": "jeton-lecture",
        },
    }
    settings.NITRATES_STATS_DATE_DEBUT = ""
    cache.clear()
    invalider_cache_contenu_rich()
    yield
    cache.clear()
    invalider_cache_contenu_rich()


@pytest.fixture
def nitrates_site(settings):
    settings.ENVERGO_NITRATES_DOMAIN = "testserver"
    site, _ = Site.objects.get_or_create(domain="testserver")
    return site


def _reponse(json_data):
    r = mock.Mock()
    r.json.return_value = json_data
    r.raise_for_status.return_value = None
    return r


def test_parse_semaines_somme_seulement_simulations():
    points = parse_events(REPONSE_SEMAINES, "week")
    assert [p.simulations for p in points] == [2, 6, 0]
    assert points[0].debut == date(2026, 9, 28)
    assert points[1].libelle == "05/10"
    assert points[1].libelle_long == "semaine du 5 oct. 2026"


def test_parse_mois_trie():
    data = {
        "2026-10": [{"label": "SimulationLancee", "nb_events": "46"}],
        "2026-09": [],
    }
    points = parse_events(data, "month")
    assert [(p.libelle, p.simulations) for p in points] == [
        ("sept. 26", 0),
        ("oct. 26", 46),
    ]


def test_parse_erreur_matomo():
    with pytest.raises(StatsIndisponibles):
        parse_events({"result": "error", "message": "accès view requis"}, "week")


def test_token_en_post_et_plage_depuis_date_debut(settings):
    settings.NITRATES_STATS_DATE_DEBUT = "2026-10-05"
    with mock.patch.object(
        stats_matomo.requests, "post", return_value=_reponse(REPONSE_SEMAINES)
    ) as post:
        simulations_par_periode("week")
    url = post.call_args.args[0]
    data = post.call_args.kwargs["data"]
    assert url == "https://stats.example/index.php"
    assert "jeton" not in url
    assert data["token_auth"] == "jeton-lecture"
    assert data["idSite"] == "276"
    assert data["date"] == "2026-10-05,today"
    assert data["method"] == "Events.getAction"


def test_cache_evite_second_appel():
    with mock.patch.object(
        stats_matomo.requests, "post", return_value=_reponse(REPONSE_SEMAINES)
    ) as post:
        simulations_par_periode("week")
        simulations_par_periode("week")
    assert post.call_count == 1


def test_repli_sur_derniere_valeur_si_matomo_tombe():
    with mock.patch.object(
        stats_matomo.requests, "post", return_value=_reponse(REPONSE_SEMAINES)
    ):
        premiers = simulations_par_periode("week")
    # le cache court expire, Matomo ne répond plus
    cache.delete(f"nitrates_stats:276:week:last{stats_matomo.NB_PERIODES_PAR_DEFAUT}")
    with mock.patch.object(
        stats_matomo.requests, "post", side_effect=requests.ConnectionError("down")
    ):
        assert simulations_par_periode("week") == premiers


def test_sans_token_pas_d_appel(settings):
    settings.ANALYTICS["NITRATES"]["SECURITY_TOKEN"] = ""
    with mock.patch.object(stats_matomo.requests, "post") as post:
        assert simulations_par_periode("week") is None
    post.assert_not_called()


@pytest.mark.parametrize("maximum,pas", [(0, 1), (3, 1), (7, 2), (46, 20), (180, 50)])
def test_pas_axe_rond(maximum, pas):
    assert _pas_axe(maximum) == pas


def test_geometrie_barres_dans_le_cadre():
    g = geometrie(parse_events(REPONSE_SEMAINES, "week"))
    assert len(g["barres"]) == 3
    for b in g["barres"]:
        assert b["x"] >= g["x_axe"]
        assert b["x"] + b["largeur"] <= g["largeur"]
        assert b["y"] + b["hauteur"] == pytest.approx(g["y_base"], abs=0.2)
    assert g["barres"][2]["hauteur"] == 0
    # max 6, pas 2 -> l'axe s'arrête à 6, pas au-delà
    assert g["graduations"][-1]["valeur"] == 6


def test_page_rendue_avec_graphe_et_tableau(client, nitrates_site):
    assert ContenuRichDSFR.objects.filter(cle="page.stats").exists()
    with mock.patch.object(
        stats_matomo.requests, "post", return_value=_reponse(REPONSE_SEMAINES)
    ):
        response = client.get(reverse("nitrates_stats"))
    assert response.status_code == 200
    html = response.content.decode()
    assert "<h1>Statistiques</h1>" in html
    assert "nombre de simulations effectuées" in html  # texte page.stats
    assert "<svg" in html
    assert "<caption>Données du graphique</caption>" in html
    assert "Semaine du 5 oct. 2026" in html
    assert 'aria-current="true">Par semaine' in html
    # coordonnees SVG jamais localisees (212,0 casse le dessin)
    assert 'y1="212,0"' not in html
    assert "semaine du 12 oct. 2026 : 0 simulation<" in html


def test_page_par_mois(client, nitrates_site):
    data = {"2026-10": [{"label": "SimulationLancee", "nb_events": "46"}]}
    with mock.patch.object(
        stats_matomo.requests, "post", return_value=_reponse(data)
    ) as post:
        html = client.get(reverse("nitrates_stats") + "?periode=mois").content.decode()
    assert post.call_args.kwargs["data"]["period"] == "month"
    assert "Oct. 2026" in html
    assert "46" in html


def test_page_matomo_indisponible_pas_de_500(client, nitrates_site):
    with mock.patch.object(
        stats_matomo.requests, "post", side_effect=requests.Timeout("lent")
    ):
        response = client.get(reverse("nitrates_stats"))
    assert response.status_code == 200
    assert "momentanément indisponibles" in response.content.decode()


def test_page_publique_en_lockdown(client, nitrates_site, settings):
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = False
    assert reverse("nitrates_stats") in PAGES_FOOTER_PUBLIQUES
    with mock.patch.object(
        stats_matomo.requests, "post", return_value=_reponse(REPONSE_SEMAINES)
    ):
        response = client.get(reverse("nitrates_stats"))
    assert response.status_code == 200


def test_lien_footer(client, nitrates_site):
    with mock.patch.object(
        stats_matomo.requests, "post", return_value=_reponse(REPONSE_SEMAINES)
    ):
        html = client.get(reverse("nitrates_cgu")).content.decode()
    assert f'href="{reverse("nitrates_stats")}">Statistiques</a>' in html


def test_stats_dans_sitemap(client, nitrates_site):
    html = client.get("/sitemap.xml").content.decode()
    assert "/stats/" in html
