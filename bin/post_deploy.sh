#!/bin/bash
# This script is ran by scalingo to start the application

# Interrupt the script on error
set -e

echo ">>> Starting the post_deploy hook"

python manage.py migrate

if [ "$IS_REVIEW_APP" == "True" ]
then
  python manage.py deploy_environment $APP.$REGION_NAME.scalingo.io
elif [ "$SKIP_NITRATES_ZV_IMPORT" == "1" ]; then
  # Fallback ops : Sandre durablement indisponible. L'import est skippe,
  # a relancer manuellement via `scalingo run python manage.py import_nitrates_zv --file <path>`.
  echo ">>> SKIP_NITRATES_ZV_IMPORT=1, ZV import skipped (manual run required)"
else
  # Import idempotent des zones vulnerables nitrates depuis Sandre.
  # Bloquant : si Sandre est down, le deploy echoue. C'est intentionnel
  # — on ne tourne pas l'app sans ZV. Pour debloquer ponctuellement,
  # set SKIP_NITRATES_ZV_IMPORT=1 et lancer l'import en manuel.
  echo ">>> Importing nitrates ZV from Sandre"
  python manage.py import_nitrates_zv
fi


echo ">>> Leaving the post_deploy hook"
