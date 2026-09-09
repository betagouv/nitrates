"""Telemetrie infra continue vers Sentry (carte #111).

Complete la sonde `/_probe/` (instantane a la demande) par un echantillonnage
regulier envoye dans Sentry, ou l'on dispose deja d'un backend, d'une retention
et d'alertes. Objectif : disposer d'un historique corrolable aux pics de
latence, que les metriques Scalingo ne permettent pas de reconstituer.

Pourquoi un thread dans le worker web plutot qu'un job planifie : le scheduler
Scalingo a une granularite minimale de 10 minutes et execute ses taches dans un
container one-off separe. Il mesurerait donc un autre container que ceux qui
servent le trafic, au moment ou justement il ne se passe rien. Les incidents
qui nous interessent durent quelques secondes.

Active par NITRATES_TELEMETRY_INTERVAL (secondes, 0 = desactive).
"""

import logging
import os
import threading

logger = logging.getLogger(__name__)

_started = False
_lock = threading.Lock()


def _emit(snapshot):
    """Pousse un instantane de la sonde vers Sentry sous forme de metriques."""
    try:
        from sentry_sdk import metrics
    except ImportError:
        return

    container = snapshot.get("container") or "?"
    tags = {"container": container}

    mem = snapshot.get("memory") or {}
    for key in ("current", "swap_current", "anon", "file"):
        val = mem.get(key)
        if isinstance(val, int):
            metrics.gauge(f"infra.memory.{key}", val, attributes=tags)

    # Compteurs cumulatifs : c'est leur progression qui compte. On les envoie
    # en gauge et on derive cote Sentry, plutot que de garder un etat ici (les
    # workers sont recycles, un etat local serait remis a zero sans prevenir).
    for key in ("pgmajfault", "workingset_refault_anon", "workingset_refault_file"):
        val = mem.get(key)
        if isinstance(val, int):
            metrics.gauge(f"infra.memory.{key}", val, attributes=tags)

    pressure = snapshot.get("pressure") or {}
    for kind in ("memory", "cpu", "io"):
        some = (pressure.get(kind) or {}).get("some") or {}
        # avg10 : pourcentage de temps bloque sur les 10 dernieres secondes.
        # C'est la fenetre la plus courte exposee par le noyau, donc la plus
        # proche d'un pic de quelques secondes.
        if "avg10" in some:
            metrics.gauge(
                f"infra.pressure.{kind}.avg10", some["avg10"], attributes=tags
            )

    cpu = snapshot.get("cpu") or {}
    for key in ("nr_throttled", "throttled_usec"):
        val = cpu.get(key)
        if isinstance(val, int):
            metrics.gauge(f"infra.cpu.{key}", val, attributes=tags)

    lat = snapshot.get("latency_ms") or {}
    for key in ("disk_read", "db_roundtrip"):
        val = lat.get(key)
        if isinstance(val, (int, float)):
            # distribution : on veut les percentiles, pas la moyenne. Un p99
            # a 6 s noye dans une moyenne a 80 ms est exactement ce qu'on
            # cherche a rendre visible.
            metrics.distribution(
                f"infra.latency.{key}", val, unit="millisecond", attributes=tags
            )


def _loop(interval):
    from envergo.nitrates.probe import collect

    while True:
        try:
            _emit(collect())
        except Exception:
            # Une sonde ne doit jamais tuer le worker qu'elle observe.
            logger.warning("telemetrie infra : echec d'un echantillon", exc_info=True)
        threading.Event().wait(interval)


def start():
    """Demarre l'echantillonnage. Idempotent, sans effet si desactive.

    Appele depuis AppConfig.ready(), donc une fois par worker gunicorn. Avec
    --preload, ready() tourne dans le master AVANT le fork : le thread ne
    survivrait pas au fork (seul le thread appelant est duplique). On ne
    demarre donc que dans un process qui sert reellement des requetes, ce que
    l'on detecte via le hook post_fork (cf. config/gunicorn.conf.py).
    """
    global _started

    try:
        from django.conf import settings

        interval = int(getattr(settings, "NITRATES_TELEMETRY_INTERVAL", 0) or 0)
    except Exception:
        interval = 0

    if interval <= 0:
        return

    with _lock:
        if _started:
            return
        _started = True

    t = threading.Thread(
        target=_loop,
        args=(interval,),
        name="nitrates-infra-telemetry",
        daemon=True,  # ne doit pas retenir l'arret du worker
    )
    t.start()
    logger.info(
        "telemetrie infra demarree (pid=%s, interval=%ss)", os.getpid(), interval
    )
