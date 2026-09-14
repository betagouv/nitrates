#!/usr/bin/env bash
# Etape 3 (RELOAD DATA) : recharge les donnees canoniques du repo en DB.
#
# - Arbres : load_arbres_actifs --skip-si-identique -> pour chaque zone, cree une
#   nouvelle version draft puis l'active (archive l'ancienne), SAUF si le contenu
#   canonique est deja identique a l'actif (pas de version-doublon). Jamais
#   d'override in-place.
# - Referentiels : seed_referentiels (loaddata upsert, preserve les blocs edites).
# - Restart web : les loaders sont en @lru_cache process-local -> sans restart, le
#   web ne voit pas les nouveaux contenus (gotcha post-mortem).

set -euo pipefail
cd "$(dirname "$0")/../.."
source .github/scripts/_scalingo_oneoff.sh

# ORDRE : referentiels AVANT arbres. load_arbres_actifs VALIDE chaque arbre
# contre le referentiel EN DB : si un arbre canonique reference une entree
# nouvellement ajoutee au repo (fixture + arbre dans le meme commit), la
# charger apres les arbres est un oeuf-et-poule qui casse le deploy.
# Constate le 14/09 : pc5 present dans la fixture ET dans national.yaml,
# absent de la DB dev -> "code_prescription 'pc5' inconnu dans le
# référentiel (DB)" et 3 deploys rouges. seed_referentiels est un upsert
# qui preserve les blocs edites : le passer en premier est sans risque.
echo "== Seed referentiels =="
run_oneoff "python manage.py seed_referentiels" || {
  echo "ECHEC seed referentiels" >&2; exit 1;
}

echo "== Reload arbres (draft->active, skip si identique) =="
run_oneoff "python manage.py load_arbres_actifs --skip-si-identique" || {
  echo "ECHEC reload arbres" >&2; exit 1;
}

echo "== Restart web (invalide le cache lru) =="
scalingo --region "$SCALINGO_REGION" --app "$SCALINGO_APP" restart web

echo "Reload termine."
