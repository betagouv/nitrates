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
  # — on ne tourne pas l'app sans ZV. Patcher manuellement avec --file
  # si Sandre est durablement indisponible.
  echo ">>> Importing nitrates ZV from Sandre"
  python manage.py import_nitrates_zv
fi


echo ">>> Leaving the post_deploy hook"
