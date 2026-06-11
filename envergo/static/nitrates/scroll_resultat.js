// Auto-scroll apres une soumission du simulateur (#112).
//
// Le parcours est un GET full-reload : apres "Lancer la simulation", le
// navigateur repositionne la page tout en haut (sur le hero), alors que la
// suite logique est plus bas. On recadre donc la vue :
//
//   - QC en attente  -> on amene le bloc "Questions complementaires" en HAUT
//     de l'ecran (block:start), pleine page, pour qu'il soit evident qu'il
//     reste quelque chose a remplir.
//   - resultat final -> on amene la section "Localisation + resultat"
//     (.results-row) en haut de l'ecran, pas le hero.
//
// Robustesse : la carte Leaflet et les images se chargent APRES le DOM et
// decalent les positions. Un scroll declenche trop tot atterrit a cote. On
// attend donc window.load, puis on attend que la hauteur de page se stabilise
// (plus de reflow) avant de scroller, avec un filet de re-scroll.

(function () {
  "use strict";

  // Cible + mode d'alignement vertical :
  //   - QC en attente  -> block:"end" : le bloc QC se cale en BAS du viewport,
  //     en laissant la fin du formulaire (Fertilisant, reponses precedentes)
  //     visible AU-DESSUS. L'utilisateur voit ainsi que la QC est la suite
  //     naturelle de ce qu'il remplissait (pas une page hors contexte).
  //   - resultat final -> block:"start" : la section Localisation/resultat se
  //     cale en HAUT du viewport (on saute le hero).
  function cible() {
    const qc = document.querySelector("#qc-bloc[data-qc-en-attente='true']");
    if (qc) return { el: qc, block: "end" };
    const row = document.querySelector(".results-row.layout--split");
    if (row) return { el: row, block: "start" };
    // Resultat sans split (mobile) : la colonne resultat ou la row simple.
    const fallback =
      document.querySelector(".result-col") ||
      document.querySelector(".results-row");
    return fallback ? { el: fallback, block: "start" } : null;
  }

  const target = cible();
  if (!target) return;

  const reduceMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)"
  ).matches;

  // Marge (px) laissee entre le bloc et le bord du viewport, pour ne pas
  // coller pile au bord (sensation de contenu coupe).
  const PADDING = 24;

  function scrollVers(comportement) {
    // block:"end" -> on cale le BAS du bloc PADDING px au-dessus du bas du
    // viewport (scrollIntoView ne gere pas d'offset, on calcule la position).
    if (target.block === "end") {
      const rect = target.el.getBoundingClientRect();
      const y = window.scrollY + rect.bottom - window.innerHeight + PADDING;
      window.scrollTo({ top: Math.max(0, y), behavior: comportement });
      return;
    }
    // block:"start" -> bloc en haut, avec un peu d'air au-dessus.
    const rect = target.el.getBoundingClientRect();
    const y = window.scrollY + rect.top - PADDING;
    window.scrollTo({ top: Math.max(0, y), behavior: comportement });
  }

  // Attend que document.body.scrollHeight reste stable sur 2 frames
  // consecutives (= layout pose, carte/images integrees) avant de scroller.
  // Garde-fou : on n'attend jamais plus de ~1.2s.
  function scrollQuandStable() {
    let lastHeight = -1;
    let stableFrames = 0;
    let elapsed = 0;
    const STEP = 80; // ms entre 2 mesures
    const MAX = 1200; // ms max d'attente

    function tick() {
      const h = document.body.scrollHeight;
      if (h === lastHeight) {
        stableFrames += 1;
      } else {
        stableFrames = 0;
        lastHeight = h;
      }
      elapsed += STEP;
      if (stableFrames >= 2 || elapsed >= MAX) {
        // Position finale, animee.
        scrollVers(reduceMotion ? "auto" : "smooth");
        return;
      }
      setTimeout(tick, STEP);
    }
    tick();
  }

  // On part de window.load (images + carte demandees). Si la page est deja
  // chargee, on enchaine directement.
  if (document.readyState === "complete") {
    scrollQuandStable();
  } else {
    window.addEventListener("load", scrollQuandStable, { once: true });
  }
})();
