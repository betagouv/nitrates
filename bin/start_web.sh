#!/bin/bash
# This script is ran by scalingo to start the application

echo "Starting the Django app ($DJANGO_SETTINGS_MODULE) as user `whoami`"

# WEB_CONCURRENCY pilote le nombre de workers gunicorn (IaC via Scalingo env).
# Defaut conservateur (2) si non defini ; ajuster par taille de container.
gunicorn config.wsgi:application --preload --workers=${WEB_CONCURRENCY:-2} --timeout 120 --max-requests 100 --max-requests-jitter 20 --log-file -
