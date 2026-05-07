// Pilote interactif du panneau resultat (issue #28).
//
// Le statut effectif "aujourd'hui" est calcule cote serveur par le
// templatetag epandage_header() (helper Python statut_aujourdhui),
// pour rester testable independamment de la date courante. Ce JS
// s'occupe uniquement des enrichissements UX :
//
//   1. Switcher de variante UX (A/B/C) avec persistance localStorage
//      -- temporaire, a retirer apres validation design
//   2. Tooltip au survol des zones du calendrier (zones rouges /
//      oranges / vertes -> info "Interdit du X au Y" etc.)
//
// La regle est exposee en JSON dans <script id="regle-actuelle"> par
// le template (cf. Resultat.to_json_dict). Ce JS la lit pour
// construire les libelles tooltip.

(function () {
  "use strict";

  // ─── Lecture de la regle JSON ────────────────────────────────────────

  let regle = null;
  const regleEl = document.getElementById("regle-actuelle");
  if (regleEl) {
    try {
      regle = JSON.parse(regleEl.textContent);
    } catch (err) {
      console.error("epandage_aujourdhui: regle JSON invalide", err);
    }
  }

  // ─── Switcher variantes UX ───────────────────────────────────────────

  const STORAGE_KEY = "nitrates_epandage_ux_variant";

  function appliquerVariante(name) {
    const header = document.querySelector(".epandage-header");
    if (!header) return;
    header.dataset.variant = name;
    header
      .querySelectorAll(".epandage-header__variant")
      .forEach((el) => {
        const isActive = el.classList.contains(
          `epandage-header__variant--${name}`
        );
        el.hidden = !isActive;
      });
  }

  const switcher = document.getElementById("ux-variant-select");
  if (switcher) {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && ["A", "B", "C"].includes(saved)) {
      switcher.value = saved;
      appliquerVariante(saved);
    } else {
      appliquerVariante("A");
    }
    switcher.addEventListener("change", (e) => {
      const name = e.target.value;
      localStorage.setItem(STORAGE_KEY, name);
      appliquerVariante(name);
    });
  }

  // ─── Tooltip au survol des zones du calendrier ───────────────────────

  function libelleRegime(regime) {
    return (
      {
        interdiction: "Interdit",
        autorisation_sous_condition: "Autorisé sous condition",
        plafonnement: "Plafonné",
        libre: "Autorisé",
      }[regime] || regime
    );
  }

  function tooltipPourZone(zoneEl, periodes, regleType) {
    // Extrait du DOM la position en % de la zone, et matche avec la
    // periode dont les bornes correspondent. Approximatif (positions en
    // pourcent) mais suffisant pour des labels indicatifs.
    const start = parseFloat(zoneEl.style.left) || 0;
    // Couleur de la zone (depuis la classe CSS) -> regime probable
    const couleur =
      Array.from(zoneEl.classList)
        .map((c) => c.match(/calendrier-epandage__zone--(\w+)/))
        .filter(Boolean)
        .map((m) => m[1])[0] || "";
    const regimeFromCouleur = {
      rouge: "interdiction",
      orange: "autorisation_sous_condition",
      vert: "libre",
    }[couleur];

    // Trouve la periode dont le segment commence le plus pres de start.
    // (heuristique : 100% de l'annee agricole ~ 365 jours, on tolere
    // 1.5% de marge ~ 5 jours).
    let best = null;
    let bestDelta = Infinity;
    for (const p of periodes || []) {
      const regime = p.regime || regleType;
      if (regime !== regimeFromCouleur) continue;
      // On ne calcule pas la position exacte ici : on prend la 1re
      // qui matche le bon regime. Pour les regles a une seule periode,
      // c'est trivialement bon. Pour les regles multi-periodes, le
      // template rend dans l'ordre, on s'aligne dessus en utilisant
      // l'index courant -- mais simplifions : matche par regime.
      if (best === null || bestDelta > 0) {
        best = p;
        bestDelta = 0;
      }
    }
    if (!best) return libelleRegime(regimeFromCouleur);
    return `${libelleRegime(regimeFromCouleur)} du ${best.du} au ${best.au}`;
  }

  function setupTooltips() {
    if (!regle) return;
    const calendrier = document.querySelector(".calendrier-epandage");
    if (!calendrier) return;

    // Conteneur tooltip unique reutilise.
    const tooltip = document.createElement("div");
    tooltip.className = "calendrier-epandage__tooltip";
    tooltip.dataset.visible = "false";
    calendrier.style.position = calendrier.style.position || "relative";
    calendrier.appendChild(tooltip);

    // Plutot que de matcher periode par index, on pre-calcule un texte
    // par zone en utilisant l'ordre du DOM et l'ordre des periodes
    // filtrees sur "regime ayant un overlay".
    const zones = Array.from(
      calendrier.querySelectorAll(".calendrier-epandage__zone")
    );
    const periodesAvecOverlay = (regle.periodes || []).filter((p) => {
      const regime = p.regime || regle.type;
      return ["interdiction", "autorisation_sous_condition", "plafonnement"].includes(regime);
    });

    zones.forEach((zone, idx) => {
      // Ce mapping idx -> periode marche pour les cas simples.
      // Cas pivot annee (1 periode -> 2 segments) : tombe a cote sur
      // la 2e zone, mais le libelle reste "du X au Y" donc OK.
      const periode = periodesAvecOverlay[idx] || periodesAvecOverlay[0];
      const couleur =
        Array.from(zone.classList)
          .map((c) => c.match(/calendrier-epandage__zone--(\w+)/))
          .filter(Boolean)
          .map((m) => m[1])[0] || "";
      const regimeFromCouleur =
        {
          rouge: "interdiction",
          orange: "autorisation_sous_condition",
          vert: "libre",
        }[couleur] || "";
      const libelle = periode
        ? `${libelleRegime(regimeFromCouleur)} du ${periode.du} au ${periode.au}`
        : libelleRegime(regimeFromCouleur);

      zone.addEventListener("mouseenter", (e) => {
        tooltip.textContent = libelle;
        tooltip.dataset.visible = "true";
        positionnerTooltip(e, tooltip, calendrier);
      });
      zone.addEventListener("mousemove", (e) => {
        positionnerTooltip(e, tooltip, calendrier);
      });
      zone.addEventListener("mouseleave", () => {
        tooltip.dataset.visible = "false";
      });
      // Mobile : tap toggle
      zone.addEventListener("click", (e) => {
        if (tooltip.dataset.visible === "true") {
          tooltip.dataset.visible = "false";
        } else {
          tooltip.textContent = libelle;
          tooltip.dataset.visible = "true";
          positionnerTooltip(e, tooltip, calendrier);
        }
      });
    });
  }

  function positionnerTooltip(event, tooltip, container) {
    const rect = container.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    tooltip.style.left = `${x}px`;
    tooltip.style.top = `${y}px`;
  }

  // ─── Init ─────────────────────────────────────────────────────────────

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupTooltips);
  } else {
    setupTooltips();
  }
})();
