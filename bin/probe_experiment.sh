#!/usr/bin/env bash
# Protocole de mesure reproductible du ralentissement staging (carte #111).
#
# Objectif : produire des chiffres opposables a un hebergeur, en isolant
# l'infrastructure du code applicatif. Le coeur du protocole est de mesurer
# une ressource dont le cout applicatif est nul et constant (un fichier
# statique servi par WhiteNoise) : toute variation de latence est alors
# imputable a la plateforme, pas a nous.
#
# Usage :
#   bin/probe_experiment.sh <base_url> [token] [nb_iterations]
#
# Exemple :
#   bin/probe_experiment.sh https://nitrates-staging.osc-fr1.scalingo.io "$PROBE_TOKEN" 60
#
# Sortie : un CSV sur stdout (redirigeable) + un resume lisible sur stderr.

set -uo pipefail

BASE="${1:?usage: probe_experiment.sh <base_url> [token] [n]}"
TOKEN="${2:-}"
N="${3:-60}"

# Ressource temoin : petite, statique, servie sans SQL ni logique metier.
STATIC_PATH="/static/images/favicon.ico"
# Ressource applicative legere : traverse Django mais ne fait presque rien.
APP_PATH="/"

echo "ts,iteration,cible,http_code,ttfb_s,total_s,taille,pgmajfault,swap_current,psi_mem_total,psi_io_total,container"

log() { printf '%s\n' "$*" >&2; }

log "Protocole #111 — $N iterations sur $BASE"
log "Temoin statique : $STATIC_PATH (cout applicatif nul)"
log ""

probe_json() {
  [ -z "$TOKEN" ] && { echo "{}"; return; }
  curl -s -m 20 "$BASE/_probe/now/?token=$TOKEN" 2>/dev/null || echo "{}"
}

# Extraction sans jq (pas garanti present) : grep sur le JSON aplati.
jget() {
  printf '%s' "$1" | tr -d ' \n' | grep -o "\"$2\":[0-9.]*" | head -1 | cut -d: -f2
}
jget_nested() {
  # $2 = chemin type pressure.memory.some.total — on prend la Nieme occurrence
  printf '%s' "$1" | tr -d ' \n' | grep -o "\"total\":[0-9.]*" | sed -n "${2}p" | cut -d: -f2
}

for i in $(seq 1 "$N"); do
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  # 1. Metriques infra AVANT la requete
  P=$(probe_json)
  majflt=$(jget "$P" pgmajfault)
  swapcur=$(jget "$P" swap_current)
  # pressure : memory.some.total est le 1er "total", io.some.total le 5e
  psimem=$(jget_nested "$P" 1)
  psiio=$(jget_nested "$P" 5)
  container=$(printf '%s' "$P" | grep -o '"container":"[^"]*"' | cut -d'"' -f4)

  # 2. Le temoin statique : c'est LA mesure qui compte
  read -r code ttfb total size <<<"$(curl -s -o /dev/null -m 60 \
    -w '%{http_code} %{time_starttransfer} %{time_total} %{size_download}' \
    "$BASE$STATIC_PATH")"
  echo "$ts,$i,static,$code,$ttfb,$total,$size,${majflt:-},${swapcur:-},${psimem:-},${psiio:-},${container:-}"

  # 3. La meme chose sur une page applicative, pour comparaison
  read -r code2 ttfb2 total2 size2 <<<"$(curl -s -o /dev/null -m 60 \
    -w '%{http_code} %{time_starttransfer} %{time_total} %{size_download}' \
    "$BASE$APP_PATH")"
  echo "$ts,$i,app,$code2,$ttfb2,$total2,$size2,${majflt:-},${swapcur:-},${psimem:-},${psiio:-},${container:-}"

  # Espacement : on cherche a attraper des pages qui refroidissent, pas a
  # faire un test de charge. 10 s laisse le temps au noyau d'evincer.
  [ "$i" -lt "$N" ] && sleep 10
done

log ""
log "Termine. Analyse suggeree :"
log "  awk -F, 'NR>1 && \$3==\"static\" {print \$5}' resultats.csv | sort -n | tail -5"
log "  # les pires TTFB sur une ressource au cout applicatif nul"
