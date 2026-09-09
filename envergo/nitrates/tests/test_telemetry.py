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


SNAPSHOT = {
    "container": "web-1",
    "memory": {
        "current": 104857600,  # 100 MiB
        "swap_current": 52428800,  # 50 MiB
        "pgmajfault": 7,
    },
    "pressure": {"memory": {"some": {"avg10": 1.5}}},
    "cpu": {"nr_throttled": 2},
    "latency_ms": {"disk_read": 0.5, "db_roundtrip": 12.0},
    "process": {"vm_swap_kb": 4096},
}


def test_flatten_convertit_et_nomme_les_valeurs():
    v = telemetry._flatten(SNAPSHOT)
    # Les tailles passent en MiB pour rester lisibles sur un graphe.
    assert v["mem_current_mib"] == 100.0
    assert v["mem_swap_current_mib"] == 50.0
    assert v["mem_pgmajfault"] == 7
    assert v["psi_memory_avg10"] == 1.5
    assert v["cpu_nr_throttled"] == 2
    assert v["latency_db_roundtrip_ms"] == 12.0
    assert v["proc_swap_kb"] == 4096


def test_flatten_ignore_les_valeurs_absentes():
    v = telemetry._flatten({"memory": {"current": None}, "pressure": {}, "cpu": {}})
    assert v == {}


class FakeTx:
    """Transaction Sentry minimale : on veut verifier ou atterrissent les
    valeurs, pas reimplementer le SDK."""

    def __init__(self):
        self._measurements = {}
        self.tags = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def set_tag(self, k, v):
        self.tags[k] = v


def _fake_sentry(monkeypatch, start_transaction):
    """Injecte un faux module sentry_sdk dans sys.modules.

    sentry_sdk est une dependance PRODUCTION, absente de l'environnement de
    test (la CI l'a rappele : ModuleNotFoundError). _emit l'importe
    paresseusement, donc un module factice suffit -- et cela teste au passage
    que le code ne depend que de start_transaction.
    """
    import sys
    import types

    fake = types.ModuleType("sentry_sdk")
    fake.start_transaction = start_transaction
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)


def test_emit_publie_les_valeurs_en_measurements(monkeypatch):
    """Les valeurs doivent partir en measurements (numeriques cote Sentry),
    pas en data (typé string, refusé par avg() et par les dashboards)."""
    tx = FakeTx()
    _fake_sentry(monkeypatch, lambda **kw: tx)

    telemetry._emit(SNAPSHOT)

    assert tx.tags["container"] == "web-1"
    assert tx._measurements["mem_swap_current_mib"]["value"] == 50.0
    assert tx._measurements["mem_pgmajfault"]["value"] == 7
    assert tx._measurements["latency_db_roundtrip_ms"]["value"] == 12.0
    # Les durees portent leur unite, le reste est sans dimension.
    assert tx._measurements["latency_db_roundtrip_ms"]["unit"] == "millisecond"
    assert tx._measurements["mem_swap_current_mib"]["unit"] == "none"


def test_emit_ne_publie_rien_si_aucune_valeur(monkeypatch):
    """Un snapshot vide ne doit pas generer de transaction inutile."""
    appels = []
    _fake_sentry(monkeypatch, lambda **kw: appels.append(kw))
    telemetry._emit({"memory": {}, "pressure": {}, "cpu": {}, "latency_ms": {}})
    assert appels == []
