// Cascade des questions complementaires conditionnelles (#58.1).
//
// Le serveur peut rendre des questions avec un parent (data-qc-parent-champ
// + data-qc-parent-valeur), initialement cachees (attribut `hidden`).
// On les revele/recache quand l'utilisateur clique la bonne valeur sur la
// question parent. Resultat : un seul aller-retour serveur pour repondre a
// toute la cascade de questions complementaires.

(function () {
  "use strict";

  const panneau = document.querySelector(".resultat-panel--questions");
  if (!panneau) return;

  const groupes = Array.from(panneau.querySelectorAll(".qc-question"));
  if (groupes.length === 0) return;

  // Index : pour chaque champ parent, quels groupes conditionnels en
  // dependent ?
  const dependants = new Map();  // parent_champ -> [groupe, ...]
  for (const g of groupes) {
    const parent = g.dataset.qcParentChamp;
    if (!parent) continue;
    if (!dependants.has(parent)) dependants.set(parent, []);
    dependants.get(parent).push(g);
  }

  function valeurActuelle(champ) {
    const checked = document.querySelector(
      `input[type="radio"][name="${champ}"]:checked`
    );
    return checked ? checked.value : null;
  }

  function decocherGroupe(groupe) {
    for (const radio of groupe.querySelectorAll('input[type="radio"]')) {
      radio.checked = false;
    }
  }

  function rafraichirVisibilite(parentChamp) {
    const valeur = valeurActuelle(parentChamp);
    for (const g of dependants.get(parentChamp) || []) {
      const attendue = g.dataset.qcParentValeur;
      if (valeur !== null && String(valeur) === String(attendue)) {
        g.hidden = false;
      } else {
        g.hidden = true;
        decocherGroupe(g);
      }
    }
  }

  // Listeners sur les radios des questions parents
  for (const parentChamp of dependants.keys()) {
    const radios = document.querySelectorAll(
      `input[type="radio"][name="${parentChamp}"]`
    );
    for (const r of radios) {
      r.addEventListener("change", () => rafraichirVisibilite(parentChamp));
    }
    // Sync initial (cas ou un parent est deja coche par checked depuis l'URL)
    rafraichirVisibilite(parentChamp);
  }

  // ─── Navigation clavier des QC (Carte #154, a11y) ─────────────────────
  // Meme modele que le formulaire principal (cascade.js) : chaque radio est un
  // arret de tabulation (tabIndex=0), Tab/fleches parcourent les reponses D'UNE
  // QC, Entree coche + saute au 1er radio de la QC suivante VISIBLE (ou au
  // bouton "Suivant"). Sinon, par defaut, le radio-groupe natif faisait sauter
  // Tab directement a la QC suivante et Entree ne selectionnait pas.
  const submitBtn = document.querySelector(
    "#form-submit-row button[type=submit]"
  );

  // Radios d'une QC (un groupe = un .qc-question), dans l'ordre du DOM.
  function radiosDuGroupe(groupe) {
    return [...groupe.querySelectorAll('input[type="radio"]')];
  }

  // 1er radio de la prochaine QC VISIBLE apres `groupe` (ordre DOM). null sinon.
  function premierRadioQcSuivante(groupe) {
    const idx = groupes.indexOf(groupe);
    for (let i = idx + 1; i < groupes.length; i++) {
      if (!groupes[i].hidden && groupes[i].offsetParent !== null) {
        const first = groupes[i].querySelector('input[type="radio"]');
        if (first) return first;
      }
    }
    return null;
  }

  // Toutes les QC visibles sont-elles repondues ? (parcours QC complet)
  function toutesQcRepondues() {
    for (const g of groupes) {
      if (g.hidden || g.offsetParent === null) continue;
      if (!g.querySelector('input[type="radio"]:checked')) return false;
    }
    return true;
  }

  const reduceMotion =
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Auto-scroll jusqu'au bouton "Suivant" quand la DERNIERE QC vient d'etre
  // repondue (Carte #154). Sur petits ecrans, le bouton etait hors viewport et
  // l'utilisateur ne voyait pas quoi faire ensuite. On prolonge donc
  // l'auto-scroll agreable du form principal jusqu'au bouton de validation.
  function scrollVersBoutonSiComplet() {
    if (!submitBtn) return;
    if (!toutesQcRepondues()) return;
    requestAnimationFrame(function () {
      submitBtn.scrollIntoView({
        behavior: reduceMotion ? "auto" : "smooth",
        block: "center",
      });
    });
  }

  function onQcRadioKeydown(e, input, groupe) {
    if (e.key === "Enter") {
      e.preventDefault();
      if (!input.checked) {
        input.checked = true;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
      // La reponse peut reveler une QC enfant (rafraichirVisibilite via le
      // listener change ci-dessus). Au microtask suivant, on donne le focus au
      // 1er radio de la QC suivante visible, sinon au bouton "Suivant".
      Promise.resolve().then(() => {
        const suivant = premierRadioQcSuivante(groupe);
        if (suivant) suivant.focus();
        else if (submitBtn && !submitBtn.disabled) submitBtn.focus();
      });
      return;
    }
    if (
      e.key === "ArrowDown" ||
      e.key === "ArrowUp" ||
      e.key === "Tab"
    ) {
      const radios = radiosDuGroupe(groupe);
      const i = radios.indexOf(input);
      if (i === -1) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        radios[(i + 1) % radios.length].focus();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        radios[(i - 1 + radios.length) % radios.length].focus();
      } else if (e.key === "Tab") {
        // Tab s'arrete sur chaque reponse ; au bord du groupe, sortie native
        // (vers la QC suivante / le bouton, deja dans l'ordre du DOM).
        if (e.shiftKey) {
          if (i > 0) {
            e.preventDefault();
            radios[i - 1].focus();
          }
        } else if (i < radios.length - 1) {
          e.preventDefault();
          radios[i + 1].focus();
        }
      }
    }
  }

  // Cable tous les radios de toutes les QC (parents ET enfants).
  for (const groupe of groupes) {
    for (const input of radiosDuGroupe(groupe)) {
      input.tabIndex = 0;
      input.addEventListener("keydown", (e) =>
        onQcRadioKeydown(e, input, groupe)
      );
      // A chaque reponse QC : si le parcours QC est complet, on amene au
      // bouton "Suivant" (couvre clic souris ET clavier). Delai pour laisser
      // rafraichirVisibilite (re)calculer la visibilite des QC enfants.
      input.addEventListener("change", function () {
        setTimeout(scrollVersBoutonSiComplet, 60);
      });
    }
  }

  // Focus initial sur la 1re QC EN ATTENTE (Carte #154, a11y) : apres la
  // soumission du form principal, la page recharge et le focus repart en haut
  // -> le 1er Tab renvoyait vers les liens d'evitement au lieu d'entrer dans
  // les QC. On place donc le focus sur le 1er radio de la 1re QC en attente
  // visible, pour que Tab enchaine directement dans les reponses.
  // preventScroll: true -> on ne se bat pas avec scroll_resultat.js (#112) qui
  // gere le cadrage apres stabilisation du layout.
  if (panneau.dataset.qcEnAttente === "true") {
    // Les QC en attente ont l'id_prefix "id_qc_sf_new_". On prend le 1er radio
    // d'une QC en attente actuellement visible (non-hidden).
    const premiereEnAttente = groupes.find(
      (g) =>
        !g.hidden &&
        g.querySelector('input[type="radio"][id^="id_qc_sf_new_"]')
    );
    if (premiereEnAttente) {
      const radio = premiereEnAttente.querySelector('input[type="radio"]');
      if (radio) {
        // Apres le paint, pour ne pas etre ecrase par un focus par defaut.
        requestAnimationFrame(() => radio.focus({ preventScroll: true }));
      }
    }
  }

  // L'auto-scroll vers les QC est gere par scroll_resultat.js (#112), qui
  // couvre aussi le cas "resultat final" et attend la stabilisation du layout
  // (carte Leaflet, images) avant de scroller.
})();
