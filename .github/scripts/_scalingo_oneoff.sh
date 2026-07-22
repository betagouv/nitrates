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

  # Poll robuste : deux signaux de fin possibles, chacun avec latence variable
  # d'indexation cote Scalingo :
  #   (a) notre marqueur END_..._rcN  -> fin fiable + code retour ;
  #   (b) "[manager] ... has stopped" du conteneur -> le one-off est termine,
  #       mais le marqueur peut ne pas encore etre indexe -> on continue a
  #       relire quelques tours pour le recuperer avant d'abandonner.
  # On lit LARGE (-n 1000) pour ne pas tronquer, et on ne renonce qu'apres avoir
  # vu le stop ET epuise une fenetre de grace de relecture.
  # Le marqueur de fin qu'on cherche est la LIGNE DE SORTIE du conteneur :
  #   "... [one-off-XXXX] END_..._rcN"  avec N numerique.
  # ATTENTION : les logs contiennent AUSSI une ligne "[manager] ... started with
  # the command 'echo BEGIN...; ...; echo END_..._rc$rc'" qui reproduit le texte
  # du marqueur (litteral, avec "$rc"). Il faut donc matcher STRICTEMENT le
  # marqueur emis par le conteneur : prefixe "[one-off-XXXX] " + END + rc SUIVI
  # D'UN CHIFFRE. Sinon on matche l'echo de la commande et on sort au tour 1
  # (bug vecu 2026-07-22).
  local end_re="\[$off\] ${end}_rc[0-9]"
  local logs="" i grace=0 stopped=0
  for i in $(seq 1 120); do
    sleep 4
    logs=$(scalingo --region "$SCALINGO_REGION" --app "$SCALINGO_APP" \
           logs --filter "$off" -n 1000 2>/dev/null || true)
    # (a) vrai marqueur de sortie trouve -> succes immediat
    if echo "$logs" | grep -qE "$end_re"; then
      break
    fi
    # (b) conteneur arrete : fenetre de grace pour laisser le marqueur s'indexer.
    if echo "$logs" | grep -q "\[$off\].*has stopped"; then
      stopped=1
    fi
    if [ "$stopped" = "1" ]; then
      grace=$((grace + 1))
      [ "$grace" -ge 8 ] && break
    fi
  done

  # Extrait la portion entre BEGIN et END (notre sortie), sans les prefixes log.
  # On ne garde que les vraies lignes du conteneur ([one-off-XXXX]) pour ne pas
  # inclure la ligne [manager] "started with the command".
  local body
  body=$(echo "$logs" \
    | grep -F "[$off] " \
    | sed -E "s/.*\[$off\] //" \
    | awk "/^${begin}$/{f=1;next} /^${end}_rc[0-9]/{f=0} f")
  echo "$body"

  # Code retour : le rc du VRAI marqueur de sortie (ligne [one-off-XXXX]).
  local rc
  rc=$(echo "$logs" | grep -oE "$end_re" | tail -1 | grep -oE '[0-9]+$' || echo "")
  if [ -z "$rc" ]; then
    # Marqueur jamais vu apres la fenetre de grace. C'est un vrai probleme
    # (timeout ou latence logs extreme) : on echoue explicitement. Ne PAS
    # supposer le succes -- un smoke doit rester conservateur.
    echo "run_oneoff: marqueur END non capte (stopped=$stopped) apres $((i*4))s" >&2
    return 1
  fi
  return "$rc"
}
