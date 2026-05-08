#!/bin/bash
# This script is ran by scalingo to start the application

# Interrupt the script on error
set -e

echo ">>> Starting the post_deploy hook"

python manage.py migrate

if [ "$IS_REVIEW_APP" == "True" ]
then
  python manage.py deploy_environment $APP.$REGION_NAME.scalingo.io
else
  # Import idempotent des zones vulnerables nitrates depuis Sandre.
  # Bloquant : si Sandre est down, le deploy echoue. C'est intentionnel
  # — on ne tourne pas l'app sans ZV. Pour debloquer ponctuellement,
  # set SKIP_NITRATES_ZV_IMPORT=1 et lancer l'import en manuel.
  if [ "$SKIP_NITRATES_ZV_IMPORT" == "1" ]; then
    echo ">>> SKIP_NITRATES_ZV_IMPORT=1, ZV import skipped (manual run required)"
  else
    echo ">>> Importing nitrates ZV from Sandre"
    python manage.py import_nitrates_zv
  fi

  # Import idempotent des departements ADMIN EXPRESS.
  # Source IGN distribuee en .7z (236 Mo metropole) - notre commande ne
  # sait que .zip. On ne tape donc pas l'IGN directement.
  # En CI/staging : SKIP_NITRATES_DEPARTMENTS_IMPORT=1 + import manuel via
  # scalingo run --file ADMIN_EXPRESS.zip.
  # En prod : DJANGO_NITRATES_DEPARTMENTS_URL pointant sur un mirror .zip.
  if [ "$SKIP_NITRATES_DEPARTMENTS_IMPORT" == "1" ]; then
    echo ">>> SKIP_NITRATES_DEPARTMENTS_IMPORT=1, departments import skipped (manual run required)"
  elif [ -n "$DJANGO_NITRATES_DEPARTMENTS_URL" ]; then
    echo ">>> Importing nitrates departments from $DJANGO_NITRATES_DEPARTMENTS_URL"
    python manage.py import_nitrates_departments --url "$DJANGO_NITRATES_DEPARTMENTS_URL"
  else
    echo ">>> No DJANGO_NITRATES_DEPARTMENTS_URL set and SKIP_NITRATES_DEPARTMENTS_IMPORT != 1"
    echo ">>> Refuse to deploy without departments. Set one of:"
    echo ">>>   - DJANGO_NITRATES_DEPARTMENTS_URL=<mirror_url.zip>"
    echo ">>>   - SKIP_NITRATES_DEPARTMENTS_IMPORT=1 (then manual import)"
    exit 1
  fi
fi


echo ">>> Leaving the post_deploy hook"
