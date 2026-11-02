// Soumission du simulateur sans rechargement de page (#273, #643).
//
// Avant : chaque « Lancer la simulation » / « Suivant » rechargeait toute la
// page (GET). Le navigateur repartait en haut, puis scroll_resultat.js
// redescendait vers les questions complementaires : la page « sautait ».
//
// Maintenant : htmx envoie la MEME requete GET (hx-get sur le form, memes
// parametres), le serveur rend la meme page complete, et on n'en reprend que ce
// qui change :
//   - #zone-recap          encart recap des choix (page resultat) ;
//   - #zone-qc             questions complementaires + hidden passthrough ;
//   - .result-col          colonne resultat (pas d'enveloppe : les gouttieres
//                          DSFR visent les enfants directs de la grille) ;
//   - #zone-fin-simulation declencheur de l'encart d'avis (#518) ;
//   - les attributs d'etat (form, grille, colonne, bouton, barre de
//     progression) et window.NITRATES_CATALOG (bloc JSON).
// La carte Leaflet et les reponses deja saisies (culture, fertilisant) restent
// en place. Les modules concernes se rebranchent sur l'evenement
// `nitrates:rendu-remplace` (detail : { resultat, qcEnAttente, url }).
//
// Historique : htmx a historyEnabled=false (sa restauration par instantane du
// DOM rendrait une carte Leaflet morte). On pousse l'URL nous-memes ; revenir
// sur une etape precedente recharge cette URL, comme avant.
//
// Repli : toute reponse inattendue (erreur serveur ou reseau, redirection vers
// une autre page, page sans formulaire) -> soumission classique du formulaire,
// c'est-a-dire exactement l'ancien comportement.

(function () {
  "use strict";

  const _isNode =
    typeof module !== "undefined" &&
    module.exports &&
    typeof document === "undefined";

  // ─── Logique PURE (testable en Node) ────────────────────────────────────

  // Que faire d'un element present avant et/ou apres la soumission ?
  function actionSynchro(existeAvant, existeApres) {
    if (existeApres) return existeAvant ? "remplacer" : "ajouter";
    return existeAvant ? "retirer" : null;
  }

  // La reponse vient-elle bien de la page demandee ? Une requete redirigee (ex.
  // session expiree -> page de connexion) arrive sur un autre chemin : on ne
  // doit pas y chercher nos zones.
  function memePage(urlDemandee, urlReponse, origine) {
    if (!urlDemandee || !urlReponse) return false;
    try {
      const a = new URL(urlDemandee, origine);
      const b = new URL(urlReponse, origine);
      return a.origin === b.origin && a.pathname === b.pathname;
    } catch (e) {
      return false;
    }
  }

  if (_isNode) {
    module.exports = { actionSynchro, memePage };
    return;
  }

  const form = document.getElementById("form-simulateur");
  if (!form || !form.hasAttribute("hx-get")) return;

  // ─── Barre de chargement (meme principe que la localisation, #154) ──────

  const chargement = document.getElementById("nitrates-soumission-chargement");
  const remplissage = chargement
    ? chargement.querySelector(".nitrates-loc-loading__fill")
    : null;
  let minuterie = null;

  function demarrerChargement() {
    if (!chargement || !remplissage) return;
    clearInterval(minuterie);
    chargement.hidden = false;
    let pct = 0;
    remplissage.style.width = "0%";
    // Montee asymptotique vers 90 % : rapide au debut, puis ralentit, sans
    // jamais pretendre avoir fini avant la reponse.
    minuterie = setInterval(function () {
      pct += (90 - pct) * 0.12;
      remplissage.style.width = pct.toFixed(1) + "%";
    }, 120);
  }

  function terminerChargement() {
    if (!chargement || !remplissage) return;
    clearInterval(minuterie);
    remplissage.style.width = "100%";
    setTimeout(function () {
      chargement.hidden = true;
      remplissage.style.width = "0%";
    }, 300);
  }

  // ─── Historique ─────────────────────────────────────────────────────────
  //
  // Chaque rendu porte un identifiant dans history.state. Au retour / a
  // l'avance du navigateur, si l'entree visee correspond a un autre rendu que
  // celui affiche, on recharge sa page. Les entrees sans identifiant (ancres
  // internes, ex. liens d'evitement) ne declenchent rien.
  const CLE_RENDU = "nitratesRendu";

  function nouvelIdRendu() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  }

  let renduAffiche = (history.state && history.state[CLE_RENDU]) || nouvelIdRendu();
  try {
    history.replaceState(
      Object.assign({}, history.state, { [CLE_RENDU]: renduAffiche }),
      ""
    );
  } catch (e) {
    /* historique indisponible : le retour arriere restera natif */
  }

  window.addEventListener("popstate", function (e) {
    const rendu = e.state && e.state[CLE_RENDU];
    if (!rendu || rendu === renduAffiche) return;
    window.location.reload();
  });

  function pousserUrl(url) {
    renduAffiche = nouvelIdRendu();
    try {
      history.pushState({ [CLE_RENDU]: renduAffiche }, "", url);
    } catch (e) {
      /* no-op */
    }
  }

  // ─── Application du rendu serveur ───────────────────────────────────────

  // Remplace / ajoute / retire `selecteur` d'apres le document recu. `parent`
  // et `avant` disent ou l'ajouter quand il n'existait pas encore.
  function synchroniser(doc, selecteur, parent, avant) {
    const ancien = document.querySelector(selecteur);
    const nouveau = doc.querySelector(selecteur);
    const action = actionSynchro(!!ancien, !!nouveau);
    if (action === "remplacer") {
      ancien.replaceWith(document.adoptNode(nouveau));
    } else if (action === "ajouter" && parent) {
      parent.insertBefore(document.adoptNode(nouveau), avant || null);
    } else if (action === "retirer") {
      ancien.remove();
    }
    return document.querySelector(selecteur);
  }

  function copierAttribut(source, cible, nom) {
    if (!source || !cible) return;
    if (source.hasAttribute(nom)) cible.setAttribute(nom, source.getAttribute(nom));
    else cible.removeAttribute(nom);
  }

  function appliquerRendu(doc) {
    const nouveauForm = doc.getElementById("form-simulateur");
    const nouvelleGrille = doc.querySelector(".results-row");
    const grille = document.querySelector(".results-row");
    const formCol = document.querySelector(".form-col");
    const nouvelleFormCol = doc.querySelector(".form-col");
    if (
      !nouveauForm ||
      !nouvelleGrille ||
      !grille ||
      !formCol ||
      !nouvelleFormCol ||
      !doc.getElementById("zone-qc") ||
      !document.getElementById("zone-qc")
    ) {
      return null;
    }

    const resultat = nouveauForm.hasAttribute("data-resultat-affiche");
    const qcEnAttente = !!doc.querySelector("#qc-bloc[data-qc-en-attente]");

    // 1. Etat du formulaire.
    copierAttribut(nouveauForm, form, "data-resultat-affiche");
    const formApres = document.getElementById("form-after-localisation");
    const nouveauFormApres = doc.getElementById("form-after-localisation");
    copierAttribut(nouveauFormApres, formApres, "data-recap-actif");
    if (formApres && nouveauFormApres) formApres.hidden = nouveauFormApres.hidden;

    // 2. Hidden passthrough : ceux du rendu precedent (dans #zone-qc) et ceux
    //    rajoutes par reset_form.js (a la racine du form, sans id) sont
    //    remplaces par ceux du nouveau rendu, qui decrivent l'etat a renvoyer.
    form.querySelectorAll('input[type="hidden"]:not([id])').forEach(function (i) {
      i.remove();
    });

    // 3. Zones remplacees en bloc.
    synchroniser(doc, "#zone-recap");
    synchroniser(doc, "#zone-qc");
    synchroniser(doc, "#zone-fin-simulation");

    // 4. Bouton de soumission : on garde l'element (cascade.js le memorise),
    //    on reprend son libelle et sa visibilite.
    const ligneBouton = document.getElementById("form-submit-row");
    const nouvelleLigneBouton = doc.getElementById("form-submit-row");
    if (ligneBouton && nouvelleLigneBouton) {
      ligneBouton.hidden = nouvelleLigneBouton.hidden;
      const bouton = ligneBouton.querySelector('button[type="submit"]');
      const nouveauBouton = nouvelleLigneBouton.querySelector(
        'button[type="submit"]'
      );
      if (bouton && nouveauBouton) bouton.textContent = nouveauBouton.textContent;
    }

    // 5. Barre de progression : masquee sur le resultat final.
    const barre = document.getElementById("nitrates-progress-bar");
    const nouvelleBarre = doc.getElementById("nitrates-progress-bar");
    if (barre && nouvelleBarre) barre.hidden = nouvelleBarre.hidden;

    // 6. Mise en page puis colonne resultat. La grille passe en split AVANT
    //    d'inserer la colonne : elle arrive directement a sa taille finale (pas
    //    de transition d'entree), sinon les calendriers, qui mesurent leur
    //    largeur au rendu, se caleraient sur une colonne en cours d'ouverture.
    //    La colonne formulaire, elle, garde sa transition de largeur (#271).
    grille.classList.toggle(
      "layout--split",
      nouvelleGrille.classList.contains("layout--split")
    );
    formCol.classList.toggle(
      "fr-col-lg-4",
      nouvelleFormCol.classList.contains("fr-col-lg-4")
    );
    synchroniser(doc, ".result-col", grille, null);

    // 7. Catalog de la parcelle.
    const catalog = doc.getElementById("nitrates-catalog-data");
    if (catalog) {
      try {
        window.NITRATES_CATALOG = JSON.parse(catalog.textContent);
      } catch (e) {
        /* on garde le precedent */
      }
    }

    return { resultat: resultat && !qcEnAttente, qcEnAttente: qcEnAttente };
  }

  // ─── Cycle de la requete htmx ───────────────────────────────────────────

  let xhrCourant = null;
  let urlCourante = null;
  let rendu = false;

  function urlDepuisDetail(detail) {
    const chemin = detail && detail.pathInfo && detail.pathInfo.finalRequestPath;
    if (chemin) return chemin;
    const params = new URLSearchParams(new FormData(form)).toString();
    return form.getAttribute("hx-get") + (params ? "?" + params : "");
  }

  function replier() {
    // Soumission native : n'emet pas d'evenement submit, donc htmx ne
    // l'intercepte pas. Meme requete que celle qui vient d'echouer.
    HTMLFormElement.prototype.submit.call(form);
  }

  // hx-sync="this:replace" : une nouvelle soumission annule la precedente.
  // htmx emet htmx:abort puis, de facon synchrone, htmx:afterRequest pour la
  // requete annulee : on l'oublie d'abord pour ne pas la prendre pour un echec.
  form.addEventListener("htmx:abort", function () {
    xhrCourant = null;
  });

  form.addEventListener("htmx:beforeRequest", function (e) {
    xhrCourant = e.detail.xhr;
    urlCourante = urlDepuisDetail(e.detail);
    rendu = false;
    form.setAttribute("aria-busy", "true");
    demarrerChargement();
  });

  form.addEventListener("htmx:beforeSwap", function (e) {
    // Le remplacement est fait ici, pas par htmx (cf. en-tete).
    e.detail.shouldSwap = false;
    const xhr = e.detail.xhr;
    if (xhr !== xhrCourant || !xhr || xhr.status !== 200) return;
    if (!memePage(urlCourante, xhr.responseURL, window.location.origin)) return;

    let doc;
    try {
      doc = new DOMParser().parseFromString(xhr.responseText, "text/html");
    } catch (err) {
      return;
    }
    const etat = appliquerRendu(doc);
    if (!etat) return;
    rendu = true;

    const urlPrecedente = window.location.href;
    pousserUrl(urlCourante);
    document.dispatchEvent(
      new CustomEvent("nitrates:rendu-remplace", {
        detail: {
          resultat: etat.resultat,
          qcEnAttente: etat.qcEnAttente,
          url: window.location.href,
          urlPrecedente: urlPrecedente,
        },
      })
    );
    // Recalcul de l'etat du bouton (cascade.js), de la barre de progression
    // et de l'encart recap, comme a l'apparition du formulaire.
    document.dispatchEvent(new CustomEvent("nitrates:form-revealed"));

    // Accessibilite : le bouton qui avait le focus disparait avec le resultat
    // final -> on le donne au titre du resultat (les QC, elles, recoivent le
    // focus de subsidiaires_cascade.js). Sans defilement : scroll_resultat.js
    // cadre la vue.
    if (etat.resultat) {
      const titre = document.querySelector(".result-col h2");
      if (titre) {
        titre.setAttribute("tabindex", "-1");
        titre.focus({ preventScroll: true });
      }
    }
  });

  form.addEventListener("htmx:afterRequest", function (e) {
    if (e.detail.xhr !== xhrCourant) return; // requete remplacee (hx-sync)
    form.removeAttribute("aria-busy");
    terminerChargement();
    if (!rendu) replier();
  });
})();
