"""Sonde d'observabilite infrastructure (carte #111).

Les metriques Scalingo (CPU / RAM / swap agreges par container, echantillonnes
grossierement) ne permettent pas de diagnostiquer les ralentissements
intermittents de staging. Ce module lit ce que le noyau expose reellement
DANS le container, ce que le dashboard ne montre pas :

- cgroup v2 : memory.current / .max / .swap.current, et surtout `memory.stat`
  (pgmajfault, workingset_refault_*) qui compte les fautes de page majeures,
  c'est-a-dire les acces qui sont partis chercher une page sur disque ;
- PSI (pressure stall information, /sys/fs/cgroup/*.pressure) : le pourcentage
  de temps ou des taches sont bloquees a attendre la memoire, le CPU ou l'I/O.
  C'est la metrique qui prouve un probleme d'hote, et Scalingo ne l'expose pas ;
- latences mesurees a la source : un read disque, un aller-retour SQL trivial.

Expose en lecture seule via une URL protegee par jeton (cf. views_probe.py).
A retirer une fois le probleme d'infrastructure tranche.
"""

import os
import time

CGROUP = "/sys/fs/cgroup"


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _read_int(path):
    raw = _read(path)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return raw  # "max" par exemple


def _read_keyed(path):
    """Parse un fichier cgroup "cle valeur" par ligne (memory.stat, cpu.stat)."""
    raw = _read(path)
    if not raw:
        return {}
    out = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                out[parts[0]] = int(parts[1])
            except ValueError:
                pass
    return out


def _read_pressure(path):
    """Parse un fichier PSI.

    Format : `some avg10=0.00 avg60=0.00 avg300=0.00 total=12345`
    `total` est un compteur cumulatif en microsecondes : c'est lui qui compte
    pour un diff entre deux echantillons, les moyennes glissantes ratent les
    pics courts.
    """
    raw = _read(path)
    if not raw:
        return {}
    out = {}
    for line in raw.splitlines():
        parts = line.split()
        if not parts:
            continue
        kind = parts[0]  # "some" ou "full"
        vals = {}
        for p in parts[1:]:
            if "=" in p:
                k, v = p.split("=", 1)
                try:
                    vals[k] = float(v)
                except ValueError:
                    pass
        out[kind] = vals
    return out


def _proc_self_swap_kb():
    """Combien de la memoire de CE process est actuellement en swap."""
    raw = _read("/proc/self/status")
    if not raw:
        return None
    for line in raw.splitlines():
        if line.startswith("VmSwap:"):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return None
    return 0


def _disk_read_latency_ms():
    """Temps pour lire un fichier deja present sur le disque du container.

    Sert de temoin : si cette valeur explose alors que le fichier est minuscule,
    le container attend l'I/O de l'hote, pas notre code.
    """
    target = "/proc/self/cmdline"
    t = time.perf_counter()
    try:
        with open(target, "rb") as f:
            f.read()
    except OSError:
        return None
    return round((time.perf_counter() - t) * 1000, 3)


def _db_roundtrip_ms():
    """Aller-retour SQL trivial (SELECT 1), connexion deja etablie."""
    from django.db import connection

    t = time.perf_counter()
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
            c.fetchone()
    except Exception:
        return None
    return round((time.perf_counter() - t) * 1000, 3)


def collect():
    """Retourne un instantane des metriques infra du container."""
    mem_stat = _read_keyed(f"{CGROUP}/memory.stat")
    cpu_stat = _read_keyed(f"{CGROUP}/cpu.stat")

    snapshot = {
        "ts": time.time(),
        "container": os.environ.get("CONTAINER", os.environ.get("HOSTNAME")),
        "memory": {
            "current": _read_int(f"{CGROUP}/memory.current"),
            "max": _read_int(f"{CGROUP}/memory.max"),
            "swap_current": _read_int(f"{CGROUP}/memory.swap.current"),
            "swap_max": _read_int(f"{CGROUP}/memory.swap.max"),
            "anon": mem_stat.get("anon"),
            "file": mem_stat.get("file"),
            # Fautes de page majeures = acces partis chercher une page sur
            # disque. C'est LE compteur qui materialise le cout du swap.
            "pgmajfault": mem_stat.get("pgmajfault"),
            "workingset_refault_anon": mem_stat.get("workingset_refault_anon"),
            "workingset_refault_file": mem_stat.get("workingset_refault_file"),
            "pgscan": mem_stat.get("pgscan"),
            "pgsteal": mem_stat.get("pgsteal"),
        },
        # PSI : temps passe bloque a attendre une ressource. `total` est
        # cumulatif (microsecondes), a differencier entre deux echantillons.
        "pressure": {
            "memory": _read_pressure(f"{CGROUP}/memory.pressure"),
            "cpu": _read_pressure(f"{CGROUP}/cpu.pressure"),
            "io": _read_pressure(f"{CGROUP}/io.pressure"),
        },
        "cpu": {
            "usage_usec": cpu_stat.get("usage_usec"),
            # Throttling : l'hote nous a-t-il coupe le CPU ?
            "nr_throttled": cpu_stat.get("nr_throttled"),
            "throttled_usec": cpu_stat.get("throttled_usec"),
            "nr_periods": cpu_stat.get("nr_periods"),
        },
        "process": {
            "pid": os.getpid(),
            "vm_swap_kb": _proc_self_swap_kb(),
        },
        "latency_ms": {
            "disk_read": _disk_read_latency_ms(),
            "db_roundtrip": _db_roundtrip_ms(),
        },
    }
    return snapshot
