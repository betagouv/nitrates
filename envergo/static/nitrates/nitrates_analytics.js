// Tracking metier nitrates -> Matomo (events trackEvent).
//
// Le tag Matomo lui-meme (visites, rebond, devices, navigateurs) est injecte
// par _analytics.html des que ANALYTICS["NITRATES"].TRACKER_ENABLED est vrai ;
// ce module n'ajoute QUE les 4 compteurs metier demandes, en events Matomo :
//
//   Categorie "Simulateur"
//     - RechercheCommune     : l'utilisateur a choisi une commune via la
//                              recherche (autocomplete BAN).
//     - SelectionPointCarte  : l'utilisateur a clique DIRECTEMENT sur la carte
//                              (hors selection via la recherche de commune).
//     - SimulationLancee     : l'utilisateur a soumis le formulaire (clic
//                              "Lancer la simulation").
//     - Simulation2Plus      : l'utilisateur a lance AU MOINS 2 simulations
//                              (compteur persistant par navigateur).
//
// Les events sont emis par simulator.js via des CustomEvent (couplage faible :
// pas de dependance a Matomo dans la logique carte/form). Ici on ecoute ces
// events et on relaie vers _paq. sendBeacon garantit que l'event part meme
// juste avant le full-reload GET de la soumission.
(function () {
  "use strict";

  var _paq = (window._paq = window._paq || []);

  // Fiabilise l'envoi juste avant une navigation (submit = GET full-reload) :
  // Matomo bascule sur navigator.sendBeacon au lieu d'une image bloquante.
  _paq.push(["alwaysUseSendBeacon"]);

  function track(action, name) {
    // name optionnel (ex: departement). Categorie fixe "Simulateur".
    if (name === undefined) {
      _paq.push(["trackEvent", "Simulateur", action]);
    } else {
      _paq.push(["trackEvent", "Simulateur", action, name]);
    }
  }

  document.addEventListener("nitrates:recherche-commune", function () {
    track("RechercheCommune");
  });

  document.addEventListener("nitrates:point-carte", function () {
    track("SelectionPointCarte");
  });

  // "Lancer la simulation" : compteur persistant pour derouler le "2+".
  // localStorage survit aux full-reload GET du parcours et aux sessions ; c'est
  // ce qui permet de compter un utilisateur qui revient lancer une 2e simu.
  var STORAGE_KEY = "nitrates_nb_simulations";

  document.addEventListener("nitrates:simulation-lancee", function (e) {
    var dept = (e && e.detail && e.detail.department) || undefined;
    track("SimulationLancee", dept);

    var n = 0;
    try {
      n = parseInt(window.localStorage.getItem(STORAGE_KEY) || "0", 10) || 0;
    } catch (err) {
      // localStorage indisponible (navigation privee stricte) : on degrade
      // sans casser, on ne pourra juste pas deriver le "2+" pour ce visiteur.
      n = 0;
    }
    n += 1;
    try {
      window.localStorage.setItem(STORAGE_KEY, String(n));
    } catch (err) {
      /* no-op */
    }
    // On emet Simulation2Plus UNE SEULE fois, au passage a la 2e simulation,
    // pour un compteur "au moins 2 simulations" propre (pas incremente a
    // chaque simu au-dela de 2).
    if (n === 2) {
      track("Simulation2Plus");
    }
  });
})();
