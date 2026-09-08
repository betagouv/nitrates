#!/bin/bash
# This script is ran by scalingo to start the application

echo "Starting the Django app ($DJANGO_SETTINGS_MODULE) as user `whoami`"

# WEB_CONCURRENCY pilote le nombre de workers gunicorn (IaC via Scalingo env).
# Defaut conservateur (2) si non defini ; ajuster par taille de container.
# max-requests 1000 : filet anti-fuite seulement. A 100, chaque recyclage de
# worker coutait un pic de latence (re-fault du working set : 300-400 ms en
# local, plusieurs secondes sur un container dont les pages sont en swap) et
# arrivait toutes les ~4 h au trafic staging. Le gros de la croissance memoire
# par worker etait la casse du copy-on-write par le GC, traitee par gc.freeze
# dans config/gunicorn.conf.py.
gunicorn config.wsgi:application -c config/gunicorn.conf.py --preload --workers=${WEB_CONCURRENCY:-2} --timeout 120 --max-requests 1000 --max-requests-jitter 100 --log-file -
