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
  //   - QC en attente  -> on cale le BLOC "Questions complementaires" (avec son
  //     titre) en HAUT du viewport (block:"start"). Avant on calait le BAS du
  //     bloc (block:"end"), mais quand il etait plus haut que l'ecran la 1re
  //     question passait au-dessus du viewport -> invisible (retour Max #154).
  //   - resultat final -> block:"start" : la table Localisation/reglementation
  //     en haut du viewport (on saute le hero).
  // Sous le breakpoint lg du DSFR (992px), les deux colonnes de .layout--split
  // s'empilent : le resultat passe SOUS le formulaire + la carte. Scroller vers
  // le HAUT de la .results-row ramenait alors sur le formulaire, pas sur le
  // resultat -> l'auto-scroll semblait "ne pas marcher" en mobile (#177). On
  // vise donc directement la colonne resultat quand les colonnes sont empilees.
  const LG_BREAKPOINT = 992;

  function cible() {
    // QC en attente : on cale le BLOC "Questions complementaires" (avec son
    // titre) en haut du viewport -> l'utilisateur voit le titre + la 1re
    // question. (Cibler la question interne masquait le titre du bloc.)
    const qc = document.querySelector("#qc-bloc[data-qc-en-attente='true']");
    if (qc) return { el: qc, block: "start" };

    const empile = window.innerWidth < LG_BREAKPOINT;
    const resultCol = document.querySelector(".result-col");

    // Colonnes empilees (mobile/tablette, #177) : on cale la colonne resultat
    // en haut (sinon scroller le haut de la row ramene sur le formulaire).
    if (empile && resultCol) return { el: resultCol, block: "start" };

    // Desktop en 2 colonnes : le haut de la row (form + resultat alignes).
    const row = document.querySelector(".results-row.layout--split");
    if (row) return { el: row, block: "start" };

    // Filets : colonne resultat, sinon row simple.
    const fallback = resultCol || document.querySelector(".results-row");
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

  // Hauteur des barres fixes en haut (bandeau "En construction" quand il est
  // affiche + barre de progression) : sans cet offset, block:"start" cale le
  // bloc pile sous ces barres qui le recouvrent -> scroll "imprecis". On mesure
  // la hauteur reelle du bandeau construction s'il est visible.
  function offsetHautFixe() {
    let h = 0;
    const bandeau = document.querySelector(".nitrates-construction__bar");
    if (bandeau) {
      const r = bandeau.getBoundingClientRect();
      // visible = a l'ecran et non transparent (opacity geree en CSS au scroll)
      const style = window.getComputedStyle(bandeau);
      if (r.height > 0 && parseFloat(style.opacity) > 0.1) h = r.height;
    }
    return h;
  }

  function scrollVers(comportement) {
    // block:"end" -> on cale le BAS du bloc PADDING px au-dessus du bas du
    // viewport (scrollIntoView ne gere pas d'offset, on calcule la position).
    if (target.block === "end") {
      const rect = target.el.getBoundingClientRect();
      const y = window.scrollY + rect.bottom - window.innerHeight + PADDING;
      window.scrollTo({ top: Math.max(0, y), behavior: comportement });
      return;
    }
    // block:"start" -> haut du bloc juste sous les barres fixes, avec un peu
    // d'air. On soustrait l'offset des barres fixes pour un cadrage precis.
    const rect = target.el.getBoundingClientRect();
    const y = window.scrollY + rect.top - PADDING - offsetHautFixe();
    window.scrollTo({ top: Math.max(0, y), behavior: comportement });
  }

  // Attend que document.body.scrollHeight reste stable sur 2 frames
  // consecutives (= layout pose, carte/images integrees) avant de scroller.
  // Garde-fou : on n'attend jamais plus de ~1.2s.
  //
  // PROBLEME OBSERVE (Carte #154) : meme apres "stabilite", la carte Leaflet /
  // les images continuent de decaler la position de la cible APRES le scroll ->
  // on atterrissait a cote (cible hors viewport). Correctif : apres le scroll
  // initial, on programme des RE-SCROLLS correctifs a 150/500/1000 ms, et un
  // dernier sur window.load, pour rattraper tout reflow tardif. scrollVers est
  // idempotent (recalcule la position a chaque appel).
  function scrollQuandStable() {
    let lastHeight = -1;
    let stableFrames = 0;
    let elapsed = 0;
    const STEP = 80; // ms entre 2 mesures
    const MAX = 1200; // ms max d'attente

    function corriger() {
      scrollVers("auto");
    }

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
        // Re-scrolls correctifs pour rattraper les reflows tardifs (tuiles
        // carte, images). Sans animation pour ne pas "sauter" visuellement.
        setTimeout(corriger, 150);
        setTimeout(corriger, 500);
        setTimeout(corriger, 1000);
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
