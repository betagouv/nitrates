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

  function viderContainer(champ) {
    const c = containers[champ];
    if (!c) return;
    c.innerHTML = "";
    c.hidden = true;
    cacherWrapper(champ);
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
    input.addEventListener("change", () => onChangeChamp(champ));
    const label = document.createElement("label");
    label.className = "fr-label";
    label.htmlFor = id;
    label.textContent = libelle || valeur;
    wrapper.appendChild(input);
    wrapper.appendChild(label);
    container.appendChild(wrapper);
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
