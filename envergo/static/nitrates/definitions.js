// Scrollspy du sommaire de la page « Aide & définitions » (batch 2 #110).
//
// Pendant le scroll, l'entrée du sommaire correspondant à la section visible
// prend le liseré + texte violet (retour Max sur la maquette Coralie : suivi
// visuel de la lecture). On pose aria-current="true" sur le lien actif (l'état
// sémantique DSFR) et le style violet vit dans definitions.css.
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    const sections = Array.prototype.slice.call(
      document.querySelectorAll(".definitions-section[id]")
    );
    const liens = {};
    let vide = true;
    sections.forEach(function (s) {
      const lien = document.querySelector(
        '.fr-sidemenu__link[href="#' + s.id + '"]'
      );
      if (lien) {
        liens[s.id] = lien;
        vide = false;
      }
    });
    if (vide) return;

    let courant = null;
    // Verrou après clic sommaire : l'ancre choisie reste active tant que
    // l'utilisateur n'a pas re-scrollé lui-même. Sans ça, une section courte
    // en fin de page est « insélectionnable » (le saut d'ancre bute sur le
    // bas de page avant que son haut franchisse le seuil, et le spy rebascule
    // aussitôt sur la section précédente).
    let verrouClick = false;

    function activer(id) {
      if (id === courant) return;
      if (courant && liens[courant]) {
        liens[courant].removeAttribute("aria-current");
      }
      if (id && liens[id]) liens[id].setAttribute("aria-current", "true");
      courant = id;
    }

    function majSection() {
      if (verrouClick) return;
      // Page scrollée jusqu'en bas : la dernière section est active même si
      // son haut n'a jamais franchi le seuil (section courte en fin de page,
      // impossible à « sélectionner » autrement).
      const enBas =
        window.innerHeight + window.scrollY >=
        document.documentElement.scrollHeight - 4;
      if (enBas) {
        activer(sections[sections.length - 1].id);
        return;
      }
      // Section courante = la dernière dont le haut est passé au-dessus du
      // tiers supérieur du viewport (lecture naturelle, déterministe).
      const seuil = window.innerHeight / 3;
      let actif = sections[0] ? sections[0].id : null;
      sections.forEach(function (s) {
        if (s.getBoundingClientRect().top <= seuil) actif = s.id;
      });
      activer(actif);
    }

    let prevu = false;
    function planifier() {
      if (prevu) return;
      prevu = true;
      requestAnimationFrame(function () {
        prevu = false;
        majSection();
      });
    }

    window.addEventListener("scroll", planifier, { passive: true });
    window.addEventListener("resize", planifier);

    // Clic sommaire : activation directe de l'entrée cliquée + verrou.
    Object.keys(liens).forEach(function (id) {
      liens[id].addEventListener("click", function () {
        verrouClick = true;
        activer(id);
      });
    });
    // Scroll volontaire (molette / tactile / clavier) : le spy reprend.
    ["wheel", "touchmove", "keydown"].forEach(function (evt) {
      window.addEventListener(
        evt,
        function () {
          verrouClick = false;
        },
        { passive: true }
      );
    });

    majSection();
  });
})();
