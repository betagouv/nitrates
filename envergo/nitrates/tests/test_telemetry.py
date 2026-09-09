"""Tests de la telemetrie infra continue (carte #111).

L'enjeu : cette boucle tourne dans chaque worker web en production. Elle doit
etre desactivee par defaut, ne jamais lever, et ne jamais empecher un worker
de demarrer ou de s'arreter.
"""

import pytest

from envergo.nitrates import telemetry


@pytest.fixture(autouse=True)
def _reset_started():
    """Le module garde un drapeau global d'idempotence : on le remet a zero
    entre les tests, sinon le premier demarrage masque tous les suivants."""
    telemetry._started = False
    yield
    telemetry._started = False


def test_desactive_par_defaut(settings):
    settings.NITRATES_TELEMETRY_INTERVAL = 0
    telemetry.start()
    assert telemetry._started is False


def test_intervalle_negatif_ne_demarre_pas(settings):
    settings.NITRATES_TELEMETRY_INTERVAL = -5
    telemetry.start()
    assert telemetry._started is False


def test_demarre_un_thread_daemon(settings):
    import threading

    settings.NITRATES_TELEMETRY_INTERVAL = 3600  # assez long pour ne pas boucler
    telemetry.start()
    assert telemetry._started is True
    t = [x for x in threading.enumerate() if x.name == "nitrates-infra-telemetry"]
    assert len(t) == 1
    # daemon : ne doit pas retenir l'arret du worker gunicorn.
    assert t[0].daemon is True


def test_idempotent(settings):
    """Plusieurs appels a start() ne doivent lancer qu'un seul thread.

    On compte les threads crees pendant CE test : le fixture remet le drapeau
    a zero mais ne peut pas tuer les threads des tests precedents (ils sont
    daemon et dorment une heure), donc un comptage global serait fausse.
    """
    import threading

    avant = {
        id(x) for x in threading.enumerate() if x.name == "nitrates-infra-telemetry"
    }
    settings.NITRATES_TELEMETRY_INTERVAL = 3600
    telemetry.start()
    telemetry.start()
    telemetry.start()
    apres = {
        id(x) for x in threading.enumerate() if x.name == "nitrates-infra-telemetry"
    }
    assert len(apres - avant) == 1


def test_emit_ne_leve_pas_sur_snapshot_incomplet():
    """Un snapshot degrade (cgroup absent, valeurs None) ne doit pas casser
    la boucle : elle tourne dans un worker qui sert du trafic."""
    telemetry._emit({})
    telemetry._emit({"memory": {}, "pressure": {}, "cpu": {}, "latency_ms": {}})
    telemetry._emit(
        {
            "container": None,
            "memory": {"current": None, "pgmajfault": None},
            "pressure": {"memory": {}},
            "cpu": {"nr_throttled": None},
            "latency_ms": {"disk_read": None},
        }
    )


def test_emit_envoie_les_metriques_attendues(monkeypatch):
    envoye = []

    class FakeMetrics:
        @staticmethod
        def gauge(name, value, **kwargs):
            envoye.append(("gauge", name, value))

        @staticmethod
        def distribution(name, value, **kwargs):
            envoye.append(("distribution", name, value))

        @staticmethod
        def count(name, value, **kwargs):
            envoye.append(("count", name, value))

    import sentry_sdk

    monkeypatch.setattr(sentry_sdk, "metrics", FakeMetrics, raising=False)

    telemetry._emit(
        {
            "container": "web-1",
            "memory": {"current": 100, "swap_current": 50, "pgmajfault": 7},
            "pressure": {"memory": {"some": {"avg10": 1.5}}},
            "cpu": {"nr_throttled": 2},
            "latency_ms": {"disk_read": 0.5, "db_roundtrip": 12.0},
        }
    )

    noms = {n for _, n, _ in envoye}
    assert "infra.memory.current" in noms
    assert "infra.memory.pgmajfault" in noms
    assert "infra.pressure.memory.avg10" in noms
    assert "infra.cpu.nr_throttled" in noms
    # Les latences partent en distribution : on veut des percentiles, un p99
    # a 6 s ne doit pas etre noye dans une moyenne.
    assert ("distribution", "infra.latency.db_roundtrip", 12.0) in envoye
