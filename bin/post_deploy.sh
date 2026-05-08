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
  # Default : URL stable IGN (data.geopf.fr, .7z 250 Mo metropole).
  # Pour debloquer ponctuellement (IGN down, mirror prive) :
  # SKIP_NITRATES_DEPARTMENTS_IMPORT=1 (puis import manuel via --file).
  if [ "$SKIP_NITRATES_DEPARTMENTS_IMPORT" == "1" ]; then
    echo ">>> SKIP_NITRATES_DEPARTMENTS_IMPORT=1, departments import skipped (manual run required)"
  else
    echo ">>> Importing nitrates departments from IGN ADMIN EXPRESS"
    if [ -n "$DJANGO_NITRATES_DEPARTMENTS_URL" ]; then
      python manage.py import_nitrates_departments --url "$DJANGO_NITRATES_DEPARTMENTS_URL"
    else
      python manage.py import_nitrates_departments
    fi
  fi
fi


echo ">>> Leaving the post_deploy hook"
