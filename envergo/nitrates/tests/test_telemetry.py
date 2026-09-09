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


def test_emit_publie_une_transaction_avec_les_valeurs(monkeypatch):
    """L'instance Sentry auto-hebergee n'ingere pas les metriques custom du
    SDK (verifie le 09/09) : les valeurs doivent voyager sur une transaction."""
    posees = {}
    tags = {}

    class FakeTx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def set_data(self, k, v):
            posees[k] = v

        def set_tag(self, k, v):
            tags[k] = v

    import sentry_sdk

    monkeypatch.setattr(
        sentry_sdk, "start_transaction", lambda **kw: FakeTx(), raising=False
    )

    telemetry._emit(SNAPSHOT)

    assert tags["container"] == "web-1"
    assert posees["mem_swap_current_mib"] == 50.0
    assert posees["mem_pgmajfault"] == 7
    assert posees["latency_db_roundtrip_ms"] == 12.0


def test_emit_ne_publie_rien_si_aucune_valeur(monkeypatch):
    """Un snapshot vide ne doit pas generer de transaction inutile."""
    appels = []
    import sentry_sdk

    monkeypatch.setattr(
        sentry_sdk,
        "start_transaction",
        lambda **kw: appels.append(kw),
        raising=False,
    )
    telemetry._emit({"memory": {}, "pressure": {}, "cpu": {}, "latency_ms": {}})
    assert appels == []
