// Reset / flush du formulaire au changement d'un champ apres resultat (#135).
//
// Contexte (cas A uniquement, cf. PLAN_135_reset_form.md) :
// quand un RESULTAT final ou une QUESTION COMPLEMENTAIRE est deja affiche et
// que l'utilisateur change un champ DANS le formulaire (radio cascade OU
// reponse a une QC deja repondue), tout ce qui suit ce champ devient invalide.
// On revient a l'etat « parcours en cours » a ce point precis : le resultat (et
// les QC obsoletes) disparaissent, l'utilisateur n'a plus qu'a relancer.
//
// Principe directeur (les 3 causes des echecs precedents) :
//   1. Le JS ne fait QU'ELAGUER le DOM rendu par le serveur (resultat + QC +
//      hidden passthrough obsoletes). Il ne resoud RIEN a la main : cascade.js
//      reste seul maitre de la resolution radios -> hidden derives. On ne
//      resoumet pas le serveur, on ne reconstruit pas le rendu.
//   2. L'URL est nettoyee EN MIROIR comme un DICTIONNAIRE de cles UNIQUES
//      (URLSearchParams.set, jamais append) a partir de l'etat COURANT du DOM,
//      pour que la prochaine soumission parte d'un etat propre, sans doublon ni
//      reponse obsolete. history.replaceState, pas de navigation.
//   3. On traite la PAIRE radio + ses hidden derives : on lit les hidden APRES
//      que cascade.js ait re-resolu (au prochain tick), jamais le radio seul.
//
// HORS SCOPE de ce dev : le cas B (re-clic carte / changement de scope SIG).
// On ne touche pas a simulator.js ni au handler map.on('click').

(function () {
  "use strict";

  // En Node (tests unitaires), on n'expose que les helpers PURS de
  // construction d'URL (pas de DOM) puis on sort. En navigateur, on branche
  // l'elagage sur le change des champs. cf. calculatrice-calendrier.js.
  const _isNode =
    typeof module !== "undefined" &&
    module.exports &&
    typeof document === "undefined";

  // Champs « structurels » de localisation : jamais elagues de l'URL.
  const CHAMPS_LOCALISATION = ["lat", "lng", "code_insee"];

  // Cascade culture/fertilisant : les radios visibles + leurs hidden derives.
  // On reconstruit l'URL a partir de l'etat COURANT de ces champs (lus dans le
  // DOM apres le reset cascade), pour ne garder que ce qui est encore valide.
  const CHAMPS_CASCADE_VISIBLES = [
    "categorie_culture",
    "sous_culture_form",
    "categorie_fertilisant",
    "sous_fertilisant",
  ];
  const CHAMPS_HIDDEN_DERIVES = [
    "occupation_sol",
    "sous_culture",
    "culture_irriguee_type",
    "prairie_permanente",
    "type_fertilisant",
    "effluent_peu_charge",
    "effluent_peu_charge_elevage",
  ];

  // Hidden derives produits par chaque champ cascade (cf. cascade.js). Quand on
  // elague un champ cascade AVAL, on elague aussi les hidden qu'il derive, sinon
  // l'URL garderait des valeurs orphelines incoherentes avec le nouveau parcours.
  const HIDDEN_DERIVES_PAR_CHAMP = {
    categorie_culture: [
      "occupation_sol",
      "sous_culture",
      "culture_irriguee_type",
      "prairie_permanente",
    ],
    sous_culture_form: [
      "occupation_sol",
      "sous_culture",
      "culture_irriguee_type",
      "prairie_permanente",
    ],
    categorie_fertilisant: [
      "type_fertilisant",
      "effluent_peu_charge",
      "effluent_peu_charge_elevage",
    ],
    sous_fertilisant: [
      "type_fertilisant",
      "effluent_peu_charge",
      "effluent_peu_charge_elevage",
    ],
  };

  // ─── Logique PURE (testable en Node) ────────────────────────────────────
  //
  // A partir d'un dict { cle: valeur } (etat courant du form), produit la
  // query string. Invariant garanti : chaque cle apparait AU PLUS une fois
  // (URLSearchParams.set, jamais .append) ; les valeurs vides sont ignorees.
  function construireQueryString(dict) {
    const params = new URLSearchParams();
    for (const [cle, valeur] of Object.entries(dict || {})) {
      if (valeur === undefined || valeur === null || valeur === "") continue;
      params.set(cle, String(valeur));
    }
    return params.toString();
  }

  // Elague l'AVAL d'un champ change, EN PARTANT de l'URL existante (#175).
  //
  // Principe (retour Max) : on ADJOINT / MET A JOUR sans ecraser l'existant.
  // Concretement :
  //   - on part de `searchInitial` (toutes les cles deja presentes survivent) ;
  //   - `champChange` et ses hidden derives sont MIS A JOUR depuis `valeurs`
  //     (etat courant du DOM re-resolu par cascade.js) ;
  //   - tout champ STRICTEMENT APRES `champChange` dans `ordre` (radios cascade
  //     ET reponses QC aval) est SUPPRIME, ainsi que les hidden qu'il derivait ;
  //   - tout le reste (amont, localisation, params inconnus) est PRESERVE.
  //
  // `ordre` : liste des champs interactifs dans l'ordre du parcours (lu du DOM).
  // `valeurs` : { champ: valeurCourante } pour champChange + ses hidden derives.
  // `hiddenParChamp` : map champ cascade -> ses hidden derives (injectable pour
  //   les tests ; defaut = HIDDEN_DERIVES_PAR_CHAMP).
  function elaguerAvalDansUrl(
    searchInitial,
    ordre,
    champChange,
    valeurs,
    hiddenParChamp
  ) {
    const map = hiddenParChamp || HIDDEN_DERIVES_PAR_CHAMP;
    const params = new URLSearchParams(searchInitial || "");
    const idx = ordre.indexOf(champChange);

    // Champs a supprimer = ceux strictement APRES champChange + leurs hidden.
    if (idx !== -1) {
      const aval = ordre.slice(idx + 1);
      for (const champ of aval) {
        params.delete(champ);
        for (const h of map[champ] || []) params.delete(h);
      }
    }

    // Met a jour le champ change + ses hidden derives depuis l'etat courant.
    // Une valeur vide => on supprime la cle (pas de cle=… vide dans l'URL).
    const aEcrire = [champChange, ...(map[champChange] || [])];
    for (const champ of aEcrire) {
      const v = valeurs && valeurs[champ];
      if (v === undefined) continue; // pas dans le DOM courant -> on n'y touche pas
      if (v === "" || v === null) params.delete(champ);
      else params.set(champ, String(v));
    }

    return params.toString();
  }

  if (_isNode) {
    module.exports = {
      construireQueryString,
      elaguerAvalDansUrl,
      CHAMPS_LOCALISATION,
      CHAMPS_CASCADE_VISIBLES,
      CHAMPS_HIDDEN_DERIVES,
      HIDDEN_DERIVES_PAR_CHAMP,
    };
    return;
  }

  const form = document.getElementById("form-simulateur");
  if (!form) return;

  // ─── Detection de l'etat serveur affiche ───────────────────────────────
  //
  // 3 etats serveur possibles quand un champ change :
  //   1. RESULTAT FINAL : .result-col present, aucune QC en attente.
  //   2. QC EN ATTENTE  : #qc-bloc[data-qc-en-attente] present (a REMPLIR),
  //      pas de .result-col. C'est l'utilisateur qui repond -> NE PAS elaguer
  //      quand il clique un radio DANS ce bloc (sinon la QC disparait sous ses
  //      doigts = boucle infinie : il relance, le serveur la repose, etc.).
  //   3. QC REPONDUE (recap) + resultat : meme logique que l'etat 1.
  //
  // On elague donc quand un rendu serveur FINALISABLE (resultat, ou QC recap)
  // est invalide par le changement d'un champ AMONT -- mais jamais quand
  // l'utilisateur est en train de remplir la QC bloquante.

  // Le bloc QC actuellement en attente de reponse (a remplir), s'il existe.
  function qcEnAttenteBloc() {
    const bloc = document.getElementById("qc-bloc");
    return bloc && bloc.hasAttribute("data-qc-en-attente") ? bloc : null;
  }

  // Y a-t-il un rendu serveur a invalider quand un champ AMONT change ?
  // - un resultat final (.result-col), OU
  // - un bloc QC (recap repondu OU en attente : changer un champ amont
  //   invalide aussi le parcours qui a mene a cette QC).
  function rendurServeurAffiche() {
    return !!(
      document.querySelector(".result-col") || document.getElementById("qc-bloc")
    );
  }

  // ─── Elagage DOM ───────────────────────────────────────────────────────

  function elaguerResultat() {
    // 1. Retirer le panneau resultat (colonne droite).
    const resultCol = document.querySelector(".result-col");
    if (resultCol) resultCol.remove();

    // 2. Retirer le bloc QC (questions complementaires sous le form).
    const qcBloc = document.getElementById("qc-bloc");
    if (qcBloc) qcBloc.remove();
    // Au cas ou un autre panneau QC trainerait (defensif).
    document
      .querySelectorAll(".resultat-panel--questions")
      .forEach((el) => el.remove());

    // 3. Repasser le layout en colonne unique.
    const row = document.querySelector(".results-row");
    if (row) row.classList.remove("layout--split");
    const formCol = document.querySelector(".form-col");
    if (formCol) formCol.classList.remove("fr-col-lg-5");

    // 4. Retirer les hidden passthrough rendus par le serveur : ils portent
    //    les reponses QC / valeurs derivees du parcours PRECEDENT, qui ne
    //    correspondent plus au champ qu'on vient de changer. cascade.js
    //    re-resoudra les hidden derives encore pertinents ; l'URL miroir
    //    (etape suivante) ne reprendra que l'etat courant. On ne touche PAS
    //    aux hidden « officiels » du form (id_occupation_sol, etc.), seulement
    //    aux passthrough anonymes injectes par _form_hidden_passthrough.html.
    retirerPassthroughObsoletes();

    // 5. Le bouton « Suivant » (libelle affiche quand une QC est en attente,
    //    cf. #160) redevient « Lancer la simulation » : apres elagage il n'y a
    //    plus de QC en attente cote DOM. On matche « Suivant » (libelle actuel)
    //    ET « Relancer » (ancien libelle) par robustesse.
    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn && /Suivant|Relancer/.test(submitBtn.textContent)) {
      submitBtn.textContent = "Lancer la simulation";
    }

    // 6. Re-afficher le bouton de soumission : cote serveur il est CACHE quand
    //    un resultat final est affiche (rien a relancer). L'utilisateur vient
    //    de modifier un champ -> il faut pouvoir relancer -> on revele la ligne
    //    bouton. (#160 : pas de bouton orphelin sous un resultat inchange.)
    const submitRow = document.getElementById("form-submit-row");
    if (submitRow) submitRow.hidden = false;
  }

  function retirerPassthroughObsoletes() {
    // Les hidden officiels du form ont tous un id (id_occupation_sol, id_lat,
    // id_type_fertilisant...). Les passthrough injectes par
    // _form_hidden_passthrough.html (reponses QC + champs de parcours du rendu
    // serveur precedent) n'ont PAS d'id. On retire donc tout input[type=hidden]
    // sans id : c'est exactement le passthrough obsolete.
    form.querySelectorAll('input[type="hidden"]').forEach((input) => {
      if (!input.id) input.remove();
    });
  }

  // ─── URL miroir dedupliquee ────────────────────────────────────────────
  //
  // Reconstruit window.location.search comme un dictionnaire de cles UNIQUES a
  // partir de l'etat COURANT du DOM (lat/lng/code_insee + radios cascade
  // coches + leurs hidden derives non vides). On NE reprend PAS les reponses QC
  // du parcours precedent : elles sont caduques des qu'un champ amont change.
  function valeurRadio(name) {
    const checked = form.querySelector(
      `input[type="radio"][name="${name}"]:checked`
    );
    return checked ? checked.value : "";
  }

  function valeurHidden(name) {
    const el = document.getElementById(`id_${name}`);
    return el ? el.value : "";
  }

  // Construit le dict (cles uniques) a partir du DOM. Lit chaque champ une
  // seule fois -> pas de doublon possible par construction.
  // (Conserve pour compat tests jsdom : etat COMPLET courant du DOM.)
  function construireParamsDict() {
    const dict = {};
    for (const champ of CHAMPS_LOCALISATION) {
      const v = valeurHidden(champ);
      if (v) dict[champ] = v;
    }
    for (const champ of CHAMPS_CASCADE_VISIBLES) {
      const v = valeurRadio(champ);
      if (v) dict[champ] = v;
    }
    for (const champ of CHAMPS_HIDDEN_DERIVES) {
      const v = valeurHidden(champ);
      if (v) dict[champ] = v;
    }
    return dict;
  }

  // Ordre du parcours = ordre document des champs interactifs (radios cascade +
  // reponses QC). Le serveur les rend deja dans l'ordre du parcours, donc le DOM
  // est la source de verite synchrone (pas besoin de charger l'arbre).
  function ordreParcoursDOM() {
    const nodes = form.querySelectorAll("[data-cascade], [data-qc-champ]");
    const ordre = [];
    nodes.forEach((n) => {
      const champ =
        n.getAttribute("data-cascade") || n.getAttribute("data-qc-champ");
      if (champ && !ordre.includes(champ)) ordre.push(champ);
    });
    return ordre;
  }

  // Valeur cochee du champ change (radio cascade OU reponse QC). A lire AVANT
  // elaguerResultat (qui retire le bloc QC du DOM).
  function valeurCocheePour(champChange) {
    const coche = form.querySelector(`input[name="${champChange}"]:checked`);
    return coche ? coche.value : "";
  }

  // Assemble les valeurs a ecrire : la valeur cochee (capturee avant elagage) +
  // les hidden derives lus MAINTENANT (re-resolus par cascade.js au tick).
  function valeursCourantesPour(champChange, valeurCocheePreCapturee) {
    const valeurs = {};
    valeurs[champChange] =
      valeurCocheePreCapturee !== undefined
        ? valeurCocheePreCapturee
        : valeurCocheePour(champChange);
    for (const h of HIDDEN_DERIVES_PAR_CHAMP[champChange] || []) {
      valeurs[h] = valeurHidden(h);
    }
    return valeurs;
  }

  // Champs deja portes par le form (radios cascade coches + hidden officiels a
  // id). Sert a ne PAS dupliquer une cle en hidden passthrough.
  function champsDejaDansForm() {
    const noms = new Set();
    form
      .querySelectorAll("input[name], select[name]")
      .forEach((el) => noms.add(el.name));
    return noms;
  }

  // Synchronise le form avec la query string : pour chaque cle de `qs` qui n'est
  // PAS deja un champ du form (cascade / hidden officiel), on (re)cree un hidden
  // passthrough. Ainsi la prochaine soumission GET (bouton « Lancer ») envoie
  // EXACTEMENT l'etat de l'URL elaguee -- dont les reponses QC amont re-choisies
  // (#175 : sans ca, une reponse QC re-flippee etait perdue a la resoumission
  // car son input avait ete retire du DOM avec le bloc QC).
  function synchroniserFormDepuisUrl(qs) {
    const dejaLa = champsDejaDansForm();
    const params = new URLSearchParams(qs);
    for (const [cle, valeur] of params) {
      if (dejaLa.has(cle)) continue; // porte par un champ existant
      if (!valeur) continue;
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = cle;
      input.value = valeur;
      // Pas d'id -> considere passthrough, retire au prochain elagage.
      form.appendChild(input);
    }
  }

  // Met a jour l'URL : part de l'existant, met a jour le champ change + ses
  // hidden derives, elague l'aval, preserve tout le reste (#175). Puis
  // synchronise le form pour que la resoumission GET envoie ce meme etat.
  // `ordre` et `valeurCochee` sont captures AVANT elagage par onChangeChamp.
  function reconstruireUrl(champChange, ordre, valeurCochee) {
    const qs = elaguerAvalDansUrl(
      window.location.search,
      ordre || ordreParcoursDOM(),
      champChange,
      valeursCourantesPour(champChange, valeurCochee)
    );
    const nouvelle =
      window.location.pathname + (qs ? `?${qs}` : "") + window.location.hash;
    window.history.replaceState(null, "", nouvelle);
    synchroniserFormDepuisUrl(qs);
  }

  // ─── Branchement sur le change d'un champ du formulaire ────────────────
  //
  // On ecoute en delegation sur le form (capture) : les radios cascade sont
  // ajoutes dynamiquement par cascade.js, donc on ne peut pas brancher des
  // listeners au chargement. On laisse cascade.js / couvert_split.js /
  // subsidiaires_cascade.js traiter leur change EN PREMIER (resolution des
  // hidden derives, reset des niveaux aval) puis on elague + miroir au tick
  // suivant, pour lire des hidden deja re-resolus.
  function onChangeChamp(e) {
    const target = e.target;
    if (!target || target.type !== "radio") return;
    // lat/lng/code_insee ne sont pas des radios -> deja exclus.
    if (!rendurServeurAffiche()) return;

    // GARDE-FOU anti-boucle (#135) : si le radio modifie est DANS le bloc QC
    // en attente, c'est l'utilisateur qui REPOND a la question bloquante. On ne
    // touche a RIEN : subsidiaires_cascade.js gere la cascade conditionnelle,
    // et la QC doit rester a l'ecran pour qu'il puisse relancer. Elaguer ici
    // ferait disparaitre la QC sous ses doigts (boucle infinie constatee).
    const blocAttente = qcEnAttenteBloc();
    if (blocAttente && blocAttente.contains(target)) return;

    // Idem si le radio est dans le bloc QC (recap repondu) ET qu'aucun resultat
    // final n'est affiche : on est encore en phase de saisie QC, pas sur un
    // resultat finalise -> ne pas elaguer. (Cas ou plusieurs QC s'enchainent.)
    const qcBloc = document.getElementById("qc-bloc");
    const resultatFinal = document.querySelector(".result-col");
    if (qcBloc && qcBloc.contains(target) && !resultatFinal) return;

    // Sinon : un champ (cascade AMONT, ou reponse QC recap) a change alors
    // qu'un resultat / une QC est affiche -> on invalide le rendu serveur et on
    // met a jour l'URL en n'elaguant que l'AVAL de CE champ (#175 : on preserve
    // les reponses amont, dont celle qu'on vient de re-choisir). Laisse
    // cascade.js finir son travail (tick suivant) avant de lire les hidden.
    const champChange = target.name;
    // On capture AVANT elagage (elaguerResultat retire le bloc QC du DOM) :
    //  - l'ORDRE du parcours (pour savoir ce qui est en aval du champ change) ;
    //  - la valeur cochee du champ change (une reponse QC recap vit dans
    //    #qc-bloc, qui va etre retire).
    const ordre = ordreParcoursDOM();
    const valeurCochee = valeurCocheePour(champChange);
    setTimeout(() => {
      elaguerResultat();
      reconstruireUrl(champChange, ordre, valeurCochee);
    }, 0);
  }

  form.addEventListener("change", onChangeChamp);

  // Expose pour les tests unitaires (jsdom / node) sans polluer l'API
  // publique : uniquement la fonction pure de construction du dict.
  window.__nitratesResetForm = {
    construireParamsDict,
    CHAMPS_LOCALISATION,
    CHAMPS_CASCADE_VISIBLES,
    CHAMPS_HIDDEN_DERIVES,
  };
})();
