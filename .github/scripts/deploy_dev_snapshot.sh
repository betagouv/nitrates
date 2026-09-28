#!/usr/bin/env bash
# Etape 1 (SAFETY) : trace les arbres ACTIFS de dev AVANT le deploiement,
# dans _deploy_snapshot/ (uploade en artifact).
#
# Non bloquant : si le snapshot echoue, on log mais on ne casse pas le deploy
# (c'est une trace, pas une precondition). Le deploiement ne recharge plus les
# donnees : seules les migrations ecrivent en base.

set -euo pipefail
cd "$(dirname "$0")/../.."
source .github/scripts/_scalingo_oneoff.sh

mkdir -p _deploy_snapshot

echo "== Snapshot : liste des arbres actifs de dev =="
run_oneoff "python manage.py shell -c \"from envergo.nitrates.models import DecisionTree as D; [print(t.scope, t.region_code or '-', t.name) for t in D.objects.filter(status='active').order_by('scope','region_code')]\"" \
  > _deploy_snapshot/arbres_actifs_avant.txt 2>&1 || echo "(snapshot arbres non bloquant : echec)"

echo "Snapshot ecrit dans _deploy_snapshot/ :"
ls -la _deploy_snapshot/ || true
