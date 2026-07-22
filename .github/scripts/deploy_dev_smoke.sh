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

echo "== Smoke arbres : arbres actifs + validation (un seul one-off) =="
# Un SEUL one-off qui enchaine les deux checks avec '&&'. On se fie au CODE
# RETOUR du one-off (capture de facon fiable par le marqueur END_..._rcN du
# helper), PAS a la presence/ordre d'un marqueur texte dans les logs : ceux-ci
# arrivent en desordre et avec latence cote Scalingo (source de faux negatifs).
# rc==0 <=> le compte d'arbres ET la validation ont reussi.
# On desarme 'set -e' autour de l'appel pour pouvoir lire rc (sinon le script
# sortirait avant la ligne rc=$?).
set +e
out=$(run_oneoff "python manage.py shell -c \"from envergo.nitrates.models import DecisionTree as D; n=D.objects.filter(status='active').count(); assert n>=1, 'aucun arbre actif'; print('arbres_actifs='+str(n))\" && python manage.py validate_arbres_actifs")
rc=$?
set -e
echo "$out"
if [ "$rc" -ne 0 ]; then
  echo "ECHEC smoke arbres (rc=$rc : compte arbres ou validation KO)" >&2
  exit 1
fi

echo "Smoke OK."
