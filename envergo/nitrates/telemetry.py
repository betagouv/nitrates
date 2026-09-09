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


def _flatten(snapshot):
    """Aplatit un instantane en couples (nom, valeur numerique)."""
    out = {}

    mem = snapshot.get("memory") or {}
    for key in (
        "current",
        "swap_current",
        "anon",
        "file",
        "pgmajfault",
        "workingset_refault_anon",
        "workingset_refault_file",
    ):
        val = mem.get(key)
        if isinstance(val, (int, float)):
            # Les tailles passent en MiB : plus lisible sur un graphe qu'un
            # octet brut, sans perte utile a cette echelle.
            if key in ("current", "swap_current", "anon", "file"):
                out[f"mem_{key}_mib"] = round(val / 1048576, 2)
            else:
                out[f"mem_{key}"] = val

    pressure = snapshot.get("pressure") or {}
    for kind in ("memory", "cpu", "io"):
        some = (pressure.get(kind) or {}).get("some") or {}
        # avg10 : pourcentage de temps bloque sur les 10 dernieres secondes.
        # C'est la fenetre la plus courte exposee par le noyau, donc la plus
        # proche d'un pic de quelques secondes.
        if isinstance(some.get("avg10"), (int, float)):
            out[f"psi_{kind}_avg10"] = some["avg10"]

    cpu = snapshot.get("cpu") or {}
    for key in ("nr_throttled", "throttled_usec"):
        val = cpu.get(key)
        if isinstance(val, (int, float)):
            out[f"cpu_{key}"] = val

    lat = snapshot.get("latency_ms") or {}
    for key in ("disk_read", "db_roundtrip"):
        val = lat.get(key)
        if isinstance(val, (int, float)):
            out[f"latency_{key}_ms"] = val

    proc = snapshot.get("process") or {}
    if isinstance(proc.get("vm_swap_kb"), (int, float)):
        out["proc_swap_kb"] = proc["vm_swap_kb"]

    return out


def _emit(snapshot):
    """Publie un instantane de la sonde vers Sentry.

    Transporte par une TRANSACTION et non par l'API `sentry_sdk.metrics` :
    verifie le 09/09 sur sentry.incubateur.net, les metriques custom du SDK
    2.66 ne sont pas ingerees par cette instance auto-hebergee (elles partent
    en HTTP 200 mais ressortent a count()=0), alors que les transactions le
    sont.

    Les valeurs sont posees en MEASUREMENTS et non en `data` : un `data`
    ressort typé string cote Sentry (`avg()` le refuse, et le validateur des
    dashboards rejette la syntaxe `tags[<nom>,number]` a l'ecriture), la ou un
    measurement est nativement numerique, donc agregeable en avg/p95 et
    utilisable tel quel dans un widget.
    """
    try:
        import sentry_sdk
    except ImportError:
        return

    values = _flatten(snapshot)
    if not values:
        return

    with sentry_sdk.start_transaction(
        op="infra.telemetry",
        name="infra.probe",
        # Cet echantillon est deja cadence par l'intervalle de la boucle :
        # le sampling global des traces n'a pas a le filtrer en plus.
        sampled=True,
    ) as tx:
        tx.set_tag("container", snapshot.get("container") or "?")
        for key, val in values.items():
            unit = "millisecond" if key.endswith("_ms") else "none"
            # On alimente `_measurements` directement plutot que via
            # set_measurement() : cette methode est depreciee depuis le SDK
            # 2.28 au profit de set_data(), mais set_data produit un champ
            # typé string cote Sentry, que ni avg()/p95() ni le validateur
            # des dashboards n'acceptent. Le format du dict est stable et
            # public dans le protocole d'evenement (measurements).
            tx._measurements[key] = {"value": val, "unit": unit}


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
