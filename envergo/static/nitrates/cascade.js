// Cascade en RADIO BUTTONS DSFR du formulaire /simulateur/.
//
// Ordre de cascade UX (5 niveaux visibles) :
//   1. categorie_culture  -> referentiels.categories_cultures
//   2. sous_culture_form  -> categories_cultures[X].sous_cultures (filtre)
//   3. categorie_fertilisant -> referentiels.categories_fertilisants
//   4. sous_fertilisant   -> categories_fertilisants[X].sous_fertilisants
//
// Hidden inputs resolus cote front et envoyes au backend :
//   - occupation_sol      : via mapping_sous_culture_vers_branche
//   - sous_culture        : via mapping_sous_culture_vers_branche
//   - type_fertilisant    : via mapping_sous_fertilisant_vers_type
//   - culture_irriguee_type, prairie_permanente :
//     flags optionnels remplis depuis mapping_sous_culture_vers_branche
//     pour court-circuiter des questions complementaires.
//
// Cas special : "sol_non_cultive" en categorie_culture n'a pas de
// sous-categorie. On saute directement le niveau 2 et on rempli les
// hidden inputs occupation_sol=sol_non_cultive direct.

(function () {
  "use strict";

  const FIELDS = [
    "categorie_culture",
    "sous_culture_form",
    "categorie_fertilisant",
    "sous_fertilisant",
  ];

  const containers = {};
  for (const champ of FIELDS) {
    containers[champ] = document.querySelector(`[data-cascade="${champ}"]`);
  }
  if (!containers.categorie_culture) return;

  const occupationSolHidden = document.getElementById("id_occupation_sol");
  const sousCultureHidden = document.getElementById("id_sous_culture");
  const cultureIrrigueeTypeHidden = document.getElementById(
    "id_culture_irriguee_type"
  );
  const prairiePermanenteHidden = document.getElementById(
    "id_prairie_permanente"
  );
  const typeFertilisantHidden = document.getElementById("id_type_fertilisant");
  // Flags de pre-remplissage portes par certains sous-fertilisants (carte
  // #98 : effluents peu charges issus / non issus d'elevage). Pousses en
  // hidden inputs pour auto-resoudre les questions complementaires de
  // l'arbre (effluent_peu_charge, effluent_peu_charge_elevage), qui ne sont
  // alors pas posees mais inferees -- meme mecanisme que le mais irrigue.
  const effluentPeuChargeHidden = document.getElementById(
    "id_effluent_peu_charge"
  );
  const effluentPeuChargeElevageHidden = document.getElementById(
    "id_effluent_peu_charge_elevage"
  );

  const initial = window.NITRATES_INITIAL_DATA || {};

  let referentiels = null;

  fetch(window.NITRATES_REFERENTIELS_URL)
    .then((r) => r.json())
    .then((r) => {
      referentiels = r;
      initialiser();
    })
    .catch((err) => {
      console.error("Cascade : echec du chargement referentiels", err);
    });

  // ─── Helpers ──────────────────────────────────────────────────────────

  function currentValue(champ) {
    const checked = document.querySelector(
      `input[type="radio"][name="${champ}"]:checked`
    );
    return checked ? checked.value : "";
  }

  function montrerWrapper(champ) {
    const wrapper = document.getElementById(`${champ}-wrapper`);
    if (wrapper) wrapper.hidden = false;
  }
  function cacherWrapper(champ) {
    const wrapper = document.getElementById(`${champ}-wrapper`);
    if (wrapper) wrapper.hidden = true;
  }

  // Section entiere (titre + questions) : cachee tant qu'aucune de ses
  // questions n'est visible, sinon un titre orphelin s'affiche seul (#160).
  function montrerSection(id) {
    const s = document.getElementById(id);
    if (s) s.hidden = false;
  }
  function cacherSection(id) {
    const s = document.getElementById(id);
    if (s) s.hidden = true;
  }

  function viderContainer(champ) {
    const c = containers[champ];
    if (!c) return;
    c.innerHTML = "";
    c.hidden = true;
    cacherWrapper(champ);
    // Vider categorie_fertilisant = la section Fertilisant n'a plus aucune
    // question a montrer -> on cache aussi son titre (#160).
    if (champ === "categorie_fertilisant") {
      cacherSection("section-fertilisant");
    }
  }

  function slug(s) {
    return String(s)
      .replace(/[^a-zA-Z0-9_-]/g, "_")
      .toLowerCase();
  }

  function rendreRadio(container, champ, valeur, libelle, checked) {
    const id = `id_${champ}__${slug(valeur)}`;
    const wrapper = document.createElement("div");
    wrapper.className = "fr-radio-group";
    const input = document.createElement("input");
    input.type = "radio";
    input.id = id;
    input.name = champ;
    input.value = String(valeur);
    if (checked) input.checked = true;
    // Carte #154 (a11y) : chaque radio est un arret de tabulation a lui seul
    // (tabindex=0), au lieu du comportement natif "un seul stop par groupe,
    // fleches pour naviguer". Max veut Tab pour parcourir CHAQUE option, et
    // Entree pour selectionner + sauter au groupe suivant.
    input.tabIndex = 0;
    input.addEventListener("change", () => {
      onChangeChamp(champ);
      mettreAJourBoutonSubmit();
    });
    input.addEventListener("keydown", (e) => onRadioKeydown(e, input, champ));
    const label = document.createElement("label");
    label.className = "fr-label";
    label.htmlFor = id;
    label.textContent = libelle || valeur;
    wrapper.appendChild(input);
    wrapper.appendChild(label);
    container.appendChild(wrapper);
  }

  // Modele clavier des radios (Carte #154, a11y) :
  //  - Entree : coche le radio focalise + declenche la cascade, puis deplace
  //    le focus sur le 1er radio du GROUPE DE QUESTIONS SUIVANT (ex Culture ->
  //    Fertilisant), une fois celui-ci revele.
  //  - Fleches haut/bas : parcourent les radios du meme groupe (sans les
  //    cocher : Max veut la selection uniquement a Entree). On garde ce confort
  //    en plus de Tab.
  function onRadioKeydown(e, input, champ) {
    if (e.key === "Enter") {
      e.preventDefault();
      if (!input.checked) {
        input.checked = true;
        // dispatch change -> onChangeChamp + gating bouton + revele la suite.
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
      // La cascade vient de reveler (ou pas) un groupe suivant. On donne le
      // focus a son 1er radio, au tick suivant (le DOM est deja a jour ici,
      // mais on securise l'ordre avec un microtask).
      Promise.resolve().then(() => focusPremierRadioGroupeSuivant(champ));
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const radios = radiosVisiblesDuGroupe(champ);
      const idx = radios.indexOf(input);
      if (idx === -1) return;
      let next = e.key === "ArrowDown" ? idx + 1 : idx - 1;
      if (next < 0) next = radios.length - 1;
      if (next >= radios.length) next = 0;
      radios[next].focus();
      return;
    }
    // Tab (Carte #154, a11y) : nativement, les radios d'un meme name forment UN
    // seul arret de tabulation -> Tab quitte tout le groupe. Max veut que Tab
    // s'arrete sur CHAQUE radio. On gere donc Tab a la main : deplacement au
    // radio suivant/precedent DANS le groupe ; au bord du groupe, on laisse le
    // comportement natif (Tab sort vers l'element suivant / precedent de la page).
    if (e.key === "Tab") {
      const radios = radiosVisiblesDuGroupe(champ);
      const idx = radios.indexOf(input);
      if (idx === -1) return;
      if (e.shiftKey) {
        // Shift+Tab : radio precedent du groupe ; si on est au 1er, sortie native.
        if (idx > 0) {
          e.preventDefault();
          radios[idx - 1].focus();
        }
      } else {
        // Tab : radio suivant du groupe ; si on est au dernier, sortie native
        // (vers le groupe suivant / le bouton, deja dans l'ordre du DOM).
        if (idx < radios.length - 1) {
          e.preventDefault();
          radios[idx + 1].focus();
        }
      }
    }
  }

  function radiosVisiblesDuGroupe(champ) {
    const container = containers[champ];
    if (!container) return [];
    return [...container.querySelectorAll('input[type="radio"]')];
  }

  // Apres selection d'un radio, focus sur le 1er radio du prochain groupe
  // VISIBLE en aval dans l'ordre de cascade. Si aucun groupe suivant n'est
  // visible (parcours complet), on met le focus sur le bouton "Lancer".
  function focusPremierRadioGroupeSuivant(champActuel) {
    const idx = FIELDS.indexOf(champActuel);
    for (let i = idx + 1; i < FIELDS.length; i++) {
      const container = containers[FIELDS[i]];
      if (container && container.offsetParent !== null) {
        const first = container.querySelector('input[type="radio"]');
        if (first) {
          first.focus();
          return;
        }
      }
    }
    // Plus de question en aval : si le parcours est complet, focus le bouton.
    if (submitBtn && !submitBtn.disabled) submitBtn.focus();
  }

  // ─── Rendu de chaque niveau ───────────────────────────────────────────

  function rendreCategoriesCultures() {
    const container = containers.categorie_culture;
    container.innerHTML = "";
    container.hidden = false;
    montrerWrapper("categorie_culture");
    const cats = (referentiels || {}).categories_cultures || {};
    for (const [cle, meta] of Object.entries(cats)) {
      rendreRadio(
        container,
        "categorie_culture",
        cle,
        meta.libelle_public || cle,
        initial.categorie_culture === cle
      );
    }
  }

  function rendreSousCulturesForm() {
    const container = containers.sous_culture_form;
    container.innerHTML = "";
    const categorie = currentValue("categorie_culture");
    if (!categorie) {
      container.hidden = true;
      cacherWrapper("sous_culture_form");
      return;
    }
    const cats = (referentiels || {}).categories_cultures || {};
    const sousCultures = (referentiels || {}).sous_cultures || {};
    const cles = (cats[categorie] || {}).sous_cultures || [];
    if (cles.length === 0) {
      // Cas sol_non_cultive : pas de sous-categorie, on cache.
      container.hidden = true;
      cacherWrapper("sous_culture_form");
      return;
    }
    container.hidden = false;
    montrerWrapper("sous_culture_form");
    for (const sc of cles) {
      const meta = sousCultures[sc] || {};
      rendreRadio(
        container,
        "sous_culture_form",
        sc,
        meta.libelle_public || sc,
        initial.sous_culture_form === sc
      );
    }
  }

  function rendreCategoriesFertilisant() {
    const container = containers.categorie_fertilisant;
    container.innerHTML = "";
    container.hidden = false;
    montrerSection("section-fertilisant");
    montrerWrapper("categorie_fertilisant");
    const cats = (referentiels || {}).categories_fertilisants || {};
    for (const [cle, meta] of Object.entries(cats)) {
      rendreRadio(
        container,
        "categorie_fertilisant",
        cle,
        meta.libelle_public || cle,
        initial.categorie_fertilisant === cle
      );
    }
  }

  function rendreSousFertilisantPourCategorie() {
    const container = containers.sous_fertilisant;
    container.innerHTML = "";
    const categorie = currentValue("categorie_fertilisant");
    if (!categorie) {
      container.hidden = true;
      cacherWrapper("sous_fertilisant");
      return;
    }
    const cats = (referentiels || {}).categories_fertilisants || {};
    const sousFerts = (referentiels || {}).sous_fertilisants || {};
    const cles = (cats[categorie] || {}).sous_fertilisants || [];
    container.hidden = false;
    montrerWrapper("sous_fertilisant");
    for (const sf of cles) {
      const meta = sousFerts[sf] || {};
      rendreRadio(
        container,
        "sous_fertilisant",
        sf,
        meta.libelle_public || sf,
        initial.sous_fertilisant === sf
      );
    }
  }

  // ─── Gating du bouton de soumission (Carte #154) ──────────────────────
  //
  // Le bouton « Lancer la simulation » ne doit pas etre cliquable tant que
  // toutes les questions actuellement visibles du parcours ne sont pas
  // repondues : soumettre un form incomplet menait a une page d'erreur.
  // C'est aussi la brique de base de l'accessibilite clavier (on ne veut pas
  // qu'un submit clavier parte sur un parcours a moitie rempli).
  //
  // Critere : chaque wrapper cascade actuellement VISIBLE doit avoir un radio
  // coche. Un wrapper cache (niveau pas encore atteint, ou branche
  // court-circuitee comme sol_non_cultive) n'est pas exige. On se base sur la
  // visibilite du container [data-cascade] plutot que sur les hidden inputs
  // pour rester robuste aux branches (ex. sol_non_cultive n'a pas de
  // sous_culture_form mais reste complet).
  const submitBtn = document.querySelector("#form-submit-row button[type=submit]");

  function estVisible(el) {
    // hidden porte soit sur le container [data-cascade], soit sur son wrapper
    // parent (#<champ>-wrapper) ou sa section. offsetParent === null couvre
    // tous les cas (display:none / hidden en cascade), sauf position:fixed
    // (non utilise ici).
    return el && el.offsetParent !== null;
  }

  function parcoursComplet() {
    for (const champ of FIELDS) {
      const container = containers[champ];
      if (!estVisible(container)) continue;
      if (!currentValue(champ)) return false;
    }
    return true;
  }

  function mettreAJourBoutonSubmit() {
    if (!submitBtn) return;
    const complet = parcoursComplet();
    submitBtn.disabled = !complet;
    submitBtn.setAttribute("aria-disabled", String(!complet));
  }

  // Le form « Culture / Fertilisant » est masque tant que la localisation
  // n'est pas faite (simulator.js le devoile au clic carte). A ce moment,
  // categorie_culture devient visible et non repondue -> on recalcule pour
  // desactiver le bouton (sinon il apparait actif a tort, offsetParent etant
  // null tant que le form etait cache).
  document.addEventListener("nitrates:form-revealed", mettreAJourBoutonSubmit);

  // ─── Resolution des hidden inputs ─────────────────────────────────────

  function resoudreOccupationSousCulture() {
    if (!occupationSolHidden) return;
    // Reset des hidden flags. Les hidden form_field=value du POST initial
    // sont preserves seulement quand on est en init replay (pas userDriven).
    if (cultureIrrigueeTypeHidden) cultureIrrigueeTypeHidden.value = "";
    if (prairiePermanenteHidden) prairiePermanenteHidden.value = "";

    const cat = currentValue("categorie_culture");
    if (cat === "sol_non_cultive") {
      occupationSolHidden.value = "sol_non_cultive";
      if (sousCultureHidden) sousCultureHidden.value = "";
      return;
    }
    const sc = currentValue("sous_culture_form");
    if (!sc) {
      occupationSolHidden.value = "";
      if (sousCultureHidden) sousCultureHidden.value = "";
      return;
    }
    const mapping =
      (referentiels || {}).mapping_sous_culture_vers_branche || {};
    const target = mapping[sc] || {};
    occupationSolHidden.value = target.occupation_sol || "";
    if (sousCultureHidden)
      sousCultureHidden.value = target.sous_culture || "";
    // Application des flags optionnels.
    const flags = target.flags || {};
    if (cultureIrrigueeTypeHidden && flags.culture_irriguee_type) {
      cultureIrrigueeTypeHidden.value = flags.culture_irriguee_type;
    }
    if (prairiePermanenteHidden && flags.prairie_permanente !== undefined) {
      prairiePermanenteHidden.value = String(flags.prairie_permanente);
    }
  }

  function resoudreTypeFertilisant() {
    if (!typeFertilisantHidden) return;
    // Reset des flags fertilisant (un autre sous-fertilisant peut ne pas en
    // porter -> on ne laisse pas trainer une valeur d'un choix precedent).
    if (effluentPeuChargeHidden) effluentPeuChargeHidden.value = "";
    if (effluentPeuChargeElevageHidden)
      effluentPeuChargeElevageHidden.value = "";

    const sf = currentValue("sous_fertilisant");
    if (!sf) {
      typeFertilisantHidden.value = "";
      return;
    }
    const mapping =
      (referentiels || {}).mapping_sous_fertilisant_vers_type || {};
    typeFertilisantHidden.value = mapping[sf] || "";

    // Application des flags de pre-remplissage du sous-fertilisant choisi.
    const sousFerts = (referentiels || {}).sous_fertilisants || {};
    const flags = (sousFerts[sf] || {}).flags || {};
    if (effluentPeuChargeHidden && flags.effluent_peu_charge !== undefined) {
      effluentPeuChargeHidden.value = String(flags.effluent_peu_charge);
    }
    if (
      effluentPeuChargeElevageHidden &&
      flags.effluent_peu_charge_elevage !== undefined
    ) {
      effluentPeuChargeElevageHidden.value = String(
        flags.effluent_peu_charge_elevage
      );
    }
  }

  // ─── Initialisation et propagation ────────────────────────────────────

  function initialiser() {
    rendreCategoriesCultures();
    if (initial.categorie_culture) onChangeChamp("categorie_culture", false);
    // Etat initial du bouton : desactive tant que le parcours n'est pas
    // complet (au 1er chargement, seule categorie_culture est visible et non
    // repondue -> bouton disabled). En replay (params URL), si tout est deja
    // repondu, le bouton est actif.
    mettreAJourBoutonSubmit();
  }

  // `userDriven` distingue un click utilisateur (true) d'un replay au
  // chargement initial (false). En replay, on ne touche pas aux hidden
  // inputs (sinon on ecrase les valeurs deja resolues, ex apres une
  // question complementaire qui re-injecte des champs).
  function onChangeChamp(champSource, userDriven) {
    if (userDriven === undefined) userDriven = true;
    const idxSource = FIELDS.indexOf(champSource);

    // Reset des niveaux en aval
    for (let i = idxSource + 1; i < FIELDS.length; i++) {
      viderContainer(FIELDS[i]);
    }

    if (userDriven) {
      // L'user a touche en amont -> on reset les hidden inputs concernes.
      if (idxSource <= FIELDS.indexOf("sous_culture_form")) {
        resoudreOccupationSousCulture();
      }
      if (idxSource <= FIELDS.indexOf("sous_fertilisant")) {
        if (typeFertilisantHidden) typeFertilisantHidden.value = "";
        if (effluentPeuChargeHidden) effluentPeuChargeHidden.value = "";
        if (effluentPeuChargeElevageHidden)
          effluentPeuChargeElevageHidden.value = "";
      }
    }

    if (!currentValue(champSource)) return;

    const champSuivant = FIELDS[idxSource + 1];

    if (champSource === "categorie_culture") {
      const cat = currentValue("categorie_culture");
      if (cat === "sol_non_cultive") {
        // Pas de niveau 2 sous-categorie. Direct au fertilisant.
        viderContainer("sous_culture_form");
        resoudreOccupationSousCulture();
        rendreCategoriesFertilisant();
        if (
          initial.categorie_fertilisant &&
          currentValue("categorie_fertilisant")
        ) {
          onChangeChamp("categorie_fertilisant", false);
        }
        return;
      }
      rendreSousCulturesForm();
      if (initial.sous_culture_form && currentValue("sous_culture_form")) {
        onChangeChamp("sous_culture_form", false);
      }
      return;
    }

    if (champSource === "sous_culture_form") {
      resoudreOccupationSousCulture();
      rendreCategoriesFertilisant();
      if (
        initial.categorie_fertilisant &&
        currentValue("categorie_fertilisant")
      ) {
        onChangeChamp("categorie_fertilisant", false);
      }
      return;
    }

    if (champSource === "categorie_fertilisant") {
      rendreSousFertilisantPourCategorie();
      if (initial.sous_fertilisant && currentValue("sous_fertilisant")) {
        onChangeChamp("sous_fertilisant", false);
      }
      return;
    }

    if (champSource === "sous_fertilisant") {
      resoudreTypeFertilisant();
      return;
    }

    void champSuivant;  // suppress unused warning
  }
})();
