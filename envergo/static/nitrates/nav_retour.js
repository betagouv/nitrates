// Fleche retour de la page Aide & definitions (#453).
//
// Meme effet que le bouton retour du navigateur : on revient a la page
// d'avant (le simulateur, son formulaire restaure). Les ancres de la page
// (sommaire, liens entre termes) empilent des entrees d'historique : on les
// compte dans history.state pour revenir d'un coup a la page precedente.
// Arrivee directe (pas de page d'avant sur le site) : le lien suit son href,
// le simulateur.
(function () {
  "use strict";

  const lien = document.querySelector("[data-nitrates-retour]");
  if (!lien) return;

  function etat() {
    return history.state || {};
  }

  if (typeof etat().nitratesProfondeur !== "number") {
    history.replaceState(Object.assign({}, etat(), { nitratesProfondeur: 0 }), "");
  }
  let profondeur = etat().nitratesProfondeur;

  window.addEventListener("hashchange", function () {
    if (typeof etat().nitratesProfondeur === "number") {
      // retour / avance du navigateur sur une entree deja comptee
      profondeur = etat().nitratesProfondeur;
    } else {
      profondeur += 1;
      history.replaceState(
        Object.assign({}, etat(), { nitratesProfondeur: profondeur }),
        ""
      );
    }
  });

  function pagePrecedenteSurLeSite() {
    if (history.length <= profondeur + 1) return false; // nouvel onglet
    try {
      return new URL(document.referrer).origin === window.location.origin;
    } catch (e) {
      return false; // pas de referrer
    }
  }

  lien.addEventListener("click", function (e) {
    if (!pagePrecedenteSurLeSite()) return;
    e.preventDefault();
    history.go(-(profondeur + 1));
  });
})();
