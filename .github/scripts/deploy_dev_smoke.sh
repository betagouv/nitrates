#!/usr/bin/env bash
# Etape 4 (SMOKE) : verifie que dev repond correctement apres deploiement.
#
# - HTTP : la racine repond 302 (dev ferme -> redirection login) ou 200.
# - Arbres : au moins un arbre actif par scope attendu, et validation OK.
# Non destructif, rapide.

set -euo pipefail
cd "$(dirname "$0")/../.."
source .github/scripts/_scalingo_oneoff.sh

APP_URL="https://${SCALINGO_APP}.${SCALINGO_REGION}.scalingo.io/"

echo "== Smoke HTTP : ${APP_URL} =="
code=$(curl -s -o /dev/null -w '%{http_code}' -L --max-time 30 "$APP_URL" || echo "000")
echo "HTTP ${code}"
case "$code" in
  200|302|301) echo "OK (racine repond)";;
  *) echo "ECHEC smoke HTTP (code ${code})" >&2; exit 1;;
esac

echo "== Smoke arbres : arbres actifs + validation =="
run_oneoff "python manage.py shell -c \"from envergo.nitrates.models import DecisionTree as D; n=D.objects.filter(status='active').count(); print('arbres_actifs='+str(n)); assert n>=1\"" || {
  echo "ECHEC : aucun arbre actif" >&2; exit 1;
}

run_oneoff "python manage.py validate_arbres_actifs" || {
  echo "ECHEC validation arbres canoniques" >&2; exit 1;
}

echo "Smoke OK."
