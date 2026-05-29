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

  // Mapping regime YAML -> couleur attendue par calendrier.css. On reuse
  // exactement la palette du templatetag standard `calendrier_epandage` :
  //   interdiction -> rouge
  //   autorisation_sous_condition / plafonnement -> orange
  //   libre / par defaut -> pas d'overlay (fond vert visible)
  //   non_applicable -> pas d'overlay (fond gris quand activable plus tard)
  const REGIME_COULEUR_ZONE = {
    interdiction: "rouge",
    autorisation_sous_condition: "orange",
    plafonnement: "orange",
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

  // Evalue `condition` (mini-DSL "<input_id> <op> <JJ/MM>") sur les
  // valeurs courantes du form. La comparaison utilise l'ordre de
  // l'annee agricole (juillet=0 ... juin~365). Cf.
  // spec_extension_grammaire_condition.
  //
  // Retourne true si la condition est vraie ou absente, false sinon.
  // Si la valeur user pour input_id est manquante / non-parseable, on
  // retourne true (mode "permissif") -- la periode reste affichee, sans
  // distorsion, jusqu'a ce que l'utilisateur saisisse une valeur valide.
  const CONDITION_RE = /^\s*([a-z][a-z0-9_]*)\s*(<=|>=|==|!=|<|>)\s*(\d{2}\/\d{2})\s*$/;
  function evalCondition(rawCond, valeurs) {
    if (!rawCond) return true;
    const m = CONDITION_RE.exec(rawCond);
    if (!m) return true; // condition mal formee : permissif (validator backend l'aura rejete)
    const inputId = m[1];
    const op = m[2];
    const dateLit = m[3];
    const valUser = valeurs[inputId];
    const jourUser = valUser ? jjmmToJourAgricole(valUser) : null;
    const jourCible = jjmmToJourAgricole(dateLit);
    if (jourUser === null || jourCible === null) return true;
    switch (op) {
      case "<": return jourUser < jourCible;
      case "<=": return jourUser <= jourCible;
      case ">": return jourUser > jourCible;
      case ">=": return jourUser >= jourCible;
      case "==": return jourUser === jourCible;
      case "!=": return jourUser !== jourCible;
    }
    return true;
  }

  // Hierarchie de severite des regimes pour la linearisation visuelle
  // (cf. spec_extension_grammaire_condition §Linearisation). Plus la
  // valeur est haute, plus le regime est severe -> il "gagne" quand
  // 2 periodes principales se chevauchent au meme jour. Hors masque
  // uniquement : les masques ont leur propre passe et ne participent
  // pas a la hierarchie principale.
  const SEVERITE_REGIME = {
    libre: 0,
    plafonnement: 1,
    autorisation_sous_condition: 2,
    interdiction: 3,
    non_applicable: -1,
  };

  // Construit le tableau régime-par-jour en 2 passes (cf.
  // spec_grammaire_calculatrice §masque + spec_extension_grammaire_condition) :
  //
  //   Filtrage prealable — Periodes dont la `condition` est fausse sont
  //     retirees avant la 1re passe (idem que si elles n'existaient pas).
  //
  //   Passe 1 — Périodes PRINCIPALES (masque ≠ true). Sur chevauchement,
  //     le regime LE PLUS SEVERE gagne (linearisation visuelle).
  //
  //   Passe 2 — Périodes MASQUE (masque === true). Elles ne s'appliquent
  //     QUE sur l'intersection avec les jours déjà couverts par une
  //     période principale en passe 1. Hors intersection : silence
  //     (la période est sans effet, pas d'affichage). Sur la zone
  //     intersection, le masque ecrase la principale (override : c'est
  //     le but du masque, ex 'interdit avant 4 semaines apres semis').
  //
  // Le `libre` initial = pas de zone overlay (fond vert visible).
  function computeRegimePerDay(periodes, valeurs) {
    const result = new Array(TOTAL_JOURS).fill("libre");

    // Sentinel : qui a touché chaque jour en passe 1 ? Sert à savoir
    // si une période masque peut écrire à cet index ou non.
    const principalCovers = new Array(TOTAL_JOURS).fill(false);

    const poserPrincipale = (p) => {
      const du = parseBorne(p.du, valeurs).jour;
      const au = parseBorne(p.au, valeurs).jour;
      const regime = p.regime || data.type || "interdiction";
      if (du === null || au === null) return;
      const apply = (i) => {
        // Hierarchie : on ecrit seulement si le nouveau regime est >=
        // celui deja en place (sur cet index). 'libre' a severite 0,
        // donc tout regime principal l'ecrase. Si 2 principales se
        // chevauchent, la plus severe gagne.
        const cur = result[i];
        if (
          !principalCovers[i] ||
          (SEVERITE_REGIME[regime] ?? 0) >= (SEVERITE_REGIME[cur] ?? 0)
        ) {
          result[i] = regime;
        }
        principalCovers[i] = true;
      };
      if (du <= au) {
        for (let i = du; i <= au; i++) apply(i);
      } else {
        for (let i = du; i < TOTAL_JOURS; i++) apply(i);
        for (let i = 0; i <= au; i++) apply(i);
      }
    };

    const poserMasque = (p) => {
      const du = parseBorne(p.du, valeurs).jour;
      const au = parseBorne(p.au, valeurs).jour;
      const regime = p.regime || data.type || "interdiction";
      if (du === null || au === null) return;
      const apply = (i) => {
        if (principalCovers[i]) result[i] = regime;
      };
      if (du <= au) {
        for (let i = du; i <= au; i++) apply(i);
      } else {
        for (let i = du; i < TOTAL_JOURS; i++) apply(i);
        for (let i = 0; i <= au; i++) apply(i);
      }
    };

    // Filtrage : retire les periodes dont la condition est fausse pour
    // les valeurs courantes (cf. spec_extension_grammaire_condition).
    const periodesActives = (periodes || []).filter((p) =>
      evalCondition(p.condition, valeurs)
    );

    // Passe 1 : principales avec hierarchie.
    for (const p of periodesActives) {
      if (p.masque) continue;
      poserPrincipale(p);
    }
    // Passe 2 : masques sur intersection seulement.
    for (const p of periodesActives) {
      if (!p.masque) continue;
      poserMasque(p);
    }
    return result;
  }

  // ─── État ──────────────────────────────────────────────────────────────
  const inputs = (data.inputs_requis || []).filter(
    (inp) => inp && typeof inp === "object" && inp.id
  );
  if (inputs.length === 0) {
    mount.innerHTML =
      '<p class="fr-alert fr-alert--warning fr-alert--sm">Aucun input requis défini pour cette règle calculatrice.</p>';
    return;
  }

  const valeurs = {};
  for (const inp of inputs) {
    valeurs[inp.id] = inp.placeholder || "";
  }

  // ─── Rendu ─────────────────────────────────────────────────────────────
  // Tout le rendu reproduit la structure DOM du templatetag standard
  // `calendrier_epandage` (cf. _calendrier.html + calendrier.css), de sorte
  // que les 2 calendriers (statique / dynamique) aient le meme look. Les
  // classes utilisees sont `.calendrier-epandage*`.

  function renderMiniForm() {
    // 2 inputs cote a cote, label sur 1 ligne ferme (truncate si trop long)
    // pour eviter que les hauteurs des champs varient selon le label (le
    // user a explicitement reporte cet alignement casse).
    //
    // Pico calendrier SVG (DSFR icon calendar-line equivalent, inline pour
    // eviter un asset HTTP supplementaire). Le pictogramme ne sert qu'a
    // signaler que c'est un champ date, pas a ouvrir un date picker
    // (impossible JJ/MM sans annee en HTML natif -- MVP-2).
    const SVG_CAL =
      '<svg class="calc-cal__field-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">' +
      '<rect x="3.5" y="5" width="17" height="15" rx="2"/>' +
      '<line x1="3.5" y1="9.5" x2="20.5" y2="9.5"/>' +
      '<line x1="8" y1="3" x2="8" y2="6.5"/>' +
      '<line x1="16" y1="3" x2="16" y2="6.5"/>' +
      "</svg>";
    return `
      <div class="calc-cal__form">
        ${inputs
          .map((inp) => {
            const isDefault =
              valeurs[inp.id] && valeurs[inp.id] === (inp.placeholder || "");
            return `
          <label class="calc-cal__field">
            <span class="calc-cal__field-label">${escapeHtml(inp.label || inp.id)}</span>
            <input type="text"
                   class="fr-input"
                   data-input-id="${escapeHtml(inp.id)}"
                   value="${escapeHtml(valeurs[inp.id])}"
                   placeholder="JJ/MM"
                   pattern="^\\d{2}/\\d{2}$"
                   maxlength="5"
                   ${isDefault ? 'data-default="true"' : ""}>
            ${SVG_CAL}
          </label>
        `;
          })
          .join("")}
      </div>
    `;
  }

  function renderCalendrier(regimeParJour, actives) {
    // Segments contigus de même régime. On ne génère une zone overlay
    // QUE pour rouge/orange : le vert est le fond global de la barre.
    const segmentsRaw = [];
    let cur = { regime: regimeParJour[0], du: 0, au: 0 };
    for (let i = 1; i < TOTAL_JOURS; i++) {
      if (regimeParJour[i] === cur.regime) {
        cur.au = i;
      } else {
        segmentsRaw.push(cur);
        cur = { regime: regimeParJour[i], du: i, au: i };
      }
    }
    segmentsRaw.push(cur);

    const zonesHtml = segmentsRaw
      .map((s) => {
        const couleur = REGIME_COULEUR_ZONE[s.regime];
        if (!couleur) return "";
        const w = ((s.au - s.du + 1) / TOTAL_JOURS) * 100;
        const left = (s.du / TOTAL_JOURS) * 100;
        const flottant = isPeriodeFlottante(s, actives);
        const classes = [
          "calendrier-epandage__zone",
          `calendrier-epandage__zone--${couleur}`,
        ];
        if (flottant) classes.push("calendrier-epandage__zone--flottant");
        // Tooltip : phrase humaine qui decrit la fenetre. On cherche la
        // periode YAML d'origine qui couvre ce segment (premier match)
        // pour reutiliser sa structure (du, au, regime) et generer une
        // annotation event+offset si applicable.
        const tooltip = buildTooltipForSegment(s, actives);
        return `<div class="${classes.join(" ")}"
                     style="left:${left.toFixed(3)}%; width:${w.toFixed(3)}%"
                     aria-label="${escapeHtml(tooltip)}"
                     data-tooltip="${escapeHtml(tooltip)}"></div>`;
      })
      .join("");

    // Marqueur "aujourd'hui" : point noir DANS la barre (cf. CSS standard
    // `.calendrier-epandage__today`). Pas de label add-on : le CSS standard
    // le pose deja via ::after "Aujourd'hui" sous le point.
    const aujourdhui = aujourdhuiAgricole();
    const aujLeft = aujourdhui != null ? (aujourdhui / TOTAL_JOURS) * 100 : null;
    const aujourdhuiHtml =
      aujLeft != null
        ? `<div class="calendrier-epandage__today" style="left:${aujLeft.toFixed(3)}%" aria-label="Aujourd'hui"></div>`
        : "";

    // Bornes textuelles sous la barre :
    //   - row0 = label_court des inputs (semis / destruction), trait NOIR
    //     pleine hauteur (= marker user-input).
    //   - row1 = date concrete des bornes event+offset (ex "12 sept."),
    //     en couleur du regime de la periode (rouge/orange/vert).
    const bornesHtml = renderBornes(regimeParJour, actives);

    return `
      <div class="calendrier-epandage calendrier-epandage--vert">
        <div class="calendrier-epandage__months">
          ${MOIS_AGRICOLES.map((m) => `<span>${m}</span>`).join("")}
        </div>
        <div class="calendrier-epandage__bar" data-tooltip="Autorisé">
          ${zonesHtml}
          ${aujourdhuiHtml}
        </div>
        ${bornesHtml}
      </div>
    `;
  }

  // Construit le tooltip humain pour un segment de la barre. Cherche la
  // periode YAML qui couvre la zone (au sens jours) ; si elle est
  // event+offset, genere une phrase « jusqu'a N semaines apres semis ».
  function buildTooltipForSegment(segment, actives) {
    const inputById = Object.fromEntries(inputs.map((i) => [i.id, i]));
    for (const p of actives || []) {
      const partDu = parseBorne(p.du, valeurs);
      const partAu = parseBorne(p.au, valeurs);
      if (partDu.jour === null || partAu.jour === null) continue;
      // Match strict : meme bornes.
      if (partDu.jour !== segment.du || partAu.jour !== segment.au) continue;
      const regime = p.regime || segment.regime || "interdiction";
      const verbe = capitalize(REGIME_VERBE[regime] || regime);
      const annDu = annoterBorne(partDu, "du", inputById);
      const annAu = annoterBorne(partAu, "au", inputById);
      const annotations = [annDu, annAu].filter(Boolean);
      if (annotations.length > 0) {
        return `${verbe} ${annotations.join(", ")}`;
      }
      const duStr = jourAgricoleToLisible(partDu.jour);
      const auStr = jourAgricoleToLisible(partAu.jour);
      return `${verbe} du ${duStr} au ${auStr}`;
    }
    return REGIME_VERBE[segment.regime] || segment.regime;
  }

  // Genere « a partir de N jours apres semis » (mode=du) ou « jusqu'a
  // N jours apres semis » (mode=au), seulement pour les bornes event+offset.
  // Pour les bornes event nu (sans offset), pas d'annotation.
  function annoterBorne(part, mode, inputById) {
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
  }

  // Heuristique : un segment dont l'une des bornes YAML d'origine est un
  // event nu (sans date connue cote utilisateur) -> hachuré flottant.
  // Pour MVP, on considere qu'une periode est flottante uniquement si la
  // borne YAML est un event SANS placeholder et SANS valeur saisie.
  function isPeriodeFlottante(segment, periodes) {
    for (const p of periodes || []) {
      const du = parseBorne(p.du, valeurs);
      const au = parseBorne(p.au, valeurs);
      if (du.jour === segment.du && au.jour === segment.au) {
        return (du.isEvent && du.jour === null) || (au.isEvent && au.jour === null);
      }
    }
    return false;
  }

  // Bornes sous la barre, structurees sur N rows (auto-bump anti-overlap) :
  //
  //   row0 (au plus pres de la barre) : dates FIXES (`JJ/MM`) en couleur
  //                                     du regime (rouge prime sur orange).
  //   row1                            : ticks INPUTS (semis, destruction) -
  //                                     trait noir pleine hauteur.
  //   row2                            : bornes CALCULEES (event+offset),
  //                                     ex « 12 sept. », en couleur du regime.
  //
  // Si 2 labels d'une meme row se chevauchent horizontalement (gap < 28px),
  // le 2eme est decale au-dessus en row+1. Pour eviter une cascade trop
  // profonde, profondeur max = 4 rows.
  //
  // Une date fixe est silencieusement skipee si elle tombe sur la meme
  // position qu'un tick input ou qu'une borne calculee (= +/- 1 jour
  // de tolerance) : cela evite l'effet "double tick" sur la meme borne
  // (cf. retour user : "destruction = 15/01 -> pas besoin de re-afficher
  // 15 jan.").
  function renderBornes(regimeParJour) {
    const fixedItems = fixedBornesAsItems(regimeParJour);
    const inputItems = inputsAsBorneItems();
    const computedItems = computedBornesAsItems();
    const refDays = collectRefDays(inputItems, computedItems);
    const filteredFixed = fixedItems.filter(
      (it) => !refDays.some((d) => Math.abs(d - it.jour) <= 1),
    );
    const all = [...filteredFixed, ...inputItems, ...computedItems];
    if (all.length === 0) return "";

    // Auto-bump anti-overlap : on parcourt chaque row dans son ordre
    // canonique (0=fixe, 1=input, 2=calc) et on assigne pct croissant.
    // Si le pct precedent de cette row est trop proche, on push l'item
    // a la row suivante (et on rebrasse). Profondeur max = 4 rows.
    assignRowsWithBump(all);

    const inner = all
      .map((it) => {
        const cls = [
          "calendrier-epandage__period-date",
          "calendrier-epandage__period-date--phenologique",
        ];
        // row 0 = pas de classe (default). row 1+ = classe row{N} qui
        // decale verticalement de N*18px (cf. CSS).
        if (it.row >= 1) cls.push(`calendrier-epandage__period-date--row${it.row + 1}`);
        if (it.couleur) {
          cls.push(`calendrier-epandage__period-date--${it.couleur}`);
        }
        // Trait pleine hauteur (jusqu'au haut de la barre) pour les ticks
        // INPUTS uniquement (semis, destruction). Les bornes fixes /
        // calculees s'arretent au bord superieur de leur row.
        if (it.kind === "input") {
          cls.push("calendrier-epandage__period-date--big-tick");
        }
        const tip = it.title || it.label;
        return `<span class="${cls.join(" ")}"
                       style="left:${it.pct.toFixed(3)}%"
                       data-tooltip="${escapeHtml(tip)}">${escapeHtml(it.label)}</span>`;
      })
      .join("");
    return `<div class="calendrier-epandage__period">${inner}</div>`;
  }

  // Dates fixes des periodes principales : on liste chaque borne `du`/`au`
  // au format JJ/MM (pas event). La couleur reflete le regime EFFECTIF
  // au point de transition (en regardant `regimeParJour` aux 2 cotes du
  // tick). Permet de gerer le cas masque : si une borne principale 15/12
  // (cote orange) coincide avec le debut d'une zone rouge masquee, la
  // date 15/12 doit etre rouge (la borne sortante de l'orange est aussi
  // la borne entrante du rouge -> le rouge prime).
  const REGIME_SEVERITE = {
    interdiction: 0,
    plafonnement: 1,
    autorisation_sous_condition: 2,
    libre: 3,
    non_applicable: 4,
  };
  function fixedBornesAsItems(regimeParJour) {
    const byJour = new Map(); // jour -> {jour, borneName}
    const activeSet = activePeriodesSet();
    for (const p of data.periodes || []) {
      if (!activeSet.has(p)) continue;
      if (p.masque) continue; // les masques ont leurs bornes traitees via row2
      for (const borneName of ["du", "au"]) {
        const val = p[borneName];
        if (!val || !/^\d{2}\/\d{2}$/.test(val)) continue;
        const j = jjmmToJourAgricole(val);
        if (j === null) continue;
        // On retient la borne (pas le regime de la periode source).
        if (!byJour.has(j)) {
          byJour.set(j, { jour: j, borneName });
        }
      }
    }
    const items = [];
    for (const { jour, borneName } of byJour.values()) {
      // Couleur = regime le plus restrictif des 2 cotes du tick.
      // - borne `du` : regime entrant = regimeParJour[jour]
      // - borne `au` : regime sortant = regimeParJour[jour]
      // On regarde aussi le voisin pour gerer la frontiere.
      const regimeIci = regimeParJour[jour] || "libre";
      const regimeAvant =
        regimeParJour[(jour - 1 + TOTAL_JOURS) % TOTAL_JOURS] || "libre";
      const regimeApres = regimeParJour[(jour + 1) % TOTAL_JOURS] || "libre";
      // Pour une borne `du`, le tick est a gauche de la zone : on compare
      // regime entrant (jour) et celui d'avant (jour-1). Idem `au` : compare
      // regime sortant (jour) et celui d'apres (jour+1) -- le tick est
      // au bord droit (j+1).
      const candidats =
        borneName === "du" ? [regimeIci, regimeAvant] : [regimeIci, regimeApres];
      const regime = candidats.reduce(
        (best, r) =>
          (REGIME_SEVERITE[r] ?? 99) < (REGIME_SEVERITE[best] ?? 99) ? r : best,
        "libre",
      );
      const jourPourPct = borneName === "au" ? jour + 1 : jour;
      items.push({
        label: jourAgricoleToLisible(jour),
        pct: (jourPourPct / TOTAL_JOURS) * 100,
        jour,
        row: 0,
        couleur: REGIME_COULEUR_ZONE[regime] || null,
        title: null,
        kind: "fixed",
      });
    }
    return items;
  }

  // Collecte les jours deja occupes par les ticks inputs ou les bornes
  // computees, pour deduplication des dates fixes redondantes (+/- 1
  // jour de tolerance pour absorber l'alignement bord-gauche/bord-droit).
  //
  // IMPORTANT : on lit le `jour` final de chaque item computed deja
  // calcule (apres tronquage masque), pas la borne brute. Sinon une
  // borne masque tronquee a 15/12 ne deduplique pas la date fixe 15/12
  // (cf. bug user 2026-05-28).
  function collectRefDays(inputItems, computedItems) {
    const out = [];
    for (const inp of inputs) {
      const j = jjmmToJourAgricole(valeurs[inp.id]);
      if (j !== null) out.push(j);
    }
    for (const it of computedItems) {
      if (typeof it.jour === "number") out.push(it.jour);
    }
    return out;
  }

  // Bumping anti-overlap : on regroupe les items par row initiale, puis
  // pour chaque row, on parcourt en pct croissant et on detecte les
  // collisions (gap < seuil). Item collisionnant -> push a la row+1
  // (recursivement, max 3 niveaux supplementaires).
  //
  // Gap min = 28px / barWidth. La barre fait usuellement 640px max-width,
  // donc 28/640 = 4.4%. On approxime a 4.4% sans calcul du DOM (on a pas
  // le DOM live au moment du compute).
  const ROW_BUMP_GAP_PCT = (28 / 640) * 100; // ~4.4%
  const MAX_ROW = 3;
  function assignRowsWithBump(items) {
    // Tri par (row initiale, pct croissant) pour traiter chaque row dans
    // l'ordre. Mais comme on bump entre rows, on fait plusieurs passes.
    items.sort((a, b) => a.row - b.row || a.pct - b.pct);
    let changed = true;
    let safety = 20;
    while (changed && safety-- > 0) {
      changed = false;
      const byRow = new Map();
      for (const it of items) {
        if (!byRow.has(it.row)) byRow.set(it.row, []);
        byRow.get(it.row).push(it);
      }
      for (const [, rowItems] of byRow) {
        rowItems.sort((a, b) => a.pct - b.pct);
        for (let i = 1; i < rowItems.length; i++) {
          if (rowItems[i].pct - rowItems[i - 1].pct < ROW_BUMP_GAP_PCT) {
            if (rowItems[i].row < MAX_ROW) {
              rowItems[i].row += 1;
              changed = true;
            }
          }
        }
      }
    }
  }

  function inputsAsBorneItems() {
    const items = [];
    const aligns = inputsBorneAlignments();
    for (const inp of inputs) {
      const j = jjmmToJourAgricole(valeurs[inp.id]);
      if (j === null) continue;
      // Alignement precis (cf. computedBornesAsItems) : si cet input ne
      // sert qu'a une borne `au`, on cale le tick au bord droit de la
      // zone (j+1)/365. Sinon (du, ou indetermine), bord gauche j/365.
      const jourPourPct = aligns.get(inp.id) === "au" ? j + 1 : j;
      items.push({
        label: deduireLabelCourt(inp),
        pct: (jourPourPct / TOTAL_JOURS) * 100,
        // Convention 3-rows (cf. renderBornes) : 0=fixe, 1=input, 2=calc.
        row: 1,
        couleur: null,
        title: `${inp.label || inp.id} : ${valeurs[inp.id]}`,
        kind: "input",
      });
    }
    return items;
  }

  // Scanne les periodes : pour chaque input qui apparait COMME EVENT NU
  // (sans offset) en borne `du` ou `au`, on note de quel cote il sert.
  // Retourne Map<input_id, "du" | "au">. Si l'input sert aux 2 cotes,
  // on prefere "du" (alignement bord gauche, plus naturel pour un evenement
  // qui marque un debut). Si l'input ne sert qu'a une borne avec offset
  // (jamais event nu), on ne tag rien -> tick alignement defaut.
  function inputsBorneAlignments() {
    const map = new Map();
    for (const p of data.periodes || []) {
      for (const borneName of ["du", "au"]) {
        const val = p[borneName];
        if (!val) continue;
        const m = BORNE_RE.exec(val);
        if (!m) continue;
        // Seulement event NU (sans offset) : sinon c'est une borne calculee,
        // pas la position de l'input lui-meme.
        if (m[2]) continue;
        const eventId = m[1];
        if (!map.has(eventId)) {
          map.set(eventId, borneName);
        } else if (map.get(eventId) === "au" && borneName === "du") {
          // Preference "du" si l'input sert aux 2 cotes.
          map.set(eventId, "du");
        }
      }
    }
    return map;
  }

  // Pour chaque borne calculee (event+offset), produit une etiquette row1
  // avec sa date concrete. La couleur reflete le regime de la periode.
  //
  // Cas particulier MASQUE : on n'affiche pas la borne brute mais la borne
  // EFFECTIVE = intersection avec l'union des principales. Si la borne
  // brute tombe hors d'une principale, l'arete de la principale prend le
  // relais et on affiche cette derniere a la place (couleur = regime
  // masque, ex rouge si interdiction). Si l'arete coincide avec une
  // borne d'une principale (ex 15/12 cote orange), la borne effective
  // de la principale "perd" sa couleur orange au profit du rouge masque.
  //
  // Alignement precis : une zone overlay `[du..au]` (avec `au` inclus dans
  // la boucle de remplissage) s'etend visuellement de `du/365` a `(au+1)/365`.
  // Donc :
  //   - borne `du` -> tick a `du/365` (bord gauche de la zone)
  //   - borne `au` -> tick a `(au+1)/365` (bord droit de la zone)
  function computedBornesAsItems() {
    const items = [];
    const activeSet = activePeriodesSet();
    for (const p of data.periodes || []) {
      if (!activeSet.has(p)) continue;
      // Bornes effectives : pour les principales c'est la borne YAML
      // resolue ; pour les masques c'est l'intersection avec les principales.
      const effective = effectivePeriodWindow(p);
      if (!effective) continue;
      const couleur = REGIME_COULEUR_ZONE[p.regime || "interdiction"] || null;
      for (const borneName of ["du", "au"]) {
        const part = parseBorne(p[borneName], valeurs);
        // On ne produit un tick row2 (= "borne calculee") que si la borne
        // YAML est un event+offset. Les dates fixes brutes vont en row0
        // via fixedBornesAsItems().
        if (!part.isEvent || !part.offsetN || part.jour === null) continue;
        // Borne effective : si le masque a tronque la borne, on prend
        // la valeur de l'intersection (effective.du / effective.au).
        const jour =
          borneName === "du" ? effective.du : effective.au;
        const jourPourPct = borneName === "au" ? jour + 1 : jour;
        items.push({
          label: jourAgricoleToLisible(jour),
          pct: (jourPourPct / TOTAL_JOURS) * 100,
          row: 2,
          couleur,
          title: null,
          kind: "computed",
          jour,
        });
      }
    }
    return items;
  }

  // Calcule la fenetre effective d'une periode :
  //   - principale (masque != true) : juste la fenetre YAML resolue.
  //   - masque (masque === true)    : intersection avec l'union des
  //     principales. On retourne le PREMIER segment connexe d'intersection
  //     (sans gerer le cas multi-segments rare ou un masque couvre 2
  //     principales disjointes).
  // Retourne `{du, au}` en index agricole, ou `null` si pas de fenetre.
  function effectivePeriodWindow(p) {
    const du = parseBorne(p.du, valeurs).jour;
    const au = parseBorne(p.au, valeurs).jour;
    if (du === null || au === null) return null;
    if (!p.masque) return { du, au };
    // Masque : intersecter [du..au] avec principalCovers.
    const covers = computePrincipalCovers();
    const inMaskRange = (i) => {
      if (du <= au) return i >= du && i <= au;
      return i >= du || i <= au;
    };
    // Premier jour de l'intersection
    let first = null;
    let last = null;
    const range = (start, end) => {
      for (let i = start; i <= end; i++) {
        if (inMaskRange(i) && covers[i]) {
          if (first === null) first = i;
          last = i;
        } else if (first !== null) {
          // fin du 1er segment connexe
          return true;
        }
      }
      return false;
    };
    // Parcourir l'annee dans l'ordre [du..end][0..au] si wrap, sinon [du..au].
    if (du <= au) {
      range(du, au);
    } else {
      if (!range(du, TOTAL_JOURS - 1)) {
        range(0, au);
      }
    }
    if (first === null) return null;
    return { du: first, au: last };
  }

  // Retourne le Set des periodes "actives" pour les render-helpers :
  //   - les periodes dont la `condition` est vraie pour les valeurs
  //     courantes du form (cf. spec_extension_grammaire_condition) ;
  //   - parmi celles-la : toutes les principales (masque != true), meme
  //     si bornes non resolues -- elles seront ignorees plus loin via
  //     parseBorne null ;
  //   - et les masques dont l'intersection avec les principales est
  //     non vide.
  function activePeriodesSet() {
    const periodes = (data.periodes || []).filter((p) =>
      evalCondition(p.condition, valeurs)
    );
    const principalCovers = computePrincipalCovers(periodes);
    const result = new Set();
    for (const p of periodes) {
      if (!p.masque) {
        result.add(p);
        continue;
      }
      // Masque : verifier l'intersection avec principalCovers.
      const du = parseBorne(p.du, valeurs).jour;
      const au = parseBorne(p.au, valeurs).jour;
      if (du === null || au === null) continue;
      if (hasIntersection(principalCovers, du, au)) {
        result.add(p);
      }
    }
    return result;
  }

  function computePrincipalCovers(periodes) {
    // `periodes` peut etre fourni (deja filtre par condition) ou non
    // (fallback : on lit data.periodes et on filtre ici).
    const liste = periodes || (data.periodes || []).filter((p) =>
      evalCondition(p.condition, valeurs)
    );
    const covers = new Array(TOTAL_JOURS).fill(false);
    for (const p of liste) {
      if (p.masque) continue;
      const du = parseBorne(p.du, valeurs).jour;
      const au = parseBorne(p.au, valeurs).jour;
      if (du === null || au === null) continue;
      if (du <= au) {
        for (let i = du; i <= au; i++) covers[i] = true;
      } else {
        for (let i = du; i < TOTAL_JOURS; i++) covers[i] = true;
        for (let i = 0; i <= au; i++) covers[i] = true;
      }
    }
    return covers;
  }

  function hasIntersection(covers, du, au) {
    const test = (i) => covers[i];
    if (du <= au) {
      for (let i = du; i <= au; i++) if (test(i)) return true;
    } else {
      for (let i = du; i < TOTAL_JOURS; i++) if (test(i)) return true;
      for (let i = 0; i <= au; i++) if (test(i)) return true;
    }
    return false;
  }

  function renderLegende(regimeParJour) {
    // Legende dynamique : on ne liste que les couleurs presentes a l'ecran.
    const couleursPresentes = new Set();
    for (const r of regimeParJour) {
      const c = REGIME_COULEUR_ZONE[r];
      if (c) couleursPresentes.add(c);
    }
    // "vert" est toujours present (fond global), mais on ne l'ajoute que
    // s'il existe au moins un jour libre (sinon c'est trompeur).
    if (regimeParJour.some((r) => !REGIME_COULEUR_ZONE[r])) {
      couleursPresentes.add("vert");
    }
    const ordre = ["rouge", "orange", "vert"];
    const labels = {
      rouge: "Interdit",
      orange: "Autorisé sous conditions",
      vert: "Autorisé",
    };
    const items = ordre
      .filter((c) => couleursPresentes.has(c))
      .map(
        (c) => `
        <li>
          <span class="calendrier-epandage__legende-puce calendrier-epandage__legende-puce--${c}"></span>
          ${labels[c]}
        </li>
      `,
      )
      .join("");
    return `<ul class="calendrier-epandage__legende">${items}</ul>`;
  }

  // Traduit une condition "<input_id> <op> <JJ/MM>" en phrase humaine
  // pour le recap, ex "date_destruction_couvert < 05/12" ->
  // "car destruction avant le 5 déc.". Utilise le label_court de l'input
  // pour nommer la date utilisateur. Retourne null si non parseable.
  function conditionToText(rawCond, inputById) {
    if (!rawCond) return null;
    const m = CONDITION_RE.exec(rawCond);
    if (!m) return null;
    const inputId = m[1];
    const op = m[2];
    const dateLit = m[3];
    const inp = inputById[inputId];
    const nom = inp ? deduireLabelCourt(inp) : inputId;
    // Date litterale en forme lisible (5 déc.) via l'index agricole.
    const jour = jjmmToJourAgricole(dateLit);
    const dateStr = jour != null ? jourAgricoleToLisible(jour) : dateLit;
    // Operateur -> tournure FR. On parle de la date `nom` par rapport au
    // seuil `dateStr`.
    const tournure = {
      "<": `avant le ${dateStr}`,
      "<=": `au plus tard le ${dateStr}`,
      ">": `après le ${dateStr}`,
      ">=": `à partir du ${dateStr}`,
      "==": `le ${dateStr}`,
      "!=": `différent du ${dateStr}`,
    }[op];
    if (!tournure) return null;
    return `car ${nom} ${tournure}`;
  }

  function renderRecap(periodes) {
    // Pour chaque période : phrase courte expliquant la fenêtre concrète.
    // Periodes masque sans intersection : silencieux (cf. spec masque).
    const inputById = Object.fromEntries(inputs.map((i) => [i.id, i]));
    const activeSet = activePeriodesSet();
    const lignes = [];
    for (const p of periodes || []) {
      if (!activeSet.has(p)) continue;
      const regime = p.regime || "interdiction";
      const verbe = REGIME_VERBE[regime] || regime;
      const partDu = parseBorne(p.du, valeurs);
      const partAu = parseBorne(p.au, valeurs);
      const duStr = partDu.jour != null ? jourAgricoleToLisible(partDu.jour) : "?";
      const auStr = partAu.jour != null ? jourAgricoleToLisible(partAu.jour) : "?";
      const annDu = annoterBorne(partDu, "du", inputById);
      const annAu = annoterBorne(partAu, "au", inputById);
      let ligne = `<strong>${capitalize(verbe)}</strong> du ${duStr} au ${auStr}`;
      const annotations = [annDu, annAu].filter(Boolean);
      if (annotations.length > 0) {
        ligne += ` <span class="calc-cal__recap-annot">(${annotations.join(", ")})</span>`;
      }
      // Mention conditionnelle : si la periode n'est posee que sous condition
      // (cf. spec_extension_grammaire_condition), on l'explicite a l'utilisateur
      // pour qu'il comprenne POURQUOI cette fenetre s'applique a son cas.
      const condTxt = conditionToText(p.condition, inputById);
      if (condTxt) {
        ligne += ` <span class="calc-cal__recap-cond">— ${escapeHtml(condTxt)}</span>`;
      }
      lignes.push(`<li>${ligne}</li>`);
    }
    if (lignes.length === 0) return "";
    return `
      <div class="calc-cal__recap">
        <h4 class="fr-h6">Récapitulatif</h4>
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

  // Periodes a considerer pour le rendu courant : celles dont la condition
  // est vraie pour les valeurs courantes du form. Recalculee a chaque render
  // (cf. spec_extension_grammaire_condition §Recalcul a chaque change).
  function periodesActives() {
    return (data.periodes || []).filter((p) =>
      evalCondition(p.condition, valeurs)
    );
  }

  function render() {
    const actives = periodesActives();
    const regimeParJour = computeRegimePerDay(actives, valeurs);
    mount.innerHTML = `
      ${renderMiniForm()}
      ${renderCalendrier(regimeParJour, actives)}
      ${renderLegende(regimeParJour)}
      ${renderRecap(actives)}
    `;
    bindInputs();
    bindTooltips();
  }

  // ─── Tooltip JS instantane ─────────────────────────────────────────────
  // Remplace les `title=` natifs (delai 1.5s, customisation impossible)
  // par un `<div>` flottant qui apparait au mouseenter et suit la position
  // approximative de l'element. Tres simple : pas de logique d'overflow
  // boundary, juste positionne au-dessus de l'element.
  let tooltipEl = null;
  function ensureTooltip() {
    if (tooltipEl) return tooltipEl;
    tooltipEl = document.createElement("div");
    tooltipEl.className = "calc-cal__tooltip";
    document.body.appendChild(tooltipEl);
    return tooltipEl;
  }
  // Delegation events : on ecoute mouseover/mousemove/mouseout sur le
  // root (mount). Avantage vs mouseenter/leave par element : quand le
  // pointeur transite d'un overlay (zone rouge) vers la barre verte
  // parente, on reactive bien le tooltip "Autorisé" -- alors qu'avec
  // mouseenter/leave on aurait juste un mouseleave de la zone rouge
  // sans mouseenter de la barre (car on n'est jamais vraiment sorti
  // de la barre, juste de l'enfant zone).
  function bindTooltips() {
    let lastTarget = null;
    mount.addEventListener("mouseover", (e) => {
      const target = e.target.closest("[data-tooltip]");
      if (!target) return;
      const txt = target.getAttribute("data-tooltip");
      if (!txt) return;
      const tip = ensureTooltip();
      tip.textContent = txt;
      tip.style.opacity = "1";
      lastTarget = target;
      positionTooltip(e);
    });
    mount.addEventListener("mousemove", (e) => {
      const target = e.target.closest("[data-tooltip]");
      if (!target) {
        if (tooltipEl) tooltipEl.style.opacity = "0";
        lastTarget = null;
        return;
      }
      // Si on a change de target, refresh le texte.
      if (target !== lastTarget) {
        const txt = target.getAttribute("data-tooltip");
        if (txt) {
          const tip = ensureTooltip();
          tip.textContent = txt;
          tip.style.opacity = "1";
          lastTarget = target;
        }
      }
      positionTooltip(e);
    });
    mount.addEventListener("mouseleave", () => {
      if (tooltipEl) tooltipEl.style.opacity = "0";
      lastTarget = null;
    });
  }
  // Positionne le tooltip juste au-dessus du curseur (legerement decale
  // a droite pour ne pas masquer le pointeur). On suit la souris pour
  // que l'utilisateur sache quelle zone est decrite, surtout sur les
  // grandes zones (cas "Autorisé" qui occupe toute la barre verte).
  function positionTooltip(e) {
    if (!tooltipEl) return;
    const tipRect = tooltipEl.getBoundingClientRect();
    const left = e.pageX + 12;
    const top = e.pageY - tipRect.height - 10;
    tooltipEl.style.left = `${Math.max(4, left)}px`;
    tooltipEl.style.top = `${Math.max(4, top)}px`;
  }

  function bindInputs() {
    mount.querySelectorAll("input[data-input-id]").forEach((el) => {
      // Des qu'on focus, la valeur n'est plus celle "par defaut" -- on
      // enleve le grisé pour signaler que l'utilisateur a la main.
      el.addEventListener("focus", () => {
        el.removeAttribute("data-default");
      });
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
      // Date picker JJ/MM custom (HTML natif ne supporte pas le picker
      // sans annee, cf. spec_rendu_simulateur_calculatrice). Click sur
      // l'input ou son picto -> popup avec 2 selects jour + mois.
      attachJjmmPicker(el);
    });
  }

  // ─── Date picker JJ/MM custom ──────────────────────────────────────────
  // Popup leger : 2 selects (jour, mois) + bouton "OK". Pas de bibliotheque
  // externe ; le composant doit rester self-contained. Le picker se ferme
  // au clic dehors ou au choix d'une date.
  const MOIS_LABELS = [
    ["01", "Janvier"], ["02", "Février"], ["03", "Mars"], ["04", "Avril"],
    ["05", "Mai"], ["06", "Juin"], ["07", "Juillet"], ["08", "Août"],
    ["09", "Septembre"], ["10", "Octobre"], ["11", "Novembre"], ["12", "Décembre"],
  ];
  const JOURS_PAR_MOIS = {
    "01": 31, "02": 29, "03": 31, "04": 30, "05": 31, "06": 30,
    "07": 31, "08": 31, "09": 30, "10": 31, "11": 30, "12": 31,
  };

  let openPicker = null;

  function attachJjmmPicker(inputEl) {
    const field = inputEl.closest(".calc-cal__field");
    if (!field) return;

    const open = () => {
      if (openPicker) openPicker.close();
      const popup = createPickerPopup(inputEl);
      field.appendChild(popup);
      openPicker = {
        el: popup,
        close: () => {
          popup.remove();
          openPicker = null;
          document.removeEventListener("mousedown", outsideHandler, true);
        },
      };
      const outsideHandler = (e) => {
        if (!popup.contains(e.target) && e.target !== inputEl) {
          openPicker.close();
        }
      };
      // Defer l'ajout du listener pour eviter de capturer le click qui
      // a ouvert le popup.
      setTimeout(() => {
        document.addEventListener("mousedown", outsideHandler, true);
      }, 0);
    };

    inputEl.addEventListener("click", open);
    // Picto calendrier (sibling de l'input dans le label) clickable aussi.
    const picto = field.querySelector(".calc-cal__field-icon");
    if (picto) {
      picto.style.pointerEvents = "auto";
      picto.style.cursor = "pointer";
      picto.addEventListener("click", (e) => {
        e.preventDefault();
        inputEl.focus();
        open();
      });
    }
  }

  // Date picker JJ/MM : grille calendrier d'un mois (jour cliquable) +
  // navigation mois precedent / suivant en haut. Pas d'annee : on n'affiche
  // qu'un libelle "Janvier" / "Fevrier" / ... Le mois courant a l'ouverture
  // est celui de l'input (ou janvier par defaut).
  function createPickerPopup(inputEl) {
    const current = parseJjmm(inputEl.value) || { jour: 15, mois: 1 };
    const state = { mois: current.mois, jour: current.jour };

    const popup = document.createElement("div");
    popup.className = "calc-cal__picker";
    popup.innerHTML = `
      <div class="calc-cal__picker-header">
        <button type="button" class="calc-cal__picker-nav" data-nav="prev" aria-label="Mois précédent">‹</button>
        <span class="calc-cal__picker-mois-label" data-mois-label></span>
        <button type="button" class="calc-cal__picker-nav" data-nav="next" aria-label="Mois suivant">›</button>
      </div>
      <div class="calc-cal__picker-weekdays">
        <span>L</span><span>M</span><span>M</span><span>J</span><span>V</span><span>S</span><span>D</span>
      </div>
      <div class="calc-cal__picker-grid" data-grid></div>
    `;

    const moisLabel = popup.querySelector("[data-mois-label]");
    const grid = popup.querySelector("[data-grid]");

    function render() {
      moisLabel.textContent = MOIS_LABELS[state.mois - 1][1];
      const maxJour = JOURS_PAR_MOIS[String(state.mois).padStart(2, "0")] || 31;
      // Pour avoir une grille lisible, on aligne sur le 1er jour de la semaine.
      // On choisit une annee "neutre" (2024, bissextile, 1er janv = lundi) ;
      // le rendu visuel est juste cosmetique, l'utilisateur clique un jour
      // qui s'enregistre en JJ/MM, l'annee ne sert qu'a la grille.
      const RYEAR = 2024;
      const firstDay = new Date(RYEAR, state.mois - 1, 1);
      // Mon-based weekday : 0=Lun, ..., 6=Dim (JS getDay : 0=Dim, ..., 6=Sam).
      const offset = (firstDay.getDay() + 6) % 7;
      const cells = [];
      for (let i = 0; i < offset; i++) {
        cells.push('<button type="button" class="calc-cal__picker-day calc-cal__picker-day--empty" disabled></button>');
      }
      for (let j = 1; j <= maxJour; j++) {
        const isSel = j === state.jour && state.mois === current.mois;
        cells.push(
          `<button type="button" class="calc-cal__picker-day${isSel ? " calc-cal__picker-day--selected" : ""}" data-jour="${j}">${j}</button>`,
        );
      }
      grid.innerHTML = cells.join("");
      grid.querySelectorAll("[data-jour]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const jour = parseInt(btn.dataset.jour, 10);
          const jj = String(jour).padStart(2, "0");
          const mm = String(state.mois).padStart(2, "0");
          inputEl.value = `${jj}/${mm}`;
          inputEl.removeAttribute("data-default");
          inputEl.dispatchEvent(new Event("change", { bubbles: true }));
          if (openPicker) openPicker.close();
        });
      });
    }

    popup.querySelectorAll(".calc-cal__picker-nav").forEach((btn) => {
      btn.addEventListener("click", () => {
        const dir = btn.dataset.nav === "prev" ? -1 : 1;
        state.mois = ((state.mois - 1 + dir + 12) % 12) + 1;
        render();
      });
    });

    render();
    return popup;
  }

  function parseJjmm(s) {
    const m = /^(\d{2})\/(\d{2})$/.exec(s);
    if (!m) return null;
    return { jour: parseInt(m[1], 10), mois: parseInt(m[2], 10) };
  }

  render();
})();
