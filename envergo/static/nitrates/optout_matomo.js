// Opt-out Matomo de la page Donnees personnelles (#592).
//
// API du tracker documentee par Matomo (custom opt-out) : on lit l'etat avec
// isUserOptedOut une fois matomo.js charge, puis optUserOut / forgetUserOptOut
// au changement de la case. optUserOut retient le refus 30 ans par defaut :
// on passe 13 mois (en heures), duree max des traceurs pour la CNIL.
(function () {
  "use strict";

  const caseOptout = document.querySelector("[data-nitrates-optout]");
  if (!caseOptout) return;
  const etat = document.getElementById("matomo-optout-etat");
  const TREIZE_MOIS_EN_HEURES = 395 * 24;

  window._paq = window._paq || [];
  let trackerCharge = false;

  function afficher(refuse, annoncer) {
    caseOptout.checked = !refuse;
    caseOptout.disabled = false;
    if (annoncer) {
      etat.textContent = refuse
        ? "Vos visites ne sont plus comptées dans les statistiques de fréquentation."
        : "Vos visites sont de nouveau comptées dans les statistiques de fréquentation.";
    }
  }

  window._paq.push([
    function () {
      trackerCharge = true;
      afficher(this.isUserOptedOut(), false);
    },
  ]);

  // matomo.js bloque (bloqueur, protection contre le pistage) : rien n'est
  // envoye, la case reste inactive et on le dit.
  setTimeout(function () {
    if (!trackerCharge) {
      etat.textContent =
        "Votre navigateur bloque déjà la mesure d'audience : aucune donnée n'est envoyée.";
    }
  }, 5000);

  caseOptout.addEventListener("change", function () {
    if (caseOptout.checked) {
      window._paq.push(["forgetUserOptOut"]);
    } else {
      window._paq.push(["optUserOut", TREIZE_MOIS_EN_HEURES]);
    }
    window._paq.push([
      function () {
        afficher(this.isUserOptedOut(), true);
      },
    ]);
  });
})();
