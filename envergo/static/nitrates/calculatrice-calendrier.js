/**
 * Composant calendrier dynamique pour les feuilles type=calculatrice
 * avec composant=calendrier_dynamique_couvert.
 *
 * Cf. spec_rendu_simulateur_calculatrice.md.
 *
 * Pas de htmx ni de round-trip serveur : le composant lit le JSON
 * exposé via <script type="application/json" id="nitrates-calculatrice-data">,
 * rend le mini-formulaire avec les placeholder, et recalcule tout
 * localement à chaque change d'input.
 */
(function () {
  "use strict";

  const dataEl = document.getElementById("nitrates-calculatrice-data");
  const root = document.querySelector("[data-calc-cal-root]");
  if (!dataEl || !root) return;

  let data;
  try {
    data = JSON.parse(dataEl.textContent);
  } catch (e) {
    console.error("calculatrice-calendrier: JSON parse failed", e);
    return;
  }
  if (!data || data.type !== "calculatrice") return;

  const mount = root.querySelector("[data-calc-cal-mount]");
  if (!mount) return;

  // ─── Constantes ────────────────────────────────────────────────────────
  // Année agricole = juillet → juin. Index 0 = juillet, 11 = juin.
  const MOIS_AGRICOLES = [
    "Juil", "Aoû", "Sept", "Oct", "Nov", "Déc",
    "Jan", "Fév", "Mar", "Avr", "Mai", "Jui",
  ];
  const JOURS_PAR_MOIS_AGRICOLE = [31, 31, 30, 31, 30, 31, 31, 28, 31, 30, 31, 30];
  const TOTAL_JOURS = 365;

  const REGIME_COULEUR = {
    interdiction: "interdit",
    autorisation_sous_condition: "conditionnel",
    plafonnement: "conditionnel",
    libre: "autorise",
    non_applicable: "neutre",
  };

  // Verbes humains pour le récap et les annotations.
  const REGIME_VERBE = {
    interdiction: "interdit",
    autorisation_sous_condition: "autorisé sous condition",
    plafonnement: "soumis à plafonnement",
    libre: "autorisé",
    non_applicable: "ne s'applique pas",
  };

  const UNITES_JOURS = { jours: 1, semaines: 7, mois: 30 };

  // ─── Helpers ───────────────────────────────────────────────────────────

  // Convertit "JJ/MM" en index de jour de l'année agricole (0 = 1er juillet).
  function jjmmToJourAgricole(jjmm) {
    const m = /^(\d{2})\/(\d{2})$/.exec(jjmm);
    if (!m) return null;
    const jour = parseInt(m[1], 10);
    const mois = parseInt(m[2], 10);
    if (mois < 1 || mois > 12 || jour < 1 || jour > 31) return null;
    // Mois 7=juillet → index 0, mois 8 → 1, ..., 12 → 5, 1 → 6, ..., 6 → 11.
    const moisAgr = (mois - 7 + 12) % 12;
    let total = 0;
    for (let i = 0; i < moisAgr; i++) total += JOURS_PAR_MOIS_AGRICOLE[i];
    return total + (jour - 1);
  }

  // Convertit un index de jour agricole en "JJ mois" lisible.
  function jourAgricoleToLisible(j) {
    if (j < 0 || j >= TOTAL_JOURS) return "";
    let idx = j;
    for (let i = 0; i < 12; i++) {
      if (idx < JOURS_PAR_MOIS_AGRICOLE[i]) {
        return `${idx + 1} ${MOIS_AGRICOLES[i].toLowerCase()}.`;
      }
      idx -= JOURS_PAR_MOIS_AGRICOLE[i];
    }
    return "";
  }

  // Convertit un index de jour agricole en "JJ/MM" (mois civil).
  function jourAgricoleToJJMM(j) {
    if (j < 0 || j >= TOTAL_JOURS) return null;
    let idx = j;
    for (let i = 0; i < 12; i++) {
      if (idx < JOURS_PAR_MOIS_AGRICOLE[i]) {
        const moisCivil = ((i + 7 - 1) % 12) + 1;
        const jour = idx + 1;
        return `${String(jour).padStart(2, "0")}/${String(moisCivil).padStart(2, "0")}`;
      }
      idx -= JOURS_PAR_MOIS_AGRICOLE[i];
    }
    return null;
  }

  // Aujourd'hui en index agricole (en fonction de new Date()).
  function aujourdhuiAgricole() {
    const now = new Date();
    const jjmm = `${String(now.getDate()).padStart(2, "0")}/${String(now.getMonth() + 1).padStart(2, "0")}`;
    return jjmmToJourAgricole(jjmm);
  }

  // Heuristique label_court : prendre les mots après "de" dans le label,
  // sinon les 2 premiers mots du label.
  function deduireLabelCourt(input) {
    if (input.label_court) return input.label_court;
    if (!input.label) return input.id || "";
    const tokens = input.label.split(/\s+/);
    const idxDe = tokens.findIndex((t) => /^d[e']/i.test(t));
    if (idxDe >= 0 && tokens.length > idxDe + 1) {
      return tokens.slice(idxDe + 1, idxDe + 3).join(" ").toLowerCase();
    }
    return tokens.slice(0, 2).join(" ").toLowerCase();
  }

  // Parse une borne YAML (JJ/MM | event | event±Nunit) en index agricole.
  // Retourne {jour: int|null, isEvent: bool, eventId: str|null, offsetJours: int}
  const BORNE_RE = /^([a-z][a-z0-9_]*)(?:([+-])(\d+)(jours|semaines|mois))?$/;
  function parseBorne(val, valeursInputs) {
    if (!val) return { jour: null, isEvent: false };
    if (/^\d{2}\/\d{2}$/.test(val)) {
      return { jour: jjmmToJourAgricole(val), isEvent: false };
    }
    const m = BORNE_RE.exec(val);
    if (!m) return { jour: null, isEvent: false };
    const eventId = m[1];
    const valEvent = valeursInputs[eventId];
    if (!valEvent) return { jour: null, isEvent: true, eventId };
    let jour = jjmmToJourAgricole(valEvent);
    if (jour === null) return { jour: null, isEvent: true, eventId };
    if (m[2]) {
      const sign = m[2] === "+" ? 1 : -1;
      const n = parseInt(m[3], 10);
      const unit = m[4];
      jour = (jour + sign * n * UNITES_JOURS[unit] + TOTAL_JOURS) % TOTAL_JOURS;
    }
    return {
      jour,
      isEvent: true,
      eventId,
      offsetSign: m[2] || null,
      offsetN: m[3] ? parseInt(m[3], 10) : null,
      offsetUnit: m[4] || null,
    };
  }

  // Construit le tableau régime-par-jour (override : dernière période gagne).
  function computeRegimePerDay(periodes, valeurs) {
    const result = new Array(TOTAL_JOURS).fill("libre");
    for (const p of periodes || []) {
      const du = parseBorne(p.du, valeurs).jour;
      const au = parseBorne(p.au, valeurs).jour;
      const regime = p.regime || data.type || "interdiction";
      if (du === null || au === null) continue;
      // Gère le wrap (du > au : traverse le 30/06 → 1/07).
      if (du <= au) {
        for (let i = du; i <= au; i++) result[i] = regime;
      } else {
        for (let i = du; i < TOTAL_JOURS; i++) result[i] = regime;
        for (let i = 0; i <= au; i++) result[i] = regime;
      }
    }
    return result;
  }

  // ─── État ──────────────────────────────────────────────────────────────
  const inputs = (data.inputs_requis || []).filter(
    (inp) => inp && typeof inp === "object" && inp.id
  );
  if (inputs.length === 0) {
    mount.innerHTML =
      '<p class="calc-cal__error">Aucun input requis défini pour cette règle calculatrice.</p>';
    return;
  }

  const valeurs = {};
  for (const inp of inputs) {
    valeurs[inp.id] = inp.placeholder || "";
  }

  // ─── Rendu ─────────────────────────────────────────────────────────────

  function renderMiniForm() {
    return `
      <div class="calc-cal__form">
        ${inputs
          .map(
            (inp) => `
          <label class="calc-cal__field">
            <span class="calc-cal__field-label">${escapeHtml(inp.label || inp.id)}</span>
            <input type="text"
                   data-input-id="${escapeHtml(inp.id)}"
                   value="${escapeHtml(valeurs[inp.id])}"
                   placeholder="JJ/MM"
                   pattern="^\\d{2}/\\d{2}$"
                   maxlength="5">
          </label>
        `
          )
          .join("")}
      </div>
    `;
  }

  function renderBarre(regimeParJour) {
    // Segments contigus de même régime.
    const segments = [];
    let cur = { regime: regimeParJour[0], du: 0, au: 0 };
    for (let i = 1; i < TOTAL_JOURS; i++) {
      if (regimeParJour[i] === cur.regime) {
        cur.au = i;
      } else {
        segments.push(cur);
        cur = { regime: regimeParJour[i], du: i, au: i };
      }
    }
    segments.push(cur);

    const segmentsHtml = segments
      .map((s) => {
        const couleur = REGIME_COULEUR[s.regime] || "neutre";
        const w = ((s.au - s.du + 1) / TOTAL_JOURS) * 100;
        const left = (s.du / TOTAL_JOURS) * 100;
        return `<div class="calc-cal__segment calc-cal__segment--${couleur}"
                     style="left:${left.toFixed(3)}%; width:${w.toFixed(3)}%"
                     title="${escapeHtml(REGIME_VERBE[s.regime] || s.regime)}"></div>`;
      })
      .join("");

    // Marqueurs : aujourd'hui + dates inputs.
    const aujourdhui = aujourdhuiAgricole();
    const aujLeft = aujourdhui != null ? (aujourdhui / TOTAL_JOURS) * 100 : null;
    const markersHtml = inputs
      .map((inp) => {
        const j = jjmmToJourAgricole(valeurs[inp.id]);
        if (j === null) return "";
        const left = (j / TOTAL_JOURS) * 100;
        const labelCourt = deduireLabelCourt(inp);
        return `
          <div class="calc-cal__marker calc-cal__marker--input"
               style="left:${left.toFixed(3)}%"
               title="${escapeHtml(inp.label)} : ${escapeHtml(valeurs[inp.id])}">
            <span class="calc-cal__marker-line"></span>
            <span class="calc-cal__marker-label">${escapeHtml(labelCourt)}<br>${escapeHtml(valeurs[inp.id])}</span>
          </div>
        `;
      })
      .join("");
    const aujourdhuiHtml =
      aujLeft != null
        ? `<div class="calc-cal__marker calc-cal__marker--today" style="left:${aujLeft.toFixed(3)}%" title="Aujourd'hui"><span class="calc-cal__marker-dot"></span><span class="calc-cal__marker-label">aujourd'hui</span></div>`
        : "";

    return `
      <div class="calc-cal__barre">
        <div class="calc-cal__barre-track">
          ${segmentsHtml}
          ${markersHtml}
          ${aujourdhuiHtml}
        </div>
        <div class="calc-cal__mois">
          ${MOIS_AGRICOLES.map((m) => `<span>${m}</span>`).join("")}
        </div>
      </div>
    `;
  }

  function renderLegende() {
    return `
      <div class="calc-cal__legende">
        <span class="calc-cal__legende-item"><span class="calc-cal__legende-patch calc-cal__legende-patch--interdit"></span> Interdit</span>
        <span class="calc-cal__legende-item"><span class="calc-cal__legende-patch calc-cal__legende-patch--conditionnel"></span> Autorisé sous conditions</span>
        <span class="calc-cal__legende-item"><span class="calc-cal__legende-patch calc-cal__legende-patch--autorise"></span> Autorisé</span>
      </div>
    `;
  }

  function renderRecap(periodes) {
    // Pour chaque période : phrase courte expliquant la fenêtre concrète.
    const inputById = Object.fromEntries(inputs.map((i) => [i.id, i]));
    const lignes = [];
    for (const p of periodes || []) {
      const regime = p.regime || "interdiction";
      const verbe = REGIME_VERBE[regime] || regime;
      const partDu = parseBorne(p.du, valeurs);
      const partAu = parseBorne(p.au, valeurs);

      // Texte annotation : pour les bornes event+offset, on génère
      // « à partir de N unités après labelCourt ».
      const annoter = (part, mode) => {
        if (!part.isEvent || !part.eventId || !part.offsetN) return null;
        const inp = inputById[part.eventId];
        const lc = inp ? deduireLabelCourt(inp) : part.eventId;
        const prep = part.offsetSign === "+" ? "après" : "avant";
        const direction =
          mode === "du"
            ? part.offsetSign === "+"
              ? "à partir de"
              : "jusqu'à"
            : part.offsetSign === "+"
              ? "jusqu'à"
              : "à partir de";
        return `${direction} ${part.offsetN} ${part.offsetUnit} ${prep} ${lc}`;
      };

      const duStr = partDu.jour != null ? jourAgricoleToLisible(partDu.jour) : "?";
      const auStr = partAu.jour != null ? jourAgricoleToLisible(partAu.jour) : "?";
      const annDu = annoter(partDu, "du");
      const annAu = annoter(partAu, "au");

      let ligne = `<strong>${capitalize(verbe)}</strong> du ${duStr} au ${auStr}`;
      const annotations = [annDu, annAu].filter(Boolean);
      if (annotations.length > 0) {
        ligne += ` <span class="calc-cal__recap-annot">(${annotations.join(", ")})</span>`;
      }
      lignes.push(`<li>${ligne}</li>`);
    }
    if (lignes.length === 0) return "";
    return `
      <div class="calc-cal__recap">
        <h4>Récapitulatif</h4>
        <ul>${lignes.join("")}</ul>
      </div>
    `;
  }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function capitalize(s) {
    return s && s[0].toUpperCase() + s.slice(1);
  }

  // ─── Render principal ──────────────────────────────────────────────────

  function render() {
    const regimeParJour = computeRegimePerDay(data.periodes, valeurs);
    mount.innerHTML = `
      ${renderMiniForm()}
      ${renderBarre(regimeParJour)}
      ${renderLegende()}
      ${renderRecap(data.periodes)}
    `;
    bindInputs();
  }

  function bindInputs() {
    mount.querySelectorAll("input[data-input-id]").forEach((el) => {
      el.addEventListener("change", () => {
        const id = el.dataset.inputId;
        const val = el.value.trim();
        // Validation minimale : si pas JJ/MM, on garde l'ancienne valeur.
        if (val && !/^\d{2}\/\d{2}$/.test(val)) {
          el.value = valeurs[id];
          return;
        }
        if (val) valeurs[id] = val;
        render();
      });
    });
  }

  render();
})();
