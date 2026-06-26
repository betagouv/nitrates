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

  if (_isNode) {
    module.exports = {
      construireQueryString,
      CHAMPS_LOCALISATION,
      CHAMPS_CASCADE_VISIBLES,
      CHAMPS_HIDDEN_DERIVES,
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

    // 5. Le bouton « Relancer la simulation » redevient « Lancer la
    //    simulation » : il n'y a plus de QC en attente cote DOM.
    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn && /Relancer/.test(submitBtn.textContent)) {
      submitBtn.textContent = "Lancer la simulation";
    }
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

  function reconstruireUrl() {
    const qs = construireQueryString(construireParamsDict());
    const nouvelle =
      window.location.pathname + (qs ? `?${qs}` : "") + window.location.hash;
    window.history.replaceState(null, "", nouvelle);
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

    // Sinon : un champ AMONT (cascade) a change alors qu'un resultat / une QC
    // est affiche -> on invalide le rendu serveur et on laisse la cascade
    // reprendre. Laisse cascade.js finir son travail (tick suivant).
    setTimeout(() => {
      elaguerResultat();
      reconstruireUrl();
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
