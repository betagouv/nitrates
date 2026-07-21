#!/usr/bin/env bash
# Etape 2 (DEPLOY CODE) : deploie le code sur nitrates-dev par ARCHIVE.
#
# `scalingo deploy <archive>` deploie un tarball via l'API (token seul, pas de
# cle SSH a gerer sur le runner). Le post_deploy Scalingo joue migrate + imports
# SIG idempotents. On suit le deploiement jusqu'a son issue.
#
# Arg 1 : SHA (reference de version affichee cote Scalingo).

set -euo pipefail
cd "$(dirname "$0")/../.."

SHA="${1:-$(git rev-parse HEAD)}"
ARCHIVE="/tmp/nitrates-${SHA}.tar.gz"

echo "== Construction de l'archive de deploiement (git archive @ ${SHA}) =="
# --prefix : Scalingo `deploy` exige un tar avec un REPERTOIRE WRAPPER unique a
# la racine (comme les tarballs GitHub `owner-repo-sha/...`). Sans prefixe, les
# fichiers sont a la racine du tar et le deployeur echoue :
#   "fail to handle tgz: ... open .../django: is a directory"
git archive --format=tar.gz --prefix=nitrates/ -o "$ARCHIVE" "$SHA"
ls -la "$ARCHIVE"

echo "== scalingo deploy (--no-follow : on suit l'issue via l'API) =="
scalingo --region "$SCALINGO_REGION" --app "$SCALINGO_APP" \
  deploy --no-follow "$ARCHIVE" "$SHA"

echo "== Attente de l'issue du deploiement =="
# Le post_deploy (migrate + imports SIG) tourne dans la phase 'starting'. On
# poll le status du deploiement de CE sha jusqu'a success / erreur.
final=""
for i in $(seq 1 90); do
  sleep 10
  line=$(scalingo --region "$SCALINGO_REGION" --app "$SCALINGO_APP" \
         deployments 2>/dev/null | grep "$SHA" | grep -v "build-error" | head -1 || true)
  status=$(echo "$line" | grep -oE 'success|crashed|build-error|deploy-error|aborted' | head -1 || true)
  if [ -n "$status" ]; then final="$status"; break; fi
done

echo "Status final du deploiement : ${final:-timeout}"
if [ "$final" != "success" ]; then
  echo "ECHEC : deploiement non abouti (${final:-timeout})" >&2
  scalingo --region "$SCALINGO_REGION" --app "$SCALINGO_APP" deployments 2>/dev/null | head -4
  exit 1
fi
echo "Deploiement code OK."
