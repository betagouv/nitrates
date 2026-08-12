/* #284 — Génère l'animation "reward" : N petits lombrics contents qui
 * flottent et sourient dans un conteneur. Sobre mais mignon, couleur ver de
 * terre (lombric), pas façon caca (formes rondes lisses, sourire net, yeux).
 *
 * API : window.nitratesVersReward(conteneur, {nombre}) monte l'animation.
 * Exposé aussi comme module Node pour tests éventuels.
 */
(function () {
  "use strict";

  // Palette lombric : rosé-brun terreux. Dégradé pour donner du volume (plus
  // joli qu'un aplat), liseré foncé, clitellum clair (l'anneau du lombric).
  const CORPS = "#cf847a"; // rosé-brun principal
  const CORPS_FONCE = "#b56458"; // bas du dégradé (ombre)
  const CORPS_CLAIR = "#e6a89e"; // haut du dégradé (lumière)
  const CONTOUR = "#95504a"; // liseré
  const CLITELLUM = "#eec4ba"; // anneau clair

  // SVG d'un lombric souriant, dodu et arrondi. viewBox 0 0 64 64.
  // Un dégradé vertical par ver (id unique via `index`) donne le volume.
  function svgVer(index) {
    const flip =
      index % 2 === 1 ? ' transform="scale(-1,1) translate(-64,0)"' : "";
    const gid = "nver-grad-" + index;
    const corpsPath =
      "M16 48 C 10 32, 20 15, 33 16 C 47 17, 52 31, 47 41";
    return `
<svg viewBox="0 0 64 64" width="64" height="64" role="img" aria-hidden="true"
     xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${CORPS_CLAIR}"/>
      <stop offset="0.5" stop-color="${CORPS}"/>
      <stop offset="1" stop-color="${CORPS_FONCE}"/>
    </linearGradient>
  </defs>
  <g${flip}>
    <!-- liseré + corps dodu avec dégradé -->
    <path d="${corpsPath}" fill="none" stroke="${CONTOUR}" stroke-width="18"
          stroke-linecap="round"/>
    <path d="${corpsPath}" fill="none" stroke="url(#${gid})" stroke-width="15"
          stroke-linecap="round"/>
    <!-- reflet doux le long du dos -->
    <path d="${corpsPath}" fill="none" stroke="#fff" stroke-width="3.5"
          stroke-linecap="round" opacity="0.22"
          transform="translate(-2,-2)"/>
    <!-- clitellum : anneau clair vers le milieu -->
    <ellipse cx="33" cy="16.5" rx="6.5" ry="8" fill="${CLITELLUM}"
             opacity="0.85"/>
    <!-- tête (extrémité) bien ronde -->
    <circle cx="47" cy="41" r="9" fill="url(#${gid})" stroke="${CONTOUR}"
            stroke-width="1.5"/>
    <!-- yeux (grands, expressifs) -->
    <circle cx="44.5" cy="39" r="2" fill="#fff"/>
    <circle cx="50" cy="39" r="2" fill="#fff"/>
    <circle cx="44.9" cy="39.3" r="1.15" fill="#33221f"/>
    <circle cx="50.4" cy="39.3" r="1.15" fill="#33221f"/>
    <circle cx="45.3" cy="38.8" r="0.4" fill="#fff"/>
    <circle cx="50.8" cy="38.8" r="0.4" fill="#fff"/>
    <!-- sourire arrondi -->
    <path d="M43.6 43 Q47.3 47, 51 43" fill="none" stroke="#33221f"
          stroke-width="1.7" stroke-linecap="round"/>
    <!-- joues roses -->
    <circle cx="42.8" cy="42.6" r="1.5" fill="#ff9a8a" opacity="0.55"/>
    <circle cx="51.7" cy="42.6" r="1.5" fill="#ff9a8a" opacity="0.55"/>
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
