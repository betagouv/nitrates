"""Vues de la sonde infra (carte #111), appelées directement.

La route `/_probe/` n'est montée que si un jeton existe au chargement des
URLs, ce qui n'est pas le cas en test : passer par le client HTTP renverrait
un 404 de routage, pas celui de la vue. On teste donc les vues elles-mêmes.
"""

import json

import pytest
from django.test import RequestFactory

from envergo.nitrates import views_probe

TOKEN = "jeton-de-test-111"


@pytest.fixture(autouse=True)
def jeton(settings, monkeypatch):
    settings.NITRATES_PROBE_TOKEN = TOKEN
    monkeypatch.setattr(views_probe, "collect", lambda: {"container": "web-1"})


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.mark.parametrize("vue", [views_probe.probe_now, views_probe.probe_dash])
def test_jeton_absent_ou_faux_404(rf, vue):
    assert vue(rf.get("/")).status_code == 404
    assert vue(rf.get("/", {"token": "faux"})).status_code == 404


@pytest.mark.parametrize("vue", [views_probe.probe_now, views_probe.probe_dash])
def test_aucun_jeton_configure_404_meme_avec_jeton_vide(rf, settings, vue):
    settings.NITRATES_PROBE_TOKEN = ""
    assert vue(rf.get("/", {"token": ""})).status_code == 404


def test_probe_now_par_parametre_ou_entete(rf):
    r = views_probe.probe_now(rf.get("/", {"token": TOKEN}))
    assert json.loads(r.content) == {"container": "web-1"}
    r = views_probe.probe_now(rf.get("/", HTTP_X_PROBE_TOKEN=TOKEN))
    assert r.status_code == 200
    assert "no-cache" in r["Cache-Control"]


def test_probe_dash_rend_la_page_avec_le_jeton(rf):
    r = views_probe.probe_dash(rf.get("/", {"token": TOKEN}))
    assert r["Content-Type"].startswith("text/html")
    assert f"const TOKEN = {json.dumps(TOKEN)};" in r.content.decode()


def test_probe_dash_sert_le_json_a_lui_meme(rf):
    r = views_probe.probe_dash(rf.get("/", {"token": TOKEN, "json": "1"}))
    assert json.loads(r.content) == {"container": "web-1"}
