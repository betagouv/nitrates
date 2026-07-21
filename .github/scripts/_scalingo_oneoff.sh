#!/usr/bin/env bash
# Helper : lance une commande Django en one-off DETACHE sur Scalingo et
# recupere sa sortie de facon fiable.
#
# Pourquoi detache : `scalingo run` attache casse sans TTY (runner CI, contexte
# non-interactif) -> "make stdin raw: exit status 1" ou sortie vide (gotcha
# post-mortem PAR/ZAR). On passe donc par --detached + poll des logs.
#
# Fiabilite : on encadre la commande d'un marqueur de DEBUT et de FIN uniques
# (BEGIN/END + timestamp) pour isoler NOTRE sortie des collisions de numero
# one-off (les vieux conteneurs reutilisent les numeros). On poll jusqu'a voir
# le marqueur END (succes) ou "has stopped" (fin, on relit une derniere fois).
#
# Usage :  run_oneoff "<commande shell a executer dans le conteneur>"
# Renvoie : la sortie de la commande sur stdout ; exit != 0 si la commande a
#           imprime "ONEOFF_FAIL" (les scripts appelants s'en servent).
#
# Env requis : SCALINGO_REGION, SCALINGO_APP (+ SCALINGO_API_TOKEN pour l'auth).
#
# NB : ce fichier est destine a etre `source`. On ne met PAS `set -euo pipefail`
# ici (il modifierait l'environnement de l'appelant). Chaque script appelant
# gere ses propres options shell.

run_oneoff() {
  local user_cmd="$1"
  local tag="ONEOFF_$(date +%s)_$RANDOM"
  local begin="BEGIN_${tag}"
  local end="END_${tag}"

  # On enveloppe : marqueur debut, la commande (dont le code retour est capture),
  # puis marqueur fin AVEC le code retour. Tout sur stdout du conteneur.
  local wrapped="echo ${begin}; ( ${user_cmd} ); rc=\$?; echo ${end}_rc\$rc"

  local off
  off=$(scalingo --region "$SCALINGO_REGION" --app "$SCALINGO_APP" \
        run --detached "$wrapped" 2>&1 \
        | grep -oE 'one-off-[0-9]+' | head -1)

  if [ -z "$off" ]; then
    echo "run_oneoff: impossible de lancer le one-off" >&2
    return 1
  fi
  echo "run_oneoff: $off lance ($tag)" >&2

  # Poll : jusqu'a 90 x 4s = 6 min. On s'arrete des qu'on voit notre marqueur END.
  local logs="" i
  for i in $(seq 1 90); do
    sleep 4
    logs=$(scalingo --region "$SCALINGO_REGION" --app "$SCALINGO_APP" \
           logs --filter "$off" -n 400 2>/dev/null || true)
    if echo "$logs" | grep -q "${end}_rc"; then
      break
    fi
  done

  # Extrait la portion entre BEGIN et END (notre sortie), en retirant les
  # prefixes de log Scalingo (date + [one-off-xxxx]).
  local body
  body=$(echo "$logs" \
    | sed -E "s/.*\[$off\] //" \
    | awk "/${begin}/{f=1;next} /${end}_rc/{f=0} f")
  echo "$body"

  # Code retour de la commande distante.
  local rc
  rc=$(echo "$logs" | grep -oE "${end}_rc[0-9]+" | tail -1 | grep -oE '[0-9]+$' || echo "")
  if [ -z "$rc" ]; then
    echo "run_oneoff: marqueur de fin introuvable (timeout ?)" >&2
    return 1
  fi
  return "$rc"
}
