// Cascade des selects du formulaire /simulateur/.
//
// Les selects (occupation_sol -> sous_culture -> type_fertilisant ->
// sous_fertilisant) se peuplent dynamiquement en suivant la structure de
// l'arbre PAN charge via /api/arbre/. Avantage : on n'a aucun mapping
// hardcode cote front, c'est l'arbre qui dit quels choix sont possibles
// a chaque etape.
//
// Le sous_fertilisant n'est pas une question de l'arbre PAN (l'arbre
// s'arrete au type_fertilisant). On le peuple depuis referentiels.json
// (cle `sous_fertilisants`) en filtrant par le type choisi via
// `mapping_sous_fertilisant_vers_type`. C'est purement informatif pour
// l'instant ; le serveur ne s'en sert pas dans le parcours.

(function () {
  "use strict";

  const FIELDS = [
    "occupation_sol",
    "sous_culture",
    "type_fertilisant",
    "sous_fertilisant",
  ];

  const selects = {};
  for (const champ of FIELDS) {
    selects[champ] = document.getElementById(`id_${champ}`);
  }
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
    if (valeurInitiale && [...select.options].some((o) => o.value === valeurInitiale)) {
      select.value = valeurInitiale;
    }
  }

  function viderSelect(select, placeholder) {
    select.innerHTML = `<option value="">${placeholder}</option>`;
    select.value = "";
    select.disabled = true;
  }

  function peuplerSousFertilisant() {
    const select = selects.sous_fertilisant;
    if (!select) return;
    const typeFert = selects.type_fertilisant.value;
    if (!typeFert) {
      viderSelect(select, "— Choisir le type de fertilisant d'abord —");
      return;
    }
    const mapping = (referentiels || {}).mapping_sous_fertilisant_vers_type || {};
    const sousFerts = (referentiels || {}).sous_fertilisants || {};
    // Filtre les sous-fertilisants dont le mapping pointe vers le type choisi.
    const candidats = Object.keys(sousFerts).filter(
      (sf) => mapping[sf] === typeFert
    );

    select.innerHTML = '<option value="">— Aucun (optionnel) —</option>';
    for (const sf of candidats) {
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

  // ─── Initialisation et propagation des changes ────────────────────────

  function initialiser() {
    // Niveau 1 : peuple occupation_sol et propage en aval si valeur
    // initiale presente.
    peuplerOccupationSol();
    propagerDepuis("occupation_sol");

    selects.occupation_sol.addEventListener("change", () => {
      propagerDepuis("occupation_sol");
    });
    selects.sous_culture.addEventListener("change", () => {
      propagerDepuis("sous_culture");
    });
    selects.type_fertilisant.addEventListener("change", () => {
      propagerDepuis("type_fertilisant");
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

  // Propage le changement d'un select donne vers tous les selects en aval.
  // On NE re-peuple PAS le select source : il vient juste d'etre modifie
  // par l'utilisateur.
  function propagerDepuis(champSource) {
    const order = ["occupation_sol", "sous_culture", "type_fertilisant", "sous_fertilisant"];
    const idxSource = order.indexOf(champSource);

    // 1) Reset des selects en aval
    for (let i = idxSource + 1; i < order.length; i++) {
      const champ = order[i];
      viderSelect(selects[champ], placeholderPour(champ));
    }

    if (!selects[champSource].value) return;

    // 2) Peuple le 1er select en aval (champSource + 1).
    const champSuivant = order[idxSource + 1];
    if (!champSuivant) return;

    if (champSuivant === "sous_fertilisant") {
      peuplerSousFertilisant();
      return;
    }

    const noeudSuivant = noeudFormulairePourChamp(
      arbre.arbre.noeud,
      champSuivant
    );
    if (!noeudSuivant) {
      // Pas de noeud formulaire pour ce champ sous le chemin actuel
      // (ex: sol_non_cultive court-circuite -> pas de sous_culture).
      viderSelect(selects[champSuivant], "— Non applicable —");
      for (let i = idxSource + 2; i < order.length; i++) {
        viderSelect(selects[order[i]], "— Non applicable —");
      }
      return;
    }

    peuplerSelectDepuisNoeud(
      selects[champSuivant],
      noeudSuivant,
      initial[champSuivant]
    );

    // Si un initial[champSuivant] a ete applique (form pre-rempli depuis
    // l'URL), on continue la propagation pour peupler les niveaux d'apres.
    if (selects[champSuivant].value) {
      propagerDepuis(champSuivant);
    }
  }

  function placeholderPour(champ) {
    switch (champ) {
      case "sous_culture":
        return "— Choisir l'occupation d'abord —";
      case "type_fertilisant":
        return "— Choisir la culture d'abord —";
      case "sous_fertilisant":
        return "— Choisir le type de fertilisant d'abord —";
      default:
        return "— Choisir —";
    }
  }
})();
