#!/usr/bin/env bash
# DEPLOY CODE (staging / prod) : deploie une REF GIT donnee par archive.
#
# Variante "release" de deploy_dev_code.sh. Deux differences :
#   - on deploie une ref arbitraire (le tag de la release), pas forcement HEAD ;
#   - AUCUN reload de donnees derriere (pas d'arbres, pas de referentiels) :
#     sur staging/prod le contenu metier est pilote a la main. Le seul effet
#     de bord DB est le `migrate` joue par bin/post_deploy.sh cote Scalingo.
#
# Env requis : SCALINGO_REGION, SCALINGO_APP, SCALINGO_API_TOKEN.
# Arg 1 : la ref git a deployer (tag, ex "v0.5.0"). Defaut : HEAD.

set -euo pipefail
cd "$(dirname "$0")/../.."

REF="${1:-HEAD}"
SHA="$(git rev-parse "$REF")"
ARCHIVE="/tmp/nitrates-${SHA}.tar.gz"

echo "== Deploiement de ${REF} (${SHA}) sur ${SCALINGO_APP} (${SCALINGO_REGION}) =="

# --prefix : Scalingo exige un tar avec un repertoire wrapper unique a la
# racine. Sans prefixe, le deployeur echoue ("fail to handle tgz ... is a
# directory"). Cf. deploy_dev_code.sh.
git archive --format=tar.gz --prefix=nitrates/ -o "$ARCHIVE" "$SHA"
ls -la "$ARCHIVE"

# On etiquette le deploiement avec la ref lisible (tag) plutot que le sha nu,
# pour que `scalingo deployments` soit lisible au moment d'un rollback.
echo "== scalingo deploy (--no-follow : on suit l'issue via l'API) =="
scalingo --region "$SCALINGO_REGION" --app "$SCALINGO_APP" \
  deploy --no-follow "$ARCHIVE" "$REF"

echo "== Attente de l'issue du deploiement =="
# Le post_deploy (migrate) tourne dans la phase 'starting'. On poll le status
# du deploiement jusqu'a success / erreur. 90 x 10s = 15 min de marge.
final=""
for i in $(seq 1 90); do
  sleep 10
  line=$(scalingo --region "$SCALINGO_REGION" --app "$SCALINGO_APP" \
         deployments 2>/dev/null | grep "$REF" | grep -v "build-error" | head -1 || true)
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
