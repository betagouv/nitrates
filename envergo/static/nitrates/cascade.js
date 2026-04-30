// Cascade en RADIO BUTTONS DSFR du formulaire /simulateur/.
//
// Ordre de cascade UX :
//   1. occupation_sol     -> depuis l'arbre PAN (q_occupation_sol)
//   2. sous_culture       -> depuis l'arbre PAN (q_culture_principale_type, etc.)
//   3. categorie_fertilisant -> depuis referentiels.categories_fertilisants
//   4. sous_fertilisant   -> depuis categories_fertilisants[X].sous_fertilisants
//   5. type_fertilisant   -> RESOLU via mapping_sous_fertilisant_vers_type
//                            stocke dans un input hidden, envoye au serveur
//
// Chaque niveau a un conteneur `<div data-cascade="<champ>">` que ce JS
// remplit avec les `fr-radio-group` correspondants. Les niveaux suivants
// sont caches tant que le parent n'est pas selectionne.

(function () {
  "use strict";

  const FIELDS = [
    "occupation_sol",
    "sous_culture",
    "categorie_fertilisant",
    "sous_fertilisant",
  ];

  const containers = {};
  for (const champ of FIELDS) {
    containers[champ] = document.querySelector(`[data-cascade="${champ}"]`);
  }
  if (!containers.occupation_sol) return;

  const typeFertilisantHidden = document.getElementById("id_type_fertilisant");
  const initial = window.NITRATES_INITIAL_DATA || {};

  let arbre = null;
  let referentiels = null;

  Promise.all([
    fetch(window.NITRATES_ARBRE_URL).then((r) => r.json()),
    fetch(window.NITRATES_REFERENTIELS_URL).then((r) => r.json()),
  ])
    .then(([a, r]) => {
      arbre = a;
      referentiels = r;
      initialiser();
    })
    .catch((err) => {
      console.error("Cascade : echec du chargement arbre/referentiels", err);
    });

  // ─── Helpers de descente dans l'arbre ─────────────────────────────────

  function noeudFormulairePourChamp(racine, champ) {
    if (!racine) return null;
    if (racine.type_noeud === "formulaire" && racine.champ === champ) {
      return racine;
    }
    let valeurChoisie;
    if (racine.type_noeud === "catalogue" && racine.id === "n_zvn") {
      valeurChoisie = true;
    } else {
      valeurChoisie = currentValue(racine.champ);
    }
    if (valeurChoisie === "" || valeurChoisie === undefined) return null;
    const branche = (racine.branches || []).find(
      (b) => String(b.valeur) === String(valeurChoisie)
    );
    if (!branche || !branche.noeud) return null;
    return noeudFormulairePourChamp(branche.noeud, champ);
  }

  function currentValue(champ) {
    if (!FIELDS.includes(champ)) return "";
    const checked = document.querySelector(
      `input[type="radio"][name="${champ}"]:checked`
    );
    return checked ? checked.value : "";
  }

  // ─── Rendu des radio groups ────────────────────────────────────────────

  function libelleChoix(choix) {
    if (choix.libelle) return choix.libelle;
    return choix.valeur;
  }

  function montrerWrapper(champ) {
    const wrapper = document.getElementById(`${champ}-wrapper`);
    if (wrapper) wrapper.hidden = false;
  }
  function cacherWrapper(champ) {
    const wrapper = document.getElementById(`${champ}-wrapper`);
    if (wrapper) wrapper.hidden = true;
  }

  function rendreRadiosDepuisNoeud(champ, noeud, valeurInitiale) {
    const container = containers[champ];
    container.innerHTML = "";
    container.hidden = false;
    montrerWrapper(champ);
    for (const branche of noeud.branches || []) {
      const id = `id_${champ}__${slug(branche.valeur)}`;
      const wrapper = document.createElement("div");
      wrapper.className = "fr-radio-group";
      const input = document.createElement("input");
      input.type = "radio";
      input.id = id;
      input.name = champ;
      input.value = String(branche.valeur);
      if (String(valeurInitiale) === String(branche.valeur)) {
        input.checked = true;
      }
      input.addEventListener("change", () => onChangeChamp(champ));
      const label = document.createElement("label");
      label.className = "fr-label";
      label.htmlFor = id;
      label.textContent = libelleChoix({
        valeur: branche.valeur,
        libelle: branche.libelle,
      });
      wrapper.appendChild(input);
      wrapper.appendChild(label);
      container.appendChild(wrapper);
    }
  }

  function rendreRadiosCategoriesFertilisant() {
    const container = containers.categorie_fertilisant;
    container.innerHTML = "";
    container.hidden = false;
    montrerWrapper("categorie_fertilisant");
    const cats = (referentiels || {}).categories_fertilisants || {};
    for (const [cle, meta] of Object.entries(cats)) {
      const id = `id_categorie_fertilisant__${slug(cle)}`;
      const wrapper = document.createElement("div");
      wrapper.className = "fr-radio-group";
      const input = document.createElement("input");
      input.type = "radio";
      input.id = id;
      input.name = "categorie_fertilisant";
      input.value = cle;
      if (initial.categorie_fertilisant === cle) input.checked = true;
      input.addEventListener("change", () => onChangeChamp("categorie_fertilisant"));
      const label = document.createElement("label");
      label.className = "fr-label";
      label.htmlFor = id;
      label.textContent = meta.libelle_public || cle;
      wrapper.appendChild(input);
      wrapper.appendChild(label);
      container.appendChild(wrapper);
    }
  }

  function rendreRadiosSousFertilisantPourCategorie() {
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
      const id = `id_sous_fertilisant__${slug(sf)}`;
      const wrapper = document.createElement("div");
      wrapper.className = "fr-radio-group";
      const input = document.createElement("input");
      input.type = "radio";
      input.id = id;
      input.name = "sous_fertilisant";
      input.value = sf;
      if (initial.sous_fertilisant === sf) input.checked = true;
      input.addEventListener("change", () => onChangeChamp("sous_fertilisant"));
      const label = document.createElement("label");
      label.className = "fr-label";
      label.htmlFor = id;
      label.textContent = meta.libelle_public || sf;
      wrapper.appendChild(input);
      wrapper.appendChild(label);
      container.appendChild(wrapper);
    }
  }

  function viderContainer(champ) {
    const c = containers[champ];
    c.innerHTML = "";
    c.hidden = true;
  }

  function resoudreTypeFertilisant() {
    if (!typeFertilisantHidden) return;
    const sf = currentValue("sous_fertilisant");
    if (!sf) {
      typeFertilisantHidden.value = "";
      return;
    }
    const mapping =
      (referentiels || {}).mapping_sous_fertilisant_vers_type || {};
    typeFertilisantHidden.value = mapping[sf] || "";
  }

  function slug(s) {
    return String(s)
      .replace(/[^a-zA-Z0-9_-]/g, "_")
      .toLowerCase();
  }

  // ─── Initialisation et propagation ────────────────────────────────────

  function initialiser() {
    // Niveau 1 : occupation_sol
    const noeud = noeudFormulairePourChamp(arbre.arbre.noeud, "occupation_sol");
    if (noeud) {
      rendreRadiosDepuisNoeud(
        "occupation_sol",
        noeud,
        initial.occupation_sol
      );
    }
    // Si occupation_sol est deja choisi (initial), on propage en aval
    // (mode init replay, on ne reset pas le hidden type_fertilisant).
    if (initial.occupation_sol) onChangeChamp("occupation_sol", false);
  }

  // `userDriven` distingue un click utilisateur (true) d'un replay au
  // chargement initial (false). En replay, on ne touche pas au hidden
  // type_fertilisant (sinon on ecrase les valeurs deja resolues lorsque
  // le serveur a re-render avec un type_fertilisant present, par ex.
  // une question complementaire qui re-injecte le type pour avancer
  // dans le parcours).
  function onChangeChamp(champSource, userDriven) {
    if (userDriven === undefined) userDriven = true;
    const order = FIELDS;
    const idxSource = order.indexOf(champSource);

    // Reset des niveaux en aval
    for (let i = idxSource + 1; i < order.length; i++) {
      viderContainer(order[i]);
    }
    // Reset hidden type_fertilisant si l'utilisateur a touche a quelque
    // chose en amont de sous_fertilisant. En init replay, on respecte
    // la valeur deja presente (peut venir de l'URL ou d'une QC).
    if (userDriven && idxSource < order.indexOf("sous_fertilisant")) {
      if (typeFertilisantHidden) typeFertilisantHidden.value = "";
    }

    if (!currentValue(champSource)) return;

    // Peupler le suivant
    const champSuivant = order[idxSource + 1];
    if (!champSuivant) {
      // Plus rien apres, on resout le type_fertilisant
      if (champSource === "sous_fertilisant") {
        resoudreTypeFertilisant();
      }
      return;
    }

    if (champSuivant === "sous_culture") {
      const noeud = noeudFormulairePourChamp(arbre.arbre.noeud, "sous_culture");
      if (noeud) {
        rendreRadiosDepuisNoeud("sous_culture", noeud, initial.sous_culture);
        if (initial.sous_culture && currentValue("sous_culture")) {
          onChangeChamp("sous_culture", false);
        }
      } else {
        // Pas de sous_culture (court-circuit) : passer direct au fertilisant
        rendreRadiosCategoriesFertilisant();
        if (initial.categorie_fertilisant && currentValue("categorie_fertilisant")) {
          onChangeChamp("categorie_fertilisant", false);
        }
      }
      return;
    }

    if (champSuivant === "categorie_fertilisant") {
      rendreRadiosCategoriesFertilisant();
      if (initial.categorie_fertilisant && currentValue("categorie_fertilisant")) {
        onChangeChamp("categorie_fertilisant", false);
      }
      return;
    }

    if (champSuivant === "sous_fertilisant") {
      rendreRadiosSousFertilisantPourCategorie();
      if (initial.sous_fertilisant && currentValue("sous_fertilisant")) {
        onChangeChamp("sous_fertilisant", false);
      }
      return;
    }
  }
})();
