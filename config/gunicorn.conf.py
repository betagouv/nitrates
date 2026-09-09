"""Config gunicorn commune aux environnements Scalingo.

Chargée via `gunicorn -c config/gunicorn.conf.py` dans bin/start_web.sh.
Les réglages ligne de commande (workers, timeout...) restent dans le script.
"""

import gc


def post_fork(server, worker):
    # Avec --preload, les workers héritent de la mémoire du master en
    # copy-on-write. Le GC de chaque worker écrit dans les en-têtes des
    # objets hérités à chaque collecte, ce qui duplique les pages et fait
    # gonfler la mémoire privée de chaque worker (mesuré : USS 73 MiB par
    # worker après 300 requêtes, ramené à ~36 MiB avec ce freeze).
    # gc.freeze() déplace tout l'existant en génération permanente que le
    # GC ne visite plus.
    gc.freeze()

    # Télémétrie infra (carte #111) : démarrée ICI et pas dans AppConfig.ready()
    # parce qu'avec --preload, ready() s'exécute dans le master AVANT le fork.
    # Or fork() ne duplique que le thread appelant : un thread lancé avant
    # n'existerait dans aucun worker. post_fork tourne dans le worker, après
    # le fork, donc le thread vit dans le process qui sert vraiment le trafic.
    try:
        from envergo.nitrates.telemetry import start

        start()
    except Exception:
        # L'observabilité ne doit jamais empêcher un worker de démarrer.
        pass
