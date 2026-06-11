// Bascule de theme clair / sombre du simulateur nitrates (#83).
//
// Par defaut le site suit l'OS : le DSFR est rendu avec data-fr-scheme="system"
// (cf. multisite_base.html) et applique prefers-color-scheme tout seul. Ce
// script ajoute un choix EXPLICITE memorise : si l'utilisateur a clique soleil
// ou lune, on force ce theme et on le retient (localStorage) ; sinon on reste
// en "system".
//
// On pilote les deux attributs DSFR :
//   - data-fr-scheme : la PREFERENCE ("system" | "light" | "dark")
//   - data-fr-theme  : le theme EFFECTIF applique ("light" | "dark"), que le
//     DSFR lit pour ses tokens de couleur. On le calcule nous-memes pour ne
//     pas dependre du JS DSFR (timing) et pour refleter prefers-color-scheme
//     en mode system.

(function () {
  "use strict";

  var STORAGE_KEY = "nitrates-theme"; // "light" | "dark" | absent (=system)
  var root = document.documentElement;

  function prefereSombre() {
    return (
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
    );
  }

  // Applique une preference : "light", "dark" ou "system".
  function appliquer(pref) {
    var effectif;
    if (pref === "light" || pref === "dark") {
      root.setAttribute("data-fr-scheme", pref);
      effectif = pref;
    } else {
      root.setAttribute("data-fr-scheme", "system");
      effectif = prefereSombre() ? "dark" : "light";
    }
    root.setAttribute("data-fr-theme", effectif);
    majBoutons(pref);
  }

  // Met en avant le bouton correspondant a la preference courante.
  function majBoutons(pref) {
    var actif = pref === "light" || pref === "dark" ? pref : null;
    var btns = document.querySelectorAll(".nitrates-theme-toggle__btn");
    for (var i = 0; i < btns.length; i++) {
      var b = btns[i];
      var on = actif !== null && b.dataset.themeChoice === actif;
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.classList.toggle("nitrates-theme-toggle__btn--active", on);
    }
  }

  function prefStockee() {
    try {
      var v = localStorage.getItem(STORAGE_KEY);
      return v === "light" || v === "dark" ? v : null;
    } catch (e) {
      return null;
    }
  }

  function stocker(pref) {
    try {
      if (pref === "light" || pref === "dark") {
        localStorage.setItem(STORAGE_KEY, pref);
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch (e) {
      /* mode prive / quota : on ignore, le choix tient pour la session */
    }
  }

  // Init : applique la preference stockee, sinon system.
  appliquer(prefStockee() || "system");

  // Si on est en mode system, suivre les changements d'OS a chaud.
  if (window.matchMedia) {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    var onChange = function () {
      if (!prefStockee()) appliquer("system");
    };
    if (mq.addEventListener) mq.addEventListener("change", onChange);
    else if (mq.addListener) mq.addListener(onChange);
  }

  // Clics sur les boutons soleil / lune.
  function bind() {
    var btns = document.querySelectorAll(".nitrates-theme-toggle__btn");
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener("click", function () {
        var choix = this.dataset.themeChoice; // "light" | "dark"
        // Re-cliquer le theme deja actif = revenir en "system" (auto).
        var courant = prefStockee();
        var pref = courant === choix ? "system" : choix;
        stocker(pref);
        appliquer(pref);
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
