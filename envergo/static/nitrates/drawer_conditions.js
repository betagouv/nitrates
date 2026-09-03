// #271 chantier 3 — Drawer « Conditions d'épandage ».
//
// Panneau latéral qui slide depuis la droite (2/3 desktop, plein écran mobile).
// Ouvert par un bouton [data-drawer-open="<id>"], fermé par l'overlay, le bouton
// « Fermer » ([data-drawer-close]) ou la touche Échap. Verrouille le scroll du
// body tant qu'il est ouvert, et gère le focus (retour au déclencheur à la
// fermeture) pour l'accessibilité.

(function () {
  "use strict";

  var ouvert = null; // { drawer, declencheur }

  // Hauteur VISIBLE du bandeau « site en construction » (page publique). 0 s'il
  // est absent ou masqué (opacité ~0 tant qu'on n'a pas scrollé). Même mesure
  // que scroll_resultat.js.
  function hauteurBandeau() {
    var bandeau = document.querySelector(".nitrates-construction__bar");
    if (!bandeau) return 0;
    var r = bandeau.getBoundingClientRect();
    var style = window.getComputedStyle(bandeau);
    if (r.height > 0 && parseFloat(style.opacity) > 0.1) return r.height;
    return 0;
  }

  // #410 : la maquette place les tags de dates SOUS le titre. Or ce titre vit à
  // l'intérieur du bloc riche compilé (on ne découpe pas le bloc côté serveur).
  // On déplace donc le conteneur des tags juste après le titre, MAIS seulement
  // si le contenu COMMENCE par un titre (h1 > h2 > h3, premier trouvé) : sinon
  // les tags restent en tête, comme aujourd'hui.
  function placerBadgesSousTitre(drawer) {
    var contenu = drawer.querySelector(".drawer-conditions__contenu");
    var badges = drawer.querySelector("[data-drawer-application]");
    if (!contenu || !badges) return;
    // Premier élément de contenu réel après le bloc de tags.
    var suivant = badges.nextElementSibling;
    while (suivant && !suivant.textContent.trim()) {
      suivant = suivant.nextElementSibling;
    }
    if (!suivant) return;
    // Le titre est soit ce bloc lui-même, soit son tout premier descendant.
    var titre = suivant.matches("h1, h2, h3")
      ? suivant
      : suivant.querySelector("h1, h2, h3");
    if (!titre) return;
    // Vérifie que le titre est bien EN TÊTE (rien de textuel avant lui dans le
    // bloc), sinon on n'insère pas : les tags précéderaient du contenu.
    var avant = document.createRange();
    avant.setStart(suivant, 0);
    avant.setEndBefore(titre);
    if (avant.toString().trim()) return;
    titre.after(badges);
  }

  function ouvrir(drawer, declencheur) {
    if (ouvert) fermer();
    // Reparente le drawer sous <body> : il est en position: fixed et pourrait
    // sinon être clippé/piégé par un ancêtre (`.results-row { overflow: clip }`,
    // transform du result-col…). On mémorise son emplacement d'origine pour le
    // remettre à la fermeture (le contenu dépend de la règle rendue là).
    if (drawer.parentNode !== document.body) {
      drawer._ancre = document.createComment("drawer-conditions-ancre");
      drawer.parentNode.insertBefore(drawer._ancre, drawer);
      document.body.appendChild(drawer);
    }
    drawer.hidden = false;
    // #410 : dates sous le titre. À l'ouverture, car pour une règle calculatrice
    // les tags sont injectés en asynchrone par calculatrice-calendrier.js.
    placerBadgesSousTitre(drawer);
    // #271 : sur la page publique `/`, un bandeau « site en construction » fixe
    // occupe le haut (position: fixed, top: 0). Le drawer (top: 0 aussi) passait
    // dessous -> son en-tête (Fermer) était caché. On décale donc le panneau ET
    // l'overlay de la hauteur VISIBLE du bandeau.
    var offsetHaut = hauteurBandeau();
    var panel = drawer.querySelector(".drawer-conditions__panel");
    var overlay = drawer.querySelector(".drawer-conditions__overlay");
    if (panel) panel.style.top = offsetHaut + "px";
    if (overlay) overlay.style.top = offsetHaut + "px";
    // Force un reflow avant d'ajouter la classe --ouvert pour jouer la transition.
    void drawer.offsetWidth;
    drawer.classList.add("drawer-conditions--ouvert");
    document.body.classList.add("drawer-open");
    ouvert = { drawer: drawer, declencheur: declencheur };
    // Focus sur le bouton Fermer (premier élément focusable du panneau).
    var fermerBtn = drawer.querySelector("[data-drawer-close]");
    if (fermerBtn && fermerBtn.focus) fermerBtn.focus();
  }

  function fermer() {
    if (!ouvert) return;
    var drawer = ouvert.drawer;
    var declencheur = ouvert.declencheur;
    drawer.classList.remove("drawer-conditions--ouvert");
    document.body.classList.remove("drawer-open");
    // Attendre la fin de la transition avant de remettre hidden (sinon coupure).
    var fini = false;
    var cacher = function () {
      if (fini) return;
      fini = true;
      drawer.hidden = true;
      drawer.removeEventListener("transitionend", cacher);
    };
    drawer.addEventListener("transitionend", cacher);
    setTimeout(cacher, 400); // filet si transitionend ne se déclenche pas
    ouvert = null;
    // Remet le drawer à son emplacement d'origine (sous la règle) une fois caché,
    // pour que le calendrier dynamique continue de cibler [data-drawer-badges-asc].
    if (drawer._ancre && drawer._ancre.parentNode) {
      setTimeout(function () {
        if (!ouvert && drawer._ancre && drawer._ancre.parentNode) {
          drawer._ancre.parentNode.insertBefore(drawer, drawer._ancre);
          drawer._ancre.parentNode.removeChild(drawer._ancre);
          drawer._ancre = null;
        }
      }, 420);
    }
    // Rendre le focus au bouton déclencheur.
    if (declencheur && declencheur.focus) declencheur.focus();
  }

  // Délégation : ouverture / fermeture.
  document.addEventListener("click", function (e) {
    var openBtn = e.target.closest("[data-drawer-open]");
    if (openBtn) {
      var id = openBtn.getAttribute("data-drawer-open");
      var drawer = document.getElementById(id);
      if (drawer) {
        e.preventDefault();
        ouvrir(drawer, openBtn);
      }
      return;
    }
    if (e.target.closest("[data-drawer-close]")) {
      e.preventDefault();
      fermer();
    }
  });

  // Échap ferme le drawer ouvert.
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && ouvert) {
      e.preventDefault();
      fermer();
    }
  });
})();
