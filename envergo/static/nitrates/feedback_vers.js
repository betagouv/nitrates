/* #284 — Génère l'animation "reward" : N petits lombrics contents qui
 * flottent et sourient dans un conteneur. Sobre mais mignon, couleur ver de
 * terre (lombric), pas façon caca (formes rondes lisses, sourire net, yeux).
 *
 * API : window.nitratesVersReward(conteneur, {nombre}) monte l'animation.
 * Exposé aussi comme module Node pour tests éventuels.
 */
(function () {
  "use strict";

  // Palette lombric : rosé-brun terreux, avec une variante plus claire pour le
  // ventre/segments et un liseré plus foncé pour le contour.
  const CORPS = "#c4756a"; // ver de terre rosé-brun
  const CORPS_CLAIR = "#d99a90"; // segments/ventre
  const CONTOUR = "#9c574e"; // liseré
  const CLITELLUM = "#e2b7ab"; // l'anneau clair caractéristique du lombric

  // SVG d'un lombric souriant, courbé en U doux. viewBox 0 0 64 64.
  function svgVer(index) {
    // On alterne l'orientation (miroir) pour varier un peu.
    const flip = index % 2 === 1 ? " transform=\"scale(-1,1) translate(-64,0)\"" : "";
    return `
<svg viewBox="0 0 64 64" width="64" height="64" role="img" aria-hidden="true"
     xmlns="http://www.w3.org/2000/svg">
  <g${flip}>
    <!-- corps courbé (chemin épais arrondi) -->
    <path d="M14 46
             C 10 30, 20 16, 34 18
             C 46 20, 50 30, 46 38"
          fill="none" stroke="${CONTOUR}" stroke-width="16"
          stroke-linecap="round"/>
    <path d="M14 46
             C 10 30, 20 16, 34 18
             C 46 20, 50 30, 46 38"
          fill="none" stroke="${CORPS}" stroke-width="13"
          stroke-linecap="round"/>
    <!-- segments (petits traits clairs le long du corps) -->
    <path d="M14 46
             C 10 30, 20 16, 34 18
             C 46 20, 50 30, 46 38"
          fill="none" stroke="${CORPS_CLAIR}" stroke-width="13"
          stroke-linecap="round" stroke-dasharray="1.5 6" opacity="0.55"/>
    <!-- clitellum : anneau clair vers le milieu du corps -->
    <circle cx="34" cy="18" r="7.5" fill="${CLITELLUM}"/>
    <!-- tête (extrémité haute droite) + visage -->
    <circle cx="46" cy="38" r="8.5" fill="${CORPS}" stroke="${CONTOUR}" stroke-width="1.5"/>
    <!-- yeux -->
    <circle cx="44" cy="36" r="1.6" fill="#3a2420"/>
    <circle cx="49" cy="36" r="1.6" fill="#3a2420"/>
    <!-- petites brillances d'yeux -->
    <circle cx="43.5" cy="35.4" r="0.5" fill="#fff"/>
    <circle cx="48.5" cy="35.4" r="0.5" fill="#fff"/>
    <!-- sourire -->
    <path d="M43 40 Q46.5 43.5, 50 40" fill="none" stroke="#3a2420"
          stroke-width="1.6" stroke-linecap="round"/>
    <!-- petites joues roses -->
    <circle cx="42.5" cy="39.5" r="1.3" fill="#e88" opacity="0.5"/>
    <circle cx="50.5" cy="39.5" r="1.3" fill="#e88" opacity="0.5"/>
  </g>
</svg>`;
  }

  // Positions relatives (en %) réparties, avec rotation/amplitude variées pour
  // un rendu vivant mais non aléatoire (déterministe -> pas de flicker).
  const PLACEMENTS = [
    { left: 12, top: 20, rot: -8, delai: 0.0, scale: 1.0 },
    { left: 40, top: 6, rot: 5, delai: 0.12, scale: 1.15 },
    { left: 68, top: 22, rot: -4, delai: 0.24, scale: 0.95 },
    { left: 26, top: 50, rot: 7, delai: 0.34, scale: 0.85 },
    { left: 58, top: 52, rot: -6, delai: 0.44, scale: 0.9 },
  ];

  function nitratesVersReward(conteneur, opts) {
    if (!conteneur) return;
    const nombre = Math.max(1, Math.min((opts && opts.nombre) || 5, PLACEMENTS.length));
    conteneur.classList.add("nitrates-vers");
    conteneur.setAttribute("aria-hidden", "true");
    conteneur.innerHTML = "";
    for (let i = 0; i < nombre; i++) {
      const p = PLACEMENTS[i];
      const el = document.createElement("div");
      el.className = "nitrates-ver";
      el.style.left = p.left + "%";
      el.style.top = p.top + "%";
      el.style.setProperty("--rot", p.rot + "deg");
      el.style.setProperty("--delai", p.delai + "s");
      // taille via scale appliqué au wrapper (garde le float sur transform)
      el.style.width = 64 * p.scale + "px";
      el.style.height = 64 * p.scale + "px";
      el.innerHTML = svgVer(i);
      conteneur.appendChild(el);
    }
  }

  if (typeof window !== "undefined") {
    window.nitratesVersReward = nitratesVersReward;
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { nitratesVersReward, svgVer, PLACEMENTS };
  }
})();
