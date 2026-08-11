#!/usr/bin/env bash
# Etape 3 : redemarrage du web apres deploiement du code.
#
# CE SCRIPT NE TOUCHE PAS AUX DONNEES. Il remplace l'ancien
# deploy_dev_reload.sh, qui rechargeait les arbres et les referentiels depuis
# le depot a chaque deploiement.
#
# Pourquoi ce changement (2026-08-11)
# -----------------------------------
# Les donnees ne suivent pas le cycle de vie du code. Le code descend de dev
# vers staging puis prod. Les arbres, eux, sont edites la ou se trouve la
# connaissance metier -- en pratique sur l'environnement le plus eleve, par
# les juristes -- et doivent ensuite etre propages vers le bas. Faire porter
# les deux flux par le meme pipeline rend l'ensemble ingerable, et surtout
# expose a une perte : un deploiement de code n'a aucune raison de reecrire
# une regle metier saisie en base.
#
# Le declencheur : au deploiement du 2026-08-11, `dump_active_trees --check`
# a signale que national.yaml divergeait de la base, et `load_arbres_actifs`
# a malgre tout empile une version par-dessus. Detecter le conflit sans
# s'arreter est le pire des comportements possibles.
#
# Les arbres et les referentiels sont donc desormais propages A LA MAIN, en
# operation ops assumee, comme on traiterait une bascule de donnees en base.
# Le depot reste un MIROIR (dump_active_trees / dump_referentiels), pas une
# source d'autorite : l'autorite est la base de l'environnement cible.
#
# Le restart, lui, reste indispensable : les loaders sont en @lru_cache
# process-local, donc sans redemarrage le web continue de servir l'ancien
# contenu apres un deploiement de code (gotcha post-mortem).

set -euo pipefail
cd "$(dirname "$0")/../.."
source .github/scripts/_scalingo_oneoff.sh

echo "== Restart web (invalide le cache lru) =="
scalingo --region "$SCALINGO_REGION" --app "$SCALINGO_APP" restart web

echo "Restart termine."
echo
echo "RAPPEL : ce deploiement n'a PAS touche aux arbres ni aux referentiels."
echo "Pour propager des donnees, voir docs/propagation-donnees.md (operation"
echo "manuelle, deliberee, avec sauvegarde prealable)."
