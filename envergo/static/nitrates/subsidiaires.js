// Cascade des questions subsidiaires sur la page resultat.
//
// Le serveur a affiche la 1re question complementaire bloquante. Plutot
// que de faire un aller-retour a chaque reponse, on charge l'arbre cote
// client et on resout localement la cascade des subsidiaires : quand
// l'utilisateur repond, on regarde si on peut descendre encore, on
// affiche la prochaine question en dessous, et ainsi de suite jusqu'a
// atteindre une feuille (=> submit) ou un noeud catalogue interne (=>
// submit, le serveur resoudra via SIG).

(function () {
  "use strict";

  const form = document.querySelector(
    "form.subsidiaires-form, form[data-subsidiaires]"
  );
  if (!form) return;

  // Donnees actuelles deja en hidden inputs : on les lit pour amorcer
  // la descente cote client.
  const currentData = {};
  for (const input of form.querySelectorAll('input[type="hidden"]')) {
    if (input.name) currentData[input.name] = input.value;
  }
  // Les selects subsidiaires deja rendus par le serveur : on tient compte
  // de leur valeur si remplie.
  const initialSelects = form.querySelectorAll("select[data-subsidiaire]");

  // Conteneur ou injecter les questions suivantes
  const questionsContainer = form.querySelector(".subsidiaires-questions");
  if (!questionsContainer) return;

  let arbre = null;

  fetch(window.NITRATES_ARBRE_URL)
    .then((r) => r.json())
    .then((a) => {
      arbre = a;
      // Si la 1re question rendue par le serveur est deja repondue (cas
      // ou l'URL a un param), on descend. Sinon on reste sur place.
      attachListenersAuxSelectsExistants();
      tenterDescente();
    })
    .catch((err) => {
      console.error("Subsidiaires : echec du chargement arbre", err);
    });

  function attachListenersAuxSelectsExistants() {
    initialSelects.forEach((select) => {
      select.addEventListener("change", onChangeQuelqueQuestion);
    });
  }

  function onChangeQuelqueQuestion(e) {
    const select = e.target;
    if (select.value) {
      currentData[select.name] = select.value;
      // On retire les questions suivantes, elles seront re-render.
      retirerQuestionsApres(select);
      tenterDescente();
    } else {
      // Reset valeur : on supprime du contexte et on retire la suite.
      delete currentData[select.name];
      retirerQuestionsApres(select);
    }
  }

  function retirerQuestionsApres(select) {
    // Toutes les questions ajoutees dynamiquement apres le select donne
    // sont supprimees.
    const questionDiv = select.closest(".subsidiaire-question");
    if (!questionDiv) return;
    let next = questionDiv.nextElementSibling;
    while (next && next.classList.contains("subsidiaire-question")) {
      const nextNext = next.nextElementSibling;
      next.remove();
      next = nextNext;
    }
  }

  // ─── Descente dans l'arbre cote client ─────────────────────────────────

  function tenterDescente() {
    if (!arbre) return;
    const racine = arbre.arbre && arbre.arbre.noeud;
    if (!racine) return;
    descendre(racine);
  }

  function descendre(noeud) {
    if (!noeud) return;
    const champ = noeud.champ;
    const typeNoeud = noeud.type_noeud;

    // Cas special racine n_zvn (catalogue) : on suppose en_zone_vulnerable=true
    // (sinon on ne serait pas sur cette page resultat).
    let valeur;
    if (typeNoeud === "catalogue" && noeud.id === "n_zvn") {
      valeur = true;
    } else if (champ in currentData) {
      valeur = parseValeur(currentData[champ]);
    } else {
      // On bute sur cette question. Si c'est un formulaire, on l'affiche
      // (sauf si la 1re est deja affichee par le serveur).
      if (typeNoeud === "formulaire") {
        if (!questionDejaAffichee(champ)) {
          rendreQuestion(noeud);
        }
      } else if (typeNoeud === "catalogue") {
        // Catalogue interne sans valeur dans contexte : on submit, le
        // serveur resoudra.
        // (Cas rare en pratique : la moulinette resout les catalogues
        // racines, et les catalogues internes sont rares.)
        soumettreFormulaire();
      }
      return;
    }

    // On a la valeur, on descend la branche correspondante.
    const branche = trouverBranche(noeud, valeur);
    if (!branche) {
      // Soit valeur inconnue, soit fallback type_I a faire cote serveur.
      // On submit pour laisser le serveur gerer (incluant fallback).
      soumettreFormulaire();
      return;
    }
    if (branche.noeud) {
      descendre(branche.noeud);
    } else if (branche.regle || branche.renvoi_vers) {
      // Feuille atteinte ! On peut submit pour avoir le resultat affiche.
      soumettreFormulaire();
    }
  }

  function trouverBranche(noeud, valeur) {
    for (const b of noeud.branches || []) {
      if (valeursEgales(b.valeur, valeur)) return b;
    }
    // Fallback type_I
    if (
      noeud.champ === "type_fertilisant" &&
      (valeur === "type_Ia" || valeur === "type_Ib")
    ) {
      for (const b of noeud.branches || []) {
        if (b.valeur === "type_I") return b;
      }
    }
    return null;
  }

  function valeursEgales(brancheVal, val) {
    if (brancheVal === val) return true;
    // bool YAML <-> string contexte
    if (typeof brancheVal === "boolean" && typeof val === "string") {
      const norm = val.trim().toLowerCase();
      if (brancheVal === true && ["true", "oui", "1"].includes(norm)) return true;
      if (brancheVal === false && ["false", "non", "0"].includes(norm)) return true;
    }
    return false;
  }

  function parseValeur(s) {
    // Convertit "True"/"False" en bool pour les comparaisons. (Garde la
    // string sinon, valeurs YAML majoritairement strings.)
    if (s === "True" || s === "true") return true;
    if (s === "False" || s === "false") return false;
    return s;
  }

  function questionDejaAffichee(champ) {
    return form.querySelector(`select[name="${champ}"]`) !== null;
  }

  function rendreQuestion(noeud) {
    const wrapper = document.createElement("div");
    wrapper.className = "fr-fieldset__element subsidiaire-question";
    wrapper.innerHTML = `
      <div class="fr-select-group">
        <label class="fr-label" for="id_subsidiaire_${noeud.champ}">
          ${escapeHtml(noeud.texte || noeud.champ)}
          <span class="fr-hint-text">champ : ${escapeHtml(
            noeud.champ
          )} (niveau ${escapeHtml(noeud.niveau || "")})</span>
        </label>
        <select class="fr-select" name="${escapeAttr(
          noeud.champ
        )}" id="id_subsidiaire_${escapeAttr(noeud.champ)}" data-subsidiaire>
          <option value="">— Choisir —</option>
        </select>
      </div>
    `;
    const select = wrapper.querySelector("select");
    for (const branche of noeud.branches || []) {
      const opt = document.createElement("option");
      opt.value = String(branche.valeur);
      opt.textContent = branche.libelle
        ? `${branche.libelle} (${branche.valeur})`
        : String(branche.valeur);
      select.appendChild(opt);
    }
    select.addEventListener("change", onChangeQuelqueQuestion);
    questionsContainer.appendChild(wrapper);
  }

  function soumettreFormulaire() {
    // Pour ajouter au submit les valeurs choisies cote client qui ne sont
    // pas encore dans des inputs, on s'assure que tous les selects ont
    // bien leur name (ils l'ont, c'est bon). Le form se soumet avec les
    // selects + hidden inputs en GET, le serveur recoit tout.
    form.submit();
  }

  function escapeHtml(s) {
    return String(s).replace(
      /[&<>"']/g,
      (c) =>
        ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[
          c
        ])
    );
  }
  function escapeAttr(s) {
    return String(s).replace(/["'<>&]/g, "");
  }
})();
