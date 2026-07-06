// Bandeau "site en construction" (issue #113).
// Deux elements se relaient en fondu doux :
//  - un ruban 45deg dans le coin (visible tant que le header est a l'ecran) ;
//  - une barre fine sticky top (fondu entrant des que le header sort).
// Le declencheur n'est PAS le 1er pixel scrolle mais la disparition du
// header : la barre apparait pile quand on ne voit plus "Programme National
// Nitrates". On observe donc le header via IntersectionObserver.
(function () {
  "use strict";

  var root = document.querySelector("[data-nitrates-construction]");
  if (!root) {
    return;
  }

  // #151 : hysteresis anti-flicker. On ignore toute re-bascule survenant
  // moins de MIN_TOGGLE_MS apres la precedente. Au scroll/zoom tres lent,
  // le reflow peut faire osciller l'etat d'intersection pile au seuil ;
  // ce verrou temporel empeche le va-et-vient rapide de la classe (et donc
  // les sauts visuels de la section header).
  var MIN_TOGGLE_MS = 150;
  var currentOn = root.classList.contains("scrolled");
  var lastToggleAt = 0;
  var pending = null;

  function applyScrolled(on) {
    currentOn = on;
    // Plus de classe sur <body> (#151) : le padding-top qu'elle posait
    // deplacait le header observe -> boucle de retroaction. La barre est
    // en position:fixed, elle n'a pas besoin de reserver d'espace dans le flux.
    root.classList.toggle("scrolled", on);
    // Miroir sur <html> (Carte #154) : la barre de progression du simulateur
    // est ailleurs dans le DOM (avant le bandeau) -> pas de selecteur frere
    // possible. On expose l'etat sur <html> pour qu'elle se cale SOUS le
    // bandeau construction quand il est affiche.
    document.documentElement.classList.toggle(
      "nitrates-construction-visible",
      on
    );
  }

  function setScrolled(on) {
    if (on === currentOn) {
      return;
    }
    var now =
      window.performance && window.performance.now
        ? window.performance.now()
        : Date.now();
    var elapsed = now - lastToggleAt;
    if (pending) {
      clearTimeout(pending);
      pending = null;
    }
    if (elapsed >= MIN_TOGGLE_MS) {
      lastToggleAt = now;
      applyScrolled(on);
    } else {
      // trop tot : on differe et on ne garde que la derniere intention
      pending = setTimeout(function () {
        pending = null;
        lastToggleAt =
          window.performance && window.performance.now
            ? window.performance.now()
            : Date.now();
        applyScrolled(on);
      }, MIN_TOGGLE_MS - elapsed);
    }
  }

  // Le header legacy nitrates (banniere principale "Programme National
  // Nitrates"). Quand il quitte le viewport, on bascule en barre.
  var header = document.querySelector("header.fr-header.header-legacy");

  if (header && "IntersectionObserver" in window) {
    var observer = new IntersectionObserver(
      function (entries) {
        // header visible -> ruban ; header hors-ecran -> barre
        setScrolled(!entries[0].isIntersecting);
      },
      // un petit margin negatif evite que la barre clignote pile au ras
      { threshold: 0, rootMargin: "0px 0px -8px 0px" }
    );
    observer.observe(header);
    return;
  }

  // Fallback (pas de header trouve ou pas d'IO) : bascule au scroll.
  var scrolled = false;
  window.addEventListener(
    "scroll",
    function () {
      var on = window.scrollY > 80;
      if (on !== scrolled) {
        scrolled = on;
        setScrolled(on);
      }
    },
    { passive: true }
  );
})();
