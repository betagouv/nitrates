#!/usr/bin/env bash
# Etape 1 (SAFETY) : capture l'etat ACTIF de dev AVANT tout ecrit.
# Dumpe arbres + referentiels via one-off et rapatrie les fichiers dans
# _deploy_snapshot/ (uploade en artifact -> filet de rollback).
#
# Non bloquant : si le snapshot echoue, on log mais on ne casse pas le deploy
# (c'est un filet, pas une precondition). Le vrai garde-fou anti-ecrasement des
# arbres est le lifecycle draft->active (l'ancien reste en archive).

set -euo pipefail
cd "$(dirname "$0")/../.."
source .github/scripts/_scalingo_oneoff.sh

mkdir -p _deploy_snapshot

echo "== Snapshot : liste des arbres actifs de dev =="
run_oneoff "python manage.py shell -c \"from envergo.nitrates.models import DecisionTree as D; [print(t.scope, t.region_code or '-', t.name) for t in D.objects.filter(status='active').order_by('scope','region_code')]\"" \
  > _deploy_snapshot/arbres_actifs_avant.txt 2>&1 || echo "(snapshot arbres non bloquant : echec)"

echo "== Snapshot : etat du --check arbres (le repo reflete-t-il dev ?) =="
run_oneoff "python manage.py dump_active_trees --check" \
  > _deploy_snapshot/dump_check_arbres.txt 2>&1 || echo "(arbres repo != dev : normal si la PR modifie des arbres)"

echo "== Snapshot : etat du --check referentiels =="
run_oneoff "python manage.py dump_referentiels --check" \
  > _deploy_snapshot/dump_check_referentiels.txt 2>&1 || echo "(referentiels repo != dev)"

echo "Snapshot ecrit dans _deploy_snapshot/ :"
ls -la _deploy_snapshot/ || true
