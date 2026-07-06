// Barre de progression du parcours simulateur (Carte #154).
//
// Barre fine fixee en haut, pleine largeur, facon YouTube. Elle avance a
// mesure que l'utilisateur repond aux questions, pour l'accompagner et
// l'engager dans le parcours.
//
// Calcul (volontairement simple, cf. decision Max) : on compte des ETAPES.
//   - Localisation (parcelle placee sur la carte)   : 1 etape
//   - categorie_culture / sous_culture_form
//     / categorie_fertilisant / sous_fertilisant    : 4 etapes
//   - Reserve pour questions complementaires (QC)    : 1 etape
// Total = 6 etapes. Reserve QC volontairement a 1 (Max) : s'il y a plusieurs
// QC, la barre progresse moins par QC, mais elle ne "recule" jamais (cf.
// ci-dessous).
//
// MONOTONIE + PERSISTANCE (points cles) : le parcours QC est un GET full-reload
// a chaque etape. Sans precaution, la barre repartait de 0 a chaque rechargement
// et pouvait "reculer". On persiste donc le MAX atteint en sessionStorage :
//   - au chargement, on pose la barre directement (sans animation) a la valeur
//     memorisee, puis on calcule l'etat courant ;
//   - la barre ne DIMINUE jamais : on n'affiche que max(memorise, courant).
// La cle est remise a zero quand un nouveau parcours demarre (pas de
// localisation ET aucune reponse) -> "Recommencer" repart proprement.

(function () {
  "use strict";

  var LOC_ETAPES = 1;
  var CHAMPS = [
    "categorie_culture",
    "sous_culture_form",
    "categorie_fertilisant",
    "sous_fertilisant",
  ];
  var QC_RESERVE = 1;
  var TOTAL = LOC_ETAPES + CHAMPS.length + QC_RESERVE; // 6
  var STORAGE_KEY = "nitrates_progress_pct";

  var barre = document.getElementById("nitrates-progress-bar");
  if (!barre) return;
  var fill = barre.querySelector(".nitrates-progress__fill");
  if (!fill) return;

  function lireMemo() {
    try {
      var v = parseFloat(sessionStorage.getItem(STORAGE_KEY));
      return isNaN(v) ? 0 : v;
    } catch (e) {
      return 0;
    }
  }
  function ecrireMemo(v) {
    try {
      sessionStorage.setItem(STORAGE_KEY, String(v));
    } catch (e) {
      /* sessionStorage indispo : on degrade sans planter */
    }
  }

  function estRepondu(name) {
    return !!document.querySelector(
      'input[type="radio"][name="' + name + '"]:checked'
    );
  }

  function valeurDe(name) {
    var r = document.querySelector(
      'input[type="radio"][name="' + name + '"]:checked'
    );
    return r ? r.value : "";
  }

  function localisationFaite() {
    var lat = document.getElementById("id_lat");
    var lng = document.getElementById("id_lng");
    return !!(lat && lng && lat.value && lng.value);
  }

  // Nombre de QC repondues (parents + enfants), plafonne a la reserve.
  function qcRepondues() {
    var groupes = document.querySelectorAll(".qc-question");
    var n = 0;
    for (var i = 0; i < groupes.length; i++) {
      var g = groupes[i];
      if (g.hidden) continue;
      if (g.querySelector('input[type="radio"]:checked')) n++;
    }
    return Math.min(n, QC_RESERVE);
  }

  function etapesFaites() {
    var n = 0;
    if (localisationFaite()) n += LOC_ETAPES;
    for (var i = 0; i < CHAMPS.length; i++) {
      var champ = CHAMPS[i];
      if (estRepondu(champ)) {
        n++;
      } else if (
        champ === "sous_culture_form" &&
        estRepondu("categorie_culture") &&
        valeurDe("categorie_culture") === "sol_non_cultive"
      ) {
        // Branche sans sous-culture : l'etape est consideree faite.
        n++;
      }
    }
    n += qcRepondues();
    return n;
  }

  function pctCourant() {
    var pct = Math.round((etapesFaites() / TOTAL) * 100);
    if (pct < 0) pct = 0;
    if (pct > 100) pct = 100;
    return pct;
  }

  // Applique une valeur a la barre. anime=false -> pas de transition (utilise au
  // 1er poser pour ne pas "rejouer" l'animation depuis 0 apres un reload).
  function appliquer(pct, anime) {
    if (!anime) {
      var prev = fill.style.transition;
      fill.style.transition = "none";
      fill.style.width = pct + "%";
      // force reflow puis restaure la transition pour les MAJ suivantes
      void fill.offsetWidth;
      fill.style.transition = prev || "";
    } else {
      fill.style.width = pct + "%";
    }
    barre.setAttribute("aria-valuenow", String(pct));
    barre.classList.toggle("is-visible", pct > 0);
  }

  // Debut de parcours (aucune localisation, aucune reponse) : on repart de zero
  // -> le memo est reinitialise (utile apres "Recommencer").
  function parcoursVierge() {
    if (localisationFaite()) return false;
    for (var i = 0; i < CHAMPS.length; i++) {
      if (estRepondu(CHAMPS[i])) return false;
    }
    return true;
  }

  // ── Init : poser la barre a la valeur memorisee SANS animation, puis
  //    reconcilier avec l'etat courant (jamais en dessous du memo). ──
  if (parcoursVierge()) {
    ecrireMemo(0);
  }
  var affiche = lireMemo();
  appliquer(affiche, false);

  function maj(anime) {
    var courant = pctCourant();
    if (courant > affiche) {
      affiche = courant; // MONOTONE : ne recule jamais
      ecrireMemo(affiche);
    }
    appliquer(affiche, anime !== false);
  }

  // Reconciliation courante juste apres l'init (au cas ou l'etat courant serait
  // deja plus avance que le memo, ex parcours rejoue depuis l'URL).
  maj(false);

  // Recalcul a chaque interaction pertinente (radios form principal, split
  // couvert, QC), et a la revelation du form apres localisation.
  document.addEventListener("change", function (e) {
    if (e.target && e.target.type === "radio") maj(true);
  });
  document.addEventListener("nitrates:form-revealed", function () {
    maj(true);
  });
})();
