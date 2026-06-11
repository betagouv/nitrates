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

  function setScrolled(on) {
    root.classList.toggle("scrolled", on);
    document.body.classList.toggle("nitrates-construction-scrolled", on);
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
