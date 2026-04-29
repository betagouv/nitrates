// Cascade des selects du formulaire /simulateur/.
//
// Ordre de cascade UX :
//   1. occupation_sol     -> depuis l'arbre PAN (q_occupation_sol)
//   2. sous_culture       -> depuis l'arbre PAN (q_culture_principale_type, etc.)
//   3. categorie_fertilisant -> depuis referentiels.categories_fertilisants
//   4. sous_fertilisant   -> depuis categories_fertilisants[X].sous_fertilisants
//   5. type_fertilisant   -> RESOLU via mapping_sous_fertilisant_vers_type
//                            stocke dans un input hidden, envoye au serveur
//
// Le serveur consomme `type_fertilisant` directement (compatible avec
// l'arbre actuel) ; `categorie_fertilisant` et `sous_fertilisant` sont
// envoyes en plus pour la tracabilite (URL partageable, debug juriste).

(function () {
  "use strict";

  // Champs visibles dans le formulaire (selects)
  const VISIBLE_FIELDS = [
    "occupation_sol",
    "sous_culture",
    "categorie_fertilisant",
    "sous_fertilisant",
  ];

  const selects = {};
  for (const champ of VISIBLE_FIELDS) {
    selects[champ] = document.getElementById(`id_${champ}`);
  }
  // Champ cache resolu cote front
  const typeFertilisantHidden = document.getElementById("id_type_fertilisant");

  if (!selects.occupation_sol) return;

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
      valeurChoisie = selects[racine.champ] ? selects[racine.champ].value : "";
    }
    if (valeurChoisie === "" || valeurChoisie === undefined) return null;

    const branche = (racine.branches || []).find(
      (b) => String(b.valeur) === String(valeurChoisie)
    );
    if (!branche || !branche.noeud) return null;
    return noeudFormulairePourChamp(branche.noeud, champ);
  }

  // ─── Peuplement des selects ────────────────────────────────────────────

  function libelleChoix(choix) {
    if (choix.libelle) return `${choix.libelle} (${choix.valeur})`;
    return choix.valeur;
  }

  function peuplerSelectDepuisNoeud(select, noeud, valeurInitiale) {
    select.innerHTML = '<option value="">— Choisir —</option>';
    for (const branche of noeud.branches || []) {
      const opt = document.createElement("option");
      opt.value = branche.valeur;
      opt.textContent = libelleChoix({
        valeur: branche.valeur,
        libelle: branche.libelle,
      });
      select.appendChild(opt);
    }
    select.disabled = false;
    if (
      valeurInitiale &&
      [...select.options].some((o) => o.value === valeurInitiale)
    ) {
      select.value = valeurInitiale;
    }
  }

  function viderSelect(select, placeholder) {
    select.innerHTML = `<option value="">${placeholder}</option>`;
    select.value = "";
    select.disabled = true;
  }

  function peuplerCategoriesFertilisant() {
    const select = selects.categorie_fertilisant;
    if (!select) return;
    const categories = (referentiels || {}).categories_fertilisants || {};
    select.innerHTML = '<option value="">— Choisir —</option>';
    for (const [cle, meta] of Object.entries(categories)) {
      const opt = document.createElement("option");
      opt.value = cle;
      opt.textContent = meta.libelle_public || cle;
      select.appendChild(opt);
    }
    select.disabled = false;
    if (
      initial.categorie_fertilisant &&
      [...select.options].some((o) => o.value === initial.categorie_fertilisant)
    ) {
      select.value = initial.categorie_fertilisant;
    }
  }

  function peuplerSousFertilisantPourCategorie() {
    const select = selects.sous_fertilisant;
    if (!select) return;
    const categorie = selects.categorie_fertilisant.value;
    if (!categorie) {
      viderSelect(select, "— Choisir la categorie d'abord —");
      return;
    }
    const categories = (referentiels || {}).categories_fertilisants || {};
    const sousFerts = (referentiels || {}).sous_fertilisants || {};
    const cles = (categories[categorie] || {}).sous_fertilisants || [];

    select.innerHTML = '<option value="">— Choisir —</option>';
    for (const sf of cles) {
      const meta = sousFerts[sf] || {};
      const opt = document.createElement("option");
      opt.value = sf;
      opt.textContent = meta.libelle_public || sf;
      select.appendChild(opt);
    }
    select.disabled = false;
    if (
      initial.sous_fertilisant &&
      [...select.options].some((o) => o.value === initial.sous_fertilisant)
    ) {
      select.value = initial.sous_fertilisant;
    }
  }

  function resoudreTypeFertilisant() {
    if (!typeFertilisantHidden) return;
    const sf = selects.sous_fertilisant.value;
    if (!sf) {
      typeFertilisantHidden.value = "";
      return;
    }
    const mapping =
      (referentiels || {}).mapping_sous_fertilisant_vers_type || {};
    typeFertilisantHidden.value = mapping[sf] || "";
  }

  // ─── Initialisation et propagation des changes ────────────────────────

  function initialiser() {
    // Niveau 1 : peuple occupation_sol depuis l'arbre.
    peuplerOccupationSol();
    propagerDepuis("occupation_sol");

    selects.occupation_sol.addEventListener("change", () => {
      propagerDepuis("occupation_sol");
    });
    selects.sous_culture.addEventListener("change", () => {
      propagerDepuis("sous_culture");
    });
    selects.categorie_fertilisant.addEventListener("change", () => {
      propagerDepuis("categorie_fertilisant");
    });
    selects.sous_fertilisant.addEventListener("change", () => {
      propagerDepuis("sous_fertilisant");
    });
  }

  function peuplerOccupationSol() {
    const noeud = noeudFormulairePourChamp(arbre.arbre.noeud, "occupation_sol");
    if (noeud) {
      peuplerSelectDepuisNoeud(
        selects.occupation_sol,
        noeud,
        initial.occupation_sol
      );
    }
  }

  function propagerDepuis(champSource) {
    const order = VISIBLE_FIELDS;
    const idxSource = order.indexOf(champSource);

    // Reset des selects en aval
    for (let i = idxSource + 1; i < order.length; i++) {
      viderSelect(selects[order[i]], placeholderPour(order[i]));
    }
    // Reset systematique du hidden type_fertilisant si en aval de la source
    if (idxSource < order.indexOf("sous_fertilisant")) {
      if (typeFertilisantHidden) typeFertilisantHidden.value = "";
    }

    if (!selects[champSource].value) return;

    // Peuple le select suivant selon la nature du champ source
    const champSuivant = order[idxSource + 1];

    if (champSuivant === "sous_culture") {
      const noeud = noeudFormulairePourChamp(arbre.arbre.noeud, "sous_culture");
      if (noeud) {
        peuplerSelectDepuisNoeud(
          selects.sous_culture,
          noeud,
          initial.sous_culture
        );
        if (selects.sous_culture.value) propagerDepuis("sous_culture");
      } else {
        // Branche court-circuit (ex: sol_non_cultive) -> pas de sous_culture
        // mais on peut quand meme proposer le fertilisant pour les chemins
        // qui en demandent.
        viderSelect(selects.sous_culture, "— Non applicable —");
        peuplerCategoriesFertilisant();
        if (selects.categorie_fertilisant.value) {
          propagerDepuis("categorie_fertilisant");
        }
      }
      return;
    }

    if (champSuivant === "categorie_fertilisant") {
      peuplerCategoriesFertilisant();
      if (selects.categorie_fertilisant.value) {
        propagerDepuis("categorie_fertilisant");
      }
      return;
    }

    if (champSuivant === "sous_fertilisant") {
      peuplerSousFertilisantPourCategorie();
      if (selects.sous_fertilisant.value) {
        propagerDepuis("sous_fertilisant");
      }
      return;
    }

    if (champSource === "sous_fertilisant") {
      // Plus de select en aval, mais on resout type_fertilisant.
      resoudreTypeFertilisant();
      return;
    }
  }

  function placeholderPour(champ) {
    switch (champ) {
      case "sous_culture":
        return "— Choisir l'occupation d'abord —";
      case "categorie_fertilisant":
        return "— Choisir la culture d'abord —";
      case "sous_fertilisant":
        return "— Choisir la categorie de fertilisant d'abord —";
      default:
        return "— Choisir —";
    }
  }
})();
