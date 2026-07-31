// #271 chantier 2 — Encart récap des choix (colonne gauche, page résultat).
//
// Sur la page résultat, on ne montre plus le formulaire complet à gauche mais un
// encart violet compact qui rappelle les choix de l'utilisateur, avec un bouton
// « Modifier ». Ce module :
//   1. masque le formulaire complet (#form-after-localisation) et affiche l'encart ;
//   2. remplit l'encart en LANGAGE HUMAIN depuis l'état courant du form (les
//      libellés déjà rendus : localisation, réponses du flow couvert/culture,
//      dates, fertilisant) — pas de re-dérivation serveur ;
//   3. câble « Modifier » : ré-affiche le formulaire, masque le résultat et
//      repasse en mode saisie (réutilise reset_form.js #135).
//
// Rien n'est fait hors page résultat (l'encart n'est rendu par le template que
// quand afficher_resultat est vrai).

(function () {
  "use strict";

  var encart = document.getElementById("recap-choix");
  if (!encart) return; // pas sur une page résultat

  var form = document.getElementById("form-simulateur");
  var formApres = document.getElementById("form-after-localisation");
  var liste = encart.querySelector("[data-recap-liste]");
  var btnModifier = encart.querySelector("[data-recap-modifier]");

  // ─── Helpers de lecture des libellés (état courant du form) ─────────────

  function texte(sel) {
    var el = document.querySelector(sel);
    var t = el ? (el.textContent || "").trim() : "";
    return t && t !== "—" ? t : "";
  }

  // Libellé humain du radio coché d'un groupe (name), depuis son <label>.
  function labelRadioCoche(name) {
    var r = document.querySelector(
      'input[type="radio"][name="' + name + '"]:checked'
    );
    if (!r) return "";
    var lab = document.querySelector('label[for="' + r.id + '"]');
    return lab ? (lab.textContent || "").trim() : "";
  }

  function valeurChamp(id) {
    var el = document.getElementById(id);
    return el ? (el.value || "").trim() : "";
  }

  // ─── Construction du récap ──────────────────────────────────────────────

  function ligne(label, valeur) {
    return { label: label, valeur: valeur };
  }

  function construireLignes() {
    var lignes = [];

    // Localisation : commune - région (sans le numéro de région, que personne ne
    // connaît). Ex « Reims - Grand Est ». Le département (numéro) n'est pas repris
    // ici : c'est la région en toutes lettres qui parle à l'utilisateur.
    var commune = texte("#commune-display");
    var region = texte("#region-display").replace(/\s*\(\d+\)\s*$/, "").trim();
    if (commune) {
      lignes.push(ligne("Localisation", commune + (region ? " - " + region : "")));
    }

    // Culture ou couvert : on résume via les réponses du flow (#272).
    var destination = labelRadioCoche("cflow_destination"); // couvert / culture principale
    var typeCouvert = labelRadioCoche("cflow_type_couvert"); // interculture longue/courte OU catégorie culture
    var recolte = labelRadioCoche("cflow_couvert_recolte"); // récolté / non
    var sousCulture = labelRadioCoche("cflow_sous_culture"); // précision culture

    if (destination) {
      // Ligne « Culture ou couvert » : le type est le plus parlant.
      var cultureVal = typeCouvert || destination;
      lignes.push(ligne("Culture ou couvert", cultureVal));
      if (recolte) lignes.push(ligne("Couvert", recolte));
      if (sousCulture) lignes.push(ligne("Type de culture", sousCulture));
    }

    // Dates couvert (si renseignées).
    var semis = valeurChamp("id_date_semis_couvert");
    var destruction = valeurChamp("id_date_destruction_couvert");
    if (semis || destruction) {
      var d = [];
      if (semis) d.push("semis " + semis);
      if (destruction) d.push("destruction " + destruction);
      lignes.push(ligne("Dates du couvert", d.join(" · ")));
    }

    // Fertilisant : catégorie + précision.
    var catFert = labelRadioCoche("categorie_fertilisant");
    var sousFert = labelRadioCoche("sous_fertilisant");
    if (catFert || sousFert) {
      lignes.push(ligne("Fertilisant", sousFert || catFert));
    }

    return lignes;
  }

  function rendre() {
    var lignes = construireLignes();
    liste.innerHTML = "";
    lignes.forEach(function (l) {
      var item = document.createElement("div");
      item.className = "recap-choix__item";
      var lab = document.createElement("span");
      lab.className = "recap-choix__label";
      lab.textContent = l.label;
      var val = document.createElement("span");
      val.className = "recap-choix__valeur";
      val.textContent = l.valeur;
      item.appendChild(lab);
      item.appendChild(val);
      liste.appendChild(item);
    });
  }

  // ─── Bascule récap <-> formulaire ───────────────────────────────────────

  // Affiche le récap et masque le formulaire complet (état page résultat).
  function afficherRecap() {
    if (formApres) formApres.hidden = true;
    encart.hidden = false;
    rendre();
  }

  // « Modifier » : ré-affiche le formulaire, masque l'encart, et invalide le
  // résultat (retour en mode saisie). On délègue l'invalidation du résultat à
  // reset_form.js : on retire l'attribut data-resultat-affiche, on enlève la
  // colonne résultat et on repasse la grille en colonne unique, puis on notifie.
  function modifier() {
    encart.hidden = true;
    if (formApres) formApres.hidden = false;

    // Retire le résultat affiché (colonne droite + split) et repasse en saisie.
    if (form) form.removeAttribute("data-resultat-affiche");
    var resultCol = document.querySelector(".result-col");
    if (resultCol) resultCol.remove();
    var row = document.querySelector(".results-row");
    if (row) row.classList.remove("layout--split");
    // La colonne form reprend toute la largeur (on retire la contrainte 1/4).
    var formCol = document.querySelector(".form-col");
    if (formCol) formCol.classList.remove("fr-col-lg-3");
    // Le bouton « Lancer la simulation » doit redevenir visible pour relancer.
    var submitRow = document.getElementById("form-submit-row");
    if (submitRow) submitRow.hidden = false;

    // Notifie les autres modules (reset_form / flow) qu'on repasse en saisie.
    document.dispatchEvent(new Event("nitrates:retour-saisie"));

    // Recadre sur le formulaire (la première question).
    var cible = document.getElementById("section-culture") || formApres;
    if (cible && cible.scrollIntoView) {
      cible.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  if (btnModifier) btnModifier.addEventListener("click", modifier);

  // Au chargement de la page résultat : masque le form, montre le récap.
  // Les libellés (radios du flow + cascade fertilisant) sont rejoués de façon
  // ASYNCHRONE (fetch référentiels puis rendu) -> on rend une première fois tout
  // de suite (masque le form), puis on re-rend quand le flow signale qu'il a fini
  // (nitrates:form-revealed) et via quelques essais différés en filet.
  afficherRecap();
  document.addEventListener("nitrates:form-revealed", rendre);
  [150, 400, 900].forEach(function (ms) {
    setTimeout(rendre, ms);
  });
})();
