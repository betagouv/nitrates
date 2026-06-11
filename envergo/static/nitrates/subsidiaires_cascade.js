// Cascade des questions complementaires conditionnelles (#58.1).
//
// Le serveur peut rendre des questions avec un parent (data-qc-parent-champ
// + data-qc-parent-valeur), initialement cachees (attribut `hidden`).
// On les revele/recache quand l'utilisateur clique la bonne valeur sur la
// question parent. Resultat : un seul aller-retour serveur pour repondre a
// toute la cascade de questions complementaires.

(function () {
  "use strict";

  const panneau = document.querySelector(".resultat-panel--questions");
  if (!panneau) return;

  const groupes = Array.from(panneau.querySelectorAll(".qc-question"));
  if (groupes.length === 0) return;

  // Index : pour chaque champ parent, quels groupes conditionnels en
  // dependent ?
  const dependants = new Map();  // parent_champ -> [groupe, ...]
  for (const g of groupes) {
    const parent = g.dataset.qcParentChamp;
    if (!parent) continue;
    if (!dependants.has(parent)) dependants.set(parent, []);
    dependants.get(parent).push(g);
  }

  function valeurActuelle(champ) {
    const checked = document.querySelector(
      `input[type="radio"][name="${champ}"]:checked`
    );
    return checked ? checked.value : null;
  }

  function decocherGroupe(groupe) {
    for (const radio of groupe.querySelectorAll('input[type="radio"]')) {
      radio.checked = false;
    }
  }

  function rafraichirVisibilite(parentChamp) {
    const valeur = valeurActuelle(parentChamp);
    for (const g of dependants.get(parentChamp) || []) {
      const attendue = g.dataset.qcParentValeur;
      if (valeur !== null && String(valeur) === String(attendue)) {
        g.hidden = false;
      } else {
        g.hidden = true;
        decocherGroupe(g);
      }
    }
  }

  // Listeners sur les radios des questions parents
  for (const parentChamp of dependants.keys()) {
    const radios = document.querySelectorAll(
      `input[type="radio"][name="${parentChamp}"]`
    );
    for (const r of radios) {
      r.addEventListener("change", () => rafraichirVisibilite(parentChamp));
    }
    // Sync initial (cas ou un parent est deja coche par checked depuis l'URL)
    rafraichirVisibilite(parentChamp);
  }

  // L'auto-scroll vers les QC est gere par scroll_resultat.js (#112), qui
  // couvre aussi le cas "resultat final" et attend la stabilisation du layout
  // (carte Leaflet, images) avant de scroller.
})();
