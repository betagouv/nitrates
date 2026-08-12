/* #284 — WIP : vers de terre "groovy" qui se déplacent horizontalement et se
 * croisent (les uns vers la droite, les autres vers la gauche), en souriant et
 * en ondulant façon danse. Page de design dédiée (/sandbox/vers-design/) — on
 * itère ici, puis on remplacera feedback_vers.js quand ce sera validé.
 *
 * Référence visuelle : mascotte lombric mignonne (corps rosé-brun segmenté,
 * grands yeux, large sourire, contour net) — cf. iStock/Dreamstime.
 *
 * API : window.nitratesVersGroovy(conteneur, {nombre}) monte l'animation.
 */
(function () {
  "use strict";

  // Palette lombric (rosé-brun terreux), dégradé pour le volume.
  var CORPS = "#cf847a";
  var CORPS_FONCE = "#b56458";
  var CORPS_CLAIR = "#e6a89e";
  var CONTOUR = "#95504a";
  var CLITELLUM = "#eec4ba";

  // Un ver vu de PROFIL, orienté vers la droite (tête à droite), qui ondule.
  // viewBox large (0 0 120 48) : corps allongé horizontal. Le corps est un
  // chemin animé (les points montent/descendent) -> effet reptation groovy.
  // Ici on pose la forme de base ; l'ondulation se fait en CSS (transform sur
  // des segments) + un léger "bob". id unique par ver via `k`.
  function svgVer(k) {
    var gid = "vg-" + k;
    return (
      '<svg class="vg-svg" viewBox="0 0 120 48" width="120" height="48" ' +
      'aria-hidden="true" xmlns="http://www.w3.org/2000/svg">' +
      "<defs>" +
      '<linearGradient id="' +
      gid +
      '" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" stop-color="' +
      CORPS_CLAIR +
      '"/>' +
      '<stop offset="0.55" stop-color="' +
      CORPS +
      '"/>' +
      '<stop offset="1" stop-color="' +
      CORPS_FONCE +
      '"/>' +
      "</linearGradient>" +
      "</defs>" +
      // corps ondulé (queue à gauche, tête à droite)
      '<path class="vg-corps" d="M8 30 Q26 14 46 28 T88 26 T112 26" ' +
      'fill="none" stroke="' +
      CONTOUR +
      '" stroke-width="18" stroke-linecap="round"/>' +
      '<path class="vg-corps" d="M8 30 Q26 14 46 28 T88 26 T112 26" ' +
      'fill="none" stroke="url(#' +
      gid +
      ')" stroke-width="15" stroke-linecap="round"/>' +
      // reflet dorsal
      '<path class="vg-corps" d="M8 30 Q26 14 46 28 T88 26 T112 26" ' +
      'fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" ' +
      'opacity="0.22" transform="translate(0,-3)"/>' +
      // clitellum (anneau clair vers le tiers avant)
      '<ellipse cx="74" cy="26" rx="6" ry="9" fill="' +
      CLITELLUM +
      '" opacity="0.8"/>' +
      // tête ronde à droite
      '<circle cx="110" cy="26" r="10" fill="url(#' +
      gid +
      ')" stroke="' +
      CONTOUR +
      '" stroke-width="1.6"/>' +
      // yeux
      '<circle cx="108" cy="23" r="2.3" fill="#fff"/>' +
      '<circle cx="114" cy="23" r="2.3" fill="#fff"/>' +
      '<circle cx="108.5" cy="23.4" r="1.3" fill="#33221f"/>' +
      '<circle cx="114.5" cy="23.4" r="1.3" fill="#33221f"/>' +
      '<circle cx="108.9" cy="22.8" r="0.45" fill="#fff"/>' +
      '<circle cx="114.9" cy="22.8" r="0.45" fill="#fff"/>' +
      // sourire groovy
      '<path d="M106.5 28 Q111 32.5 115.5 28" fill="none" stroke="#33221f" ' +
      'stroke-width="1.8" stroke-linecap="round"/>' +
      // joues
      '<circle cx="105.5" cy="27.5" r="1.6" fill="#ff9a8a" opacity="0.55"/>' +
      '<circle cx="116.5" cy="27.5" r="1.6" fill="#ff9a8a" opacity="0.55"/>' +
      "</svg>"
    );
  }

  // Voies horizontales : chaque ver a une hauteur (top %), un sens (dir : +1
  // vers la droite, -1 vers la gauche), une durée (vitesse), un délai. Les sens
  // alternés + hauteurs proches -> ils se croisent.
  //
  // Vitesse : la référence agréable (retour Max) est ~6.5 s (le sens
  // droite->gauche). On reste AUTOUR de cette valeur, plus lent globalement,
  // avec une petite variation individuelle (chaque ver a son propre tempo,
  // comme des individus séparés) — mais jamais rapide au point de fatiguer.
  var VOIES = [
    { top: 8, dir: -1, dur: 7.4, delai: 0.0 },
    { top: 30, dir: 1, dur: 6.6, delai: 0.9 },
    { top: 52, dir: -1, dur: 8.2, delai: 0.4 },
    { top: 70, dir: 1, dur: 7.0, delai: 1.4 },
  ];

  function nitratesVersGroovy(conteneur, opts) {
    if (!conteneur) return;
    var nombre = Math.max(1, Math.min((opts && opts.nombre) || 4, VOIES.length));
    conteneur.classList.add("vg-scene");
    conteneur.innerHTML = "";
    for (var i = 0; i < nombre; i++) {
      var v = VOIES[i];
      var el = document.createElement("div");
      el.className = "vg-ver " + (v.dir === 1 ? "vg-vers-droite" : "vg-vers-gauche");
      el.style.top = v.top + "%";
      el.style.setProperty("--dur", v.dur + "s");
      el.style.setProperty("--delai", v.delai + "s");
      el.innerHTML = svgVer(i);
      conteneur.appendChild(el);
    }
  }

  if (typeof window !== "undefined") {
    window.nitratesVersGroovy = nitratesVersGroovy;
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { nitratesVersGroovy: nitratesVersGroovy, svgVer: svgVer };
  }
})();
