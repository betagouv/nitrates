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
