"""Tests de la sonde d'observabilite infra (carte #111).

L'enjeu principal est le controle d'acces : la sonde expose des metriques
d'infrastructure, elle ne doit repondre qu'avec le bon jeton, et rester
totalement absente quand aucun jeton n'est configure.
"""

import pytest
from django.test import Client
from django.urls import NoReverseMatch, reverse

pytestmark = pytest.mark.django_db

TOKEN = "jeton-de-test-111"


@pytest.fixture
def probe_client(settings):
    settings.NITRATES_PROBE_TOKEN = TOKEN
    return Client()


def _probe_url(settings):
    """La route n'est montee qu'au chargement des URLs, quand un jeton existe.

    En test, `NITRATES_PROBE_TOKEN` est vide au moment ou config.urls est
    importe : on cible donc le chemin en dur plutot que par reverse().
    """
    try:
        return reverse("nitrates_probe_now")
    except NoReverseMatch:
        return "/_probe/now/"


def test_sonde_refuse_sans_jeton(probe_client, settings):
    r = probe_client.get(_probe_url(settings))
    # 404 et pas 403 : on ne revele pas l'existence de l'endpoint.
    assert r.status_code == 404


def test_sonde_refuse_mauvais_jeton(probe_client, settings):
    r = probe_client.get(_probe_url(settings), {"token": "pas-le-bon"})
    assert r.status_code == 404


def test_sonde_refuse_quand_aucun_jeton_configure(settings):
    settings.NITRATES_PROBE_TOKEN = ""
    # Meme en presentant un jeton vide, rien ne doit repondre.
    r = Client().get(_probe_url(settings), {"token": ""})
    assert r.status_code == 404


def test_collect_retourne_les_metriques_attendues():
    from envergo.nitrates.probe import collect

    d = collect()
    assert {"ts", "memory", "pressure", "cpu", "process", "latency_ms"} <= set(d)
    # Ces clefs doivent exister meme si le noyau ne les renseigne pas (None) :
    # c'est ce qui rend le JSON exploitable par le dashboard sans garde partout.
    assert "pgmajfault" in d["memory"]
    assert "swap_current" in d["memory"]
    assert {"memory", "cpu", "io"} <= set(d["pressure"])
    assert "disk_read" in d["latency_ms"]


def test_collect_ne_leve_pas_si_cgroup_absent(monkeypatch):
    """Sur un hote sans cgroup v2 (macOS, CI exotique), la sonde degrade
    en None plutot que de casser la page."""
    import envergo.nitrates.probe as probe

    monkeypatch.setattr(probe, "CGROUP", "/chemin/qui/nexiste/pas")
    d = probe.collect()
    assert d["memory"]["current"] is None
    assert d["pressure"]["memory"] == {}
