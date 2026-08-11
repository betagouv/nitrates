#!/usr/bin/env bash
# GATE : refuse de deployer un SHA dont la CI n'est pas verte.
#
# Pourquoi : rien n'empeche de tagger un commit arbitraire (y compris un commit
# jamais passe en PR, ou pousse en direct sur main par un admin -- la protection
# de branche a enforce_admins=false). Sans ce garde-fou, creer une release
# suffirait a envoyer du code non teste en prod.
#
# On interroge l'API "check-runs" du SHA et on exige que les checks REQUIS
# soient en success. Un check absent est un ECHEC (il n'a jamais tourne), pas
# un succes implicite.
#
# Env requis : GH_TOKEN (fourni par le workflow), GITHUB_REPOSITORY.
# Arg 1 : le SHA a verifier.
# Arg 2+ : noms des checks requis (defaut : linter pytest).

set -euo pipefail

SHA="${1:?usage: gate_ci_green.sh <sha> [check...]}"
shift || true
REQUIS=("$@")
if [ "${#REQUIS[@]}" -eq 0 ]; then
  REQUIS=("linter" "pytest")
fi

echo "== Gate CI : verification des checks de ${SHA} =="

# --paginate : un SHA peut porter beaucoup de check-runs (CodeQL, Dependabot,
# GitGuardian...). Sans pagination on risque de rater le check cherche et de
# conclure a tort qu'il est absent.
runs=$(gh api --paginate \
  "repos/${GITHUB_REPOSITORY}/commits/${SHA}/check-runs" \
  --jq '.check_runs[] | "\(.name)\t\(.status)\t\(.conclusion)"' 2>/dev/null || true)

if [ -z "$runs" ]; then
  echo "ECHEC : aucun check-run trouve pour ${SHA}." >&2
  echo "Le commit n'a jamais ete teste par la CI -- deploiement refuse." >&2
  exit 1
fi

echo "Checks trouves :"
echo "$runs" | sed 's/^/  /'

echec=0
for check in "${REQUIS[@]}"; do
  # Un meme check peut avoir plusieurs runs (re-run). On prend la MEILLEURE
  # conclusion : si un re-run a repare un echec, le SHA est vert.
  ligne=$(echo "$runs" | awk -F'\t' -v c="$check" '$1 == c' || true)
  if [ -z "$ligne" ]; then
    echo "ECHEC : le check requis '${check}' n'a pas tourne sur ce SHA." >&2
    echec=1
    continue
  fi
  if echo "$ligne" | awk -F'\t' '$2 == "completed" && $3 == "success"' | grep -q .; then
    echo "OK : ${check} est vert."
  else
    echo "ECHEC : le check requis '${check}' n'est pas vert :" >&2
    echo "$ligne" | sed 's/^/    /' >&2
    echec=1
  fi
done

if [ "$echec" -ne 0 ]; then
  echo "" >&2
  echo "Deploiement refuse : la CI de ${SHA} n'est pas verte." >&2
  exit 1
fi

echo "Gate CI OK : tous les checks requis sont verts."
