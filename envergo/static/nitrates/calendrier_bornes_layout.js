/* #255 — anti-collision des labels de dates du calendrier STATIQUE.
 *
 * Le calendrier statique (templatetag calendrier_epandage / _calendrier.html)
 * empilait les dates de facon binaire cote Python (date fixe = row0, pheno =
 * row1). Deux dates fixes proches restaient donc sur la meme ligne et se
 * chevauchaient (cf. ticket #255, colza type_III).
 *
 * On reprend la MEME logique que le calendrier dynamique
 * (calculatrice-calendrier.js `layoutBornesRows`) : placement greedy
 * gauche->droite par MESURE REELLE du DOM (les largeurs de texte ne sont
 * connues qu'apres rendu, donc impossible a calculer cote Python). Chaque
 * label est pose sur la 1ere row ou il ne chevauche aucun label deja place
 * (avec un petit jeu horizontal). Le trait ::before s'allonge via la classe
 * --rowN, et la hauteur du conteneur .period s'ajuste a la row max utilisee.
 */
(function () {
  "use strict";

  const ROW_STEP_PX = 18; // pas vertical des classes --rowN (doit matcher le CSS)
  const ROW_GAP_PX = 6; // jeu horizontal mini entre 2 labels d'une meme row

  function layoutOne(container) {
    const labels = [
      ...container.querySelectorAll(".calendrier-epandage__period-date"),
    ];
    if (labels.length === 0) return;

    // Reset : tout en row0, on retire les classes --rowN posees (Python ou
    // passe precedente) pour re-mesurer sur une base propre.
    labels.forEach((el) => {
      el.classList.remove(
        "calendrier-epandage__period-date--row2",
        "calendrier-epandage__period-date--row3",
        "calendrier-epandage__period-date--row4",
      );
    });

    // Mesure apres reset, tri par bord gauche.
    const measured = labels
      .map((el) => {
        const r = el.getBoundingClientRect();
        return { el, left: r.left, right: r.right };
      })
      .sort((a, b) => a.left - b.left);

    // Greedy : 1ere row libre (0 = au plus pres de la barre) ou l'intervalle
    // [left,right] ne touche pas le dernier label pose sur cette row.
    const rowsLastRight = [];
    let maxRow = 0;
    for (const m of measured) {
      let row = 0;
      while (
        rowsLastRight[row] !== undefined &&
        m.left < rowsLastRight[row] + ROW_GAP_PX
      ) {
        row += 1;
      }
      rowsLastRight[row] = m.right;
      if (row > maxRow) maxRow = row;
      // row0 = pas de classe ; row>=1 -> --row{row+1} (row2/row3/row4).
      if (row >= 1) {
        m.el.classList.add(
          `calendrier-epandage__period-date--row${row + 1}`,
        );
      }
    }

    // Hauteur du conteneur ajustee a la row la plus profonde utilisee.
    container.style.height = `${20 + maxRow * ROW_STEP_PX + 8}px`;
  }

  function layoutAll() {
    // Uniquement les calendriers STATIQUES : ceux geres par le JS dynamique
    // (calc-cal) ont deja leur propre anti-collision.
    document
      .querySelectorAll(
        ".calendrier-epandage:not(.calc-cal) .calendrier-epandage__period",
      )
      .forEach(layoutOne);
  }

  function schedule() {
    // rAF pour mesurer apres que le layout CSS est applique.
    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(layoutAll);
    } else {
      layoutAll();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", schedule);
  } else {
    schedule();
  }

  // Recalage au resize (les largeurs de labels changent avec la largeur de la
  // barre), debounce leger.
  let t = null;
  window.addEventListener("resize", function () {
    if (t) clearTimeout(t);
    t = setTimeout(schedule, 120);
  });

  // Le calendrier statique est souvent (re)injecte par htmx apres relance de la
  // simulation : on relaye les evenements htmx pour re-layouter.
  document.body.addEventListener("htmx:afterSwap", schedule);
  document.body.addEventListener("htmx:afterSettle", schedule);

  // Expose pour un appel manuel eventuel.
  window.nitratesLayoutBornesStatique = layoutAll;
})();
