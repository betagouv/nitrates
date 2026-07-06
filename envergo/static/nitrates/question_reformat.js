// Reformatage front-only de certaines questions trop longues (#192).
//
// Contexte : certaines questions de l'arbre de decision arrivent du YAML sous
// forme d'une seule phrase a rallonge (enumeration « ... ou de ... ou de ... »).
// Les mettre en page proprement (intro + puces) DANS l'arbre est ingerable cote
// contenu. On fait donc un swap purement cosmetique cote front : on reconnait la
// question par sa formulation (tolerant aux variantes de ponctuation / d'escape /
// de reformulation dues aux copier-coller dans le YAML, via distance de
// Levenshtein normalisee), et on remplace le texte brut par une version HTML
// paragraphee.
//
// IMPORTANT : c'est PUREMENT visuel. Le champ, sa valeur, son name, le parcours
// d'arbre cote backend ne changent pas. On ne touche qu'au <p.form-question-text>.
//
// Le meme intitule metier peut exister en PLUSIEURS formulations distinctes dans
// les arbres actifs (national / region Grand Est / zar), pas juste des variantes
// de virgule : ex. une version longue avec enumeration vin+distillation, et une
// version courte « produits alimentaires ou d'aliments pour animaux ». On mappe
// donc CHAQUE formulation au plus pres de son texte reel, avec sa propre mise en
// page (nombre de puces adapte au contenu). Pas de factorisation forcee : une
// entree de dictionnaire par formulation.
(function () {
  "use strict";

  // En Node (tests unitaires), on n'expose que les helpers PURS de matching
  // (normalize / similarity / classify, pas de DOM) puis on sort. En
  // navigateur, on branche le swap sur DOMContentLoaded. cf. reset_form.js.
  const _isNode =
    typeof module !== "undefined" &&
    module.exports &&
    typeof document === "undefined";

  // ── Dictionnaire des reformatages ──────────────────────────────────────
  // Chaque entree :
  //   match : la question telle qu'elle apparait (grosso modo) dans le form.
  //           Sert de reference pour la comparaison floue. Ponctuation, « * »
  //           obligatoire, suffixes type « (Note 12) » et espaces multiples
  //           sont neutralises a la comparaison (cf. normalize()), donc pas
  //           besoin d'etre exact au caractere pres.
  //   html  : le remplacement, insere via innerHTML. Contenu 100% controle ici
  //           (aucune donnee utilisateur), donc pas de risque d'injection. Doit
  //           contenir un <span class="form-question-text__intro"> : c'est la
  //           qu'on re-accroche les suffixes preserves (« * », « (Note 12) »).
  const REFORMATS = [
    {
      // A — version longue (national / zar / partie region) : enumeration
      // alimentaire / vin / distillation. C'est la question de la carte #192.
      match:
        "Le fertilisant utilisé est-il issu de traitement et transformations " +
        "de matières premières en vue de la fabrication de produit alimentaire " +
        "pour l'alimentation humaine ou animale, ou de la préparation et du " +
        "conditionnement de vins, ou de la production par distillation " +
        "d'alcools de bouche d'origine agricole ?",
      html:
        '<span class="form-question-text__intro">Le fertilisant utilisé est issu d\'au moins un de ces procédés&nbsp;:</span>' +
        '<ul class="form-question-text__list">' +
        "<li>de traitement et transformations de matières premières en vue de la fabrication de produit alimentaire pour l'alimentation humaine ou animale</li>" +
        "<li>de la préparation et du conditionnement de vin</li>" +
        "<li>de la production par distillation d'alcools de bouche d'origine agricole</li>" +
        "</ul>",
    },
    {
      // B / C — version courte (region Grand Est « (Note 12) » et national) :
      // uniquement produits alimentaires / aliments pour animaux, sans les
      // clauses vin+distillation. Le suffixe « (Note 12) » eventuel est
      // preserve automatiquement (cf. SUFFIXES).
      match:
        "Le fertilisant utilisé est-il issu du traitement et/ou de la " +
        "transformation de matières premières en vue de la fabrication de " +
        "produits alimentaires ou d'aliments pour animaux ?",
      html:
        '<span class="form-question-text__intro">Le fertilisant utilisé est issu du traitement et/ou de la transformation de matières premières en vue de la fabrication&nbsp;:</span>' +
        '<ul class="form-question-text__list">' +
        "<li>de produits alimentaires</li>" +
        "<li>ou d'aliments pour animaux</li>" +
        "</ul>",
    },
  ];

  // Suffixes de fin de question a PRESERVER (re-accroches a l'intro apres swap),
  // pour ne pas perdre l'indication d'obligatoire ni le renvoi de note.
  // Ordre = ordre d'affichage. Detectes sur le texte brut d'origine.
  const SUFFIXES = [
    { test: /\(note\s*\d+\)\s*/i, extract: (raw) => (raw.match(/\(Note\s*\d+\)/i) || [null])[0] },
    { test: /\*\s*$/, html: '<span aria-hidden="true">*</span>' },
  ];

  // Seuil de similarite (1 = identique). Au-dessus -> meme formulation.
  // 0.85 tolere les variantes de virgule / accents / « ou, » vs « , ou » et le
  // suffixe « (Note 12) » (B vs C ~0.96), tout en separant nettement la version
  // longue de la version courte (A vs B/C ~0.49) et des autres questions (~0.1).
  const SEUIL = 0.85;

  // Normalise pour la comparaison : minuscules, apostrophes uniformisees,
  // insecables -> espace, ponctuation retiree, « * » et « (note N) » retires,
  // espaces multiples compresses. Neutralise les differences cosmetiques dues
  // aux copier-coller dans le YAML.
  function normalize(s) {
    return (s || "")
      .toLowerCase()
      .replace(/[’‘ʼ`]/g, "'") // apostrophes typographiques -> '
      .replace(/ /g, " ") // nbsp -> espace
      .replace(/\(note\s*\d+\)/gi, " ") // renvois de note -> espace
      .replace(/[.,;:!?()«»"*/]/g, " ") // ponctuation (dont / de « et/ou ») -> espace
      .replace(/\s+/g, " ")
      .trim();
  }

  // Distance de Levenshtein (iterative, memoire O(min)). Suffisant pour des
  // chaines de quelques centaines de caracteres, execute une poignee de fois.
  function levenshtein(a, b) {
    if (a === b) return 0;
    if (!a.length) return b.length;
    if (!b.length) return a.length;
    let prev = new Array(b.length + 1);
    let curr = new Array(b.length + 1);
    for (let j = 0; j <= b.length; j++) prev[j] = j;
    for (let i = 1; i <= a.length; i++) {
      curr[0] = i;
      const ca = a.charCodeAt(i - 1);
      for (let j = 1; j <= b.length; j++) {
        const cost = ca === b.charCodeAt(j - 1) ? 0 : 1;
        curr[j] = Math.min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost);
      }
      const tmp = prev;
      prev = curr;
      curr = tmp;
    }
    return prev[b.length];
  }

  // Similarite normalisee dans [0, 1] : 1 - distance / longueur_max.
  function similarity(a, b) {
    const max = Math.max(a.length, b.length);
    if (max === 0) return 1;
    return 1 - levenshtein(a, b) / max;
  }

  // Pre-normalise les cles du dictionnaire une seule fois.
  const NORMALIZED = REFORMATS.map((r) => ({
    key: normalize(r.match),
    html: r.html,
  }));

  // Logique PURE de matching (testable en Node) : rend l'index de l'entree du
  // dictionnaire qui matche le mieux `raw` (>= SEUIL), ou -1 si aucune. Le
  // score du meilleur candidat est renvoye pour l'introspection des tests.
  function classify(raw) {
    const txt = normalize(raw);
    let bestIdx = -1;
    let bestScore = 0;
    for (let i = 0; i < NORMALIZED.length; i++) {
      const score = similarity(txt, NORMALIZED[i].key);
      if (score > bestScore) {
        bestScore = score;
        bestIdx = i;
      }
    }
    return { index: bestScore >= SEUIL ? bestIdx : -1, score: bestScore };
  }

  // En Node : on expose les helpers purs pour les tests et on sort (pas de DOM).
  if (_isNode) {
    module.exports = { normalize, levenshtein, similarity, classify, suffixHtml, SEUIL };
    return;
  }

  // Reconstruit la chaine de suffixes a re-accrocher a l'intro, a partir du
  // texte brut d'origine (ex. « (Note 12) » puis « * »).
  function suffixHtml(raw) {
    let out = "";
    for (const s of SUFFIXES) {
      if (!s.test.test(raw)) continue;
      if (s.extract) {
        const val = s.extract(raw);
        if (val) out += " " + val;
      } else if (s.html) {
        out += " " + s.html;
      }
    }
    return out;
  }

  function apply() {
    const nodes = document.querySelectorAll(".form-question-text");
    nodes.forEach((node) => {
      if (node.dataset.reformatted === "1") return; // idempotent
      const raw = node.textContent; // avant normalisation (garde « * » / « (Note N) »)
      const txt = normalize(raw);
      if (!txt) return;

      let best = null;
      let bestScore = 0;
      for (const entry of NORMALIZED) {
        const score = similarity(txt, entry.key);
        if (score > bestScore) {
          bestScore = score;
          best = entry;
        }
      }
      if (!best || bestScore < SEUIL) return;

      node.innerHTML = best.html;
      node.classList.add("form-question-text--reformatted");
      node.dataset.reformatted = "1";

      // Re-accroche les suffixes preserves a la fin de l'intro (pas apres la
      // liste), pour garder « * » / « (Note 12) » sur la ligne de titre.
      const suffix = suffixHtml(raw);
      if (suffix) {
        const intro = node.querySelector(".form-question-text__intro");
        if (intro) intro.insertAdjacentHTML("beforeend", suffix);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", apply);
  } else {
    apply();
  }
})();
