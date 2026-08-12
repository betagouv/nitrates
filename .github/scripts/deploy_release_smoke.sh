#!/usr/bin/env bash
# SMOKE (staging / prod) : verifie que l'app repond apres deploiement.
#
# Volontairement MINIMAL et non destructif : on ne touche a aucune donnee.
#   1. HTTP : la racine repond (200, ou 302 si l'env est encore derriere le
#      lockdown login).
#   2. Migrations : aucune migration non appliquee (le post_deploy a bien
#      joue `migrate`). C'est le seul effet DB attendu d'un deploiement
#      release, donc le seul qu'on verifie.
#
# On ne verifie PAS les arbres / referentiels : sur staging et prod, ces
# contenus sont pilotes a la main et ne font pas partie du deploiement.
#
# Env requis : SCALINGO_REGION, SCALINGO_APP, SCALINGO_API_TOKEN.
# Env optionnel : APP_URL (sinon deduite du nom d'app et de la region).

set -euo pipefail
cd "$(dirname "$0")/../.."
source .github/scripts/_scalingo_oneoff.sh

APP_URL="${APP_URL:-https://${SCALINGO_APP}.${SCALINGO_REGION}.scalingo.io/}"

echo "== Smoke HTTP : ${APP_URL} =="
code=$(curl -s -o /dev/null -w '%{http_code}' -L --max-time 30 "$APP_URL" || echo "000")
echo "HTTP ${code}"
case "$code" in
  200|301|302) echo "OK (l'app repond)";;
  *) echo "ECHEC smoke HTTP (code ${code})" >&2; exit 1;;
esac

echo "== Smoke migrations : aucune migration en attente =="
# `migrate --check` sort en code != 0 s'il reste des migrations non appliquees.
# On se fie au CODE RETOUR du one-off (capture fiable via le marqueur du
# helper), pas au texte des logs (arrivee desordonnee cote Scalingo).
set +e
out=$(run_oneoff "python manage.py migrate --check")
rc=$?
set -e
echo "$out"
if [ "$rc" -ne 0 ]; then
  echo "ECHEC smoke : des migrations restent non appliquees (rc=$rc)" >&2
  echo "Le post_deploy a probablement echoue -- verifier les logs Scalingo." >&2
  exit 1
fi

echo "Smoke OK."
