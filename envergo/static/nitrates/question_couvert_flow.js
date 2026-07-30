// Flow FRONT (UI seulement) du parcours « Culture ou couvert » — carte #272.
//
// Refactor UX : au lieu d'une question unique « Sur quelle culture ou couvert »
// à 7 catégories, on pose des questions successives (une à la fois) :
//
//   Q1  destination  -> « Vous avez prévu d'épandre ? »
//                       · sur / juste avant un couvert            => couvert
//                       · sur / juste avant une culture principale => culture_principale
//   Q2 (couvert)     -> « Quel type de couvert ? »
//                       · suivi d'une culture de printemps  => interculture LONGUE
//                       · suivi d'une culture d'hiver        => interculture COURTE
//   Q2 (culture)     -> les 5 catégories culture actuelles, sol_non_cultivé en bas
//   Q3 (couvert)     -> « Le couvert est-il récolté, fauché ou pâturé ? »
//                       · oui  => CIE  (couvert exporté)
//                       · non  => CINE (couvert non exporté)
//   Q4 (couvert)     -> dates de semis + destruction (picker JJ/MM DSFR)
//
// INERTE pour le backend et l'arbre : ce module ne fait que PILOTER les vrais
// champs cascade `categorie_culture` / `sous_culture_form` (rendus + masqués
// par le template, source de vérité soumise au serveur). On coche le bon radio
// et on dispatch son `change` -> cascade.js prend le relais (résolution des
// hidden inputs, cascade fertilisant), exactement comme le faisait couvert_split.js.
//
// Inférence #272 pour l'interculture LONGUE : la question historique « encore
// en place après le 1er janvier ? » est SUPPRIMÉE et remplacée par
// l'interprétation de la date de destruction du couvert (Q4) :
//   destruction ≥ 01/01 (inclus, sur l'année agricole 1er juillet = origine)
//       => couvert toujours en place après le 1er janvier => branche …_apres_0101
//   destruction ≤ 31/12
//       => plus en place après le 31 décembre             => branche …_avant_3112
// Combinée à Q3 (récolté = CIE, non = CINE), on recompose l'une des 4 valeurs
// existantes de sous_culture_form :
//   couvert_{recolte|non_recolte}_{plus_en_place_apres_3112|toujours_en_place_apres_0101}
//
// Pour l'interculture COURTE, Q3 mappe directement :
//   récolté => couvert_courte_recolte  · non récolté => couvert_courte_non_recolte
// (la date de destruction n'entre pas dans le routage courte, mais Q4 reste
// affichée pour forcer l'agriculteur à renseigner ses dates.)

(function () {
  "use strict";

  // ─── Catégories référentiel : familles ─────────────────────────────────
  var CATS_COUVERT = {
    couvert_intercultures_longue: {
      label: "Couvert suivi d'une culture de printemps (interculture longue)",
    },
    couvert_intercultures_courte: {
      label: "Couvert suivi d'une culture d'hiver (interculture courte)",
    },
  };
  // Catégories culture principale, dans l'ordre voulu (#272) : sol_non_cultivé
  // relégué en dernier. Les autres suivent l'ordre du référentiel.
  var CATS_CULTURE_ORDRE = [
    "culture_hiver",
    "culture_printemps",
    "prairies_ou_luzerne",
    "autres_cultures_principales",
    "sol_non_cultive",
  ];

  // Libellés surchargés côté flow (#272) sans toucher aux référentiels : la
  // carte demande une parenthèse explicative sur « Sol non cultivé ».
  var LABELS_CULTURE_OVERRIDE = {
    sol_non_cultive:
      "Sol non cultivé (surface non utilisée en vue d'une production agricole : ni semé, ni récolté, ni fauché, ni pâturé pendant une campagne culturale)",
  };

  // Q1 — 4 réponses, mais 2 valeurs métier (couvert / culture_principale).
  var Q1_OPTIONS = [
    { val: "couvert", label: "Sur un couvert" },
    { val: "couvert", label: "Juste avant l'implantation d'un couvert" },
    { val: "culture_principale", label: "Sur une culture principale" },
    {
      val: "culture_principale",
      label: "Juste avant l'implantation d'une culture principale",
    },
  ];

  // Q3 — axe récolté (détermine CIE vs CINE).
  var Q3_OPTIONS = [
    {
      val: "recolte",
      label: "Couvert récolté, fauché ou pâturé (dérobée, CIVE…)",
    },
    {
      val: "non_recolte",
      label: "Couvert ni récolté, ni fauché, ni pâturé (CIPAN, engrais vert…)",
    },
  ];

  var referentiels = null;

  // ─── Helpers DOM ────────────────────────────────────────────────────────

  function el(id) {
    return document.getElementById(id);
  }
  function wrapper(id) {
    return el(id + "-wrapper");
  }
  function montrer(id) {
    var w = wrapper(id);
    if (w) w.hidden = false;
  }
  function cacher(id) {
    var w = wrapper(id);
    if (w) w.hidden = true;
  }

  // Radios du flow (pas les vrais champs cascade) : name préfixé cflow_.
  function valeurFlow(name) {
    var r = document.querySelector(
      'input[type="radio"][name="' + name + '"]:checked'
    );
    return r ? r.value : "";
  }

  function slug(s) {
    return String(s)
      .replace(/[^a-zA-Z0-9_-]/g, "_")
      .toLowerCase();
  }

  // Rend un groupe de radios dans le container `container`, name=`name`.
  // onChange rappelé à chaque sélection. Modèle clavier a11y aligné sur
  // cascade.js (#154) : Tab = chaque radio, Entrée = coche + saut au suivant.
  function rendreRadios(container, name, options, onChange, focusSuivant) {
    container.innerHTML = "";
    options.forEach(function (opt, i) {
      var rg = document.createElement("div");
      rg.className = "fr-radio-group";
      var input = document.createElement("input");
      input.type = "radio";
      input.name = name;
      input.id = "id_" + name + "__" + i + "_" + slug(opt.val);
      input.value = opt.val;
      input.tabIndex = 0;
      input.addEventListener("change", function () {
        onChange(opt.val, input);
      });
      input.addEventListener("keydown", function (e) {
        onRadioKeydown(e, input, container, focusSuivant);
      });
      var label = document.createElement("label");
      label.className = "fr-label";
      label.htmlFor = input.id;
      label.textContent = opt.label;
      rg.appendChild(input);
      rg.appendChild(label);
      container.appendChild(rg);
    });
  }

  function radiosDe(container) {
    return Array.prototype.slice.call(
      container.querySelectorAll('input[type="radio"]')
    );
  }

  function onRadioKeydown(e, input, container, focusSuivant) {
    var radios = radiosDe(container);
    var idx = radios.indexOf(input);
    if (idx === -1) return;
    if (e.key === "Enter") {
      e.preventDefault();
      if (!input.checked) {
        input.checked = true;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
      // Laisse le flow révéler la question suivante avant de la focuser.
      Promise.resolve().then(function () {
        if (typeof focusSuivant === "function") focusSuivant();
      });
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      radios[(idx + 1) % radios.length].focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      radios[(idx - 1 + radios.length) % radios.length].focus();
    } else if (e.key === "Tab") {
      if (e.shiftKey) {
        if (idx > 0) {
          e.preventDefault();
          radios[idx - 1].focus();
        }
      } else if (idx < radios.length - 1) {
        e.preventDefault();
        radios[idx + 1].focus();
      }
    }
  }

  function focusPremierRadio(containerId) {
    var c = el(containerId);
    if (!c) return false;
    var r = c.querySelector('input[type="radio"]');
    if (r && r.offsetParent !== null) {
      r.focus();
      return true;
    }
    return false;
  }

  function focusBoutonSiPret() {
    var btn = document.querySelector("#form-submit-row button[type=submit]");
    if (btn && !btn.disabled) btn.focus();
  }

  // ─── Pilotage des vrais champs cascade ──────────────────────────────────

  // Coche le radio `value` du champ cascade `champ` (categorie_culture ou
  // sous_culture_form) et dispatch son change -> cascade.js prend le relais.
  // Retourne true si le radio existe et a été (re)coché.
  function pilotherCascade(champ, value) {
    var radio = document.querySelector(
      'input[type="radio"][name="' + champ + '"][value="' + value + '"]'
    );
    if (!radio) return false;
    if (!radio.checked) {
      radio.checked = true;
      radio.dispatchEvent(new Event("change", { bubbles: true }));
    }
    return true;
  }

  // ─── Inférence date de destruction -> axe présence (interculture longue) ──

  // Année agricole : origine 1er juillet. Un JJ/MM tombant entre le 01/01 et le
  // 30/06 correspond à « l'année suivante » -> après le 1er janvier. Bornes
  // inclusives par convention (#272).
  function destructionApres0101(jjmm) {
    var m = /^(\d{2})\/(\d{2})$/.exec(jjmm || "");
    if (!m) return null; // date non saisie/invalide : pas d'inférence
    var mois = parseInt(m[2], 10);
    // Mois 01..06 = 2ᵉ moitié de l'année agricole (janv->juin) = après 01/01.
    // Mois 07..12 = 1ʳᵉ moitié (juil->déc) = plus en place après le 31/12.
    return mois >= 1 && mois <= 6;
  }

  // ─── Recomposition sous_culture_form + pilotage ─────────────────────────

  function appliquerCouvert() {
    var type = valeurFlow("cflow_type_couvert"); // longue | courte (clé référentiel)
    if (!type) return;
    var recolte = valeurFlow("cflow_couvert_recolte"); // recolte | non_recolte
    if (!recolte) return;

    // La catégorie réelle (categorie_culture) est déjà pilotée dès Q2 (voir
    // onChangeTypeCouvert). Ici on recompose sous_culture_form quand Q3 (+ Q4
    // pour la longue) sont disponibles.
    if (type === "couvert_intercultures_courte") {
      var scCourte =
        recolte === "recolte" ? "couvert_courte_recolte" : "couvert_courte_non_recolte";
      pilotherCascade("sous_culture_form", scCourte);
      return;
    }

    // Interculture longue : présence inférée de la date de destruction (Q4).
    var apres = destructionApres0101(el("id_date_destruction_couvert").value);
    if (apres === null) return; // date pas encore renseignée -> on attend Q4
    var presence = apres
      ? "toujours_en_place_apres_0101"
      : "plus_en_place_apres_3112";
    var scLongue = "couvert_" + recolte + "_" + presence;
    pilotherCascade("sous_culture_form", scLongue);
  }

  // ─── Rendu des questions ────────────────────────────────────────────────

  function rendreQ1() {
    var c = el("q_destination_epandage");
    if (!c) return;
    rendreRadios(
      c,
      "cflow_destination",
      Q1_OPTIONS,
      onChangeDestination,
      function () {
        // Après Q1 : focus Q2 (couvert ou culture selon la réponse).
        if (!focusPremierRadio("q_type_couvert")) focusPremierRadio("q_type_couvert");
      }
    );
  }

  function onChangeDestination(val) {
    // Reset des questions en aval.
    resetCouvertAval();
    cacher("q_type_couvert");
    cacher("q_couvert_recolte");
    cacher("q_dates_couvert");

    if (val === "couvert") {
      rendreQ2Couvert();
      montrer("q_type_couvert");
    } else {
      rendreQ2Culture();
      montrer("q_type_couvert");
    }
    mettreAJourBouton();
  }

  // Le libellé de Q2 dépend de Q1 : « type de couvert » vs « catégorie de
  // culture principale ». On garde le « * » (champ obligatoire).
  function setLabelQ2(texte) {
    var lab = el("q_type_couvert-label");
    // espace insécable avant « ? » (typo FR), aligné sur le template.
    if (lab) lab.textContent = texte + " ? *";
  }

  // Q2 — cas couvert : longue / courte.
  function rendreQ2Couvert() {
    var c = el("q_type_couvert");
    setLabelQ2("Quel type de couvert");
    var opts = Object.keys(CATS_COUVERT).map(function (cle) {
      return { val: cle, label: CATS_COUVERT[cle].label };
    });
    rendreRadios(c, "cflow_type_couvert", opts, onChangeTypeCouvert, function () {
      focusPremierRadio("q_couvert_recolte");
    });
  }

  // Q2 — cas culture principale : 5 catégories, sol_non_cultivé en bas.
  function rendreQ2Culture() {
    var c = el("q_type_couvert");
    setLabelQ2("Quelle catégorie de culture principale");
    var cats = (referentiels || {}).categories_cultures || {};
    var opts = CATS_CULTURE_ORDRE.filter(function (cle) {
      return cats[cle];
    }).map(function (cle) {
      return {
        val: cle,
        label:
          LABELS_CULTURE_OVERRIDE[cle] || cats[cle].libelle_public || cle,
      };
    });
    rendreRadios(c, "cflow_type_couvert", opts, onChangeTypeCulture, function () {
      // Culture principale : question suivante = précision sous_culture (si la
      // catégorie en a) ou directement le fertilisant.
      focusPremierRadio("q_sous_culture") || focusApresCouvert();
    });
  }

  // Sélection d'un type de couvert (longue/courte) : on pilote la catégorie
  // réelle, on révèle Q3.
  function onChangeTypeCouvert(val) {
    resetApresType();
    pilotherCascade("categorie_culture", val);
    cacher("q_dates_couvert");
    rendreQ3();
    montrer("q_couvert_recolte");
    mettreAJourBouton();
  }

  // Sélection d'une catégorie culture principale : on pilote le champ cascade
  // categorie_culture (cascade.js rend alors les sous_culture_form réels dans le
  // container masqué), puis on rend Q3-culture (précision) en pilotant ces
  // radios réels. sol_non_cultivé n'a pas de sous-catégorie -> on saute Q3.
  function onChangeTypeCulture(val) {
    resetApresType();
    cacher("q_couvert_recolte");
    cacher("q_dates_couvert");
    pilotherCascade("categorie_culture", val);

    var cats = (referentiels || {}).categories_cultures || {};
    var sousCles = (cats[val] || {}).sous_cultures || [];
    if (sousCles.length > 0) {
      rendreQ3Culture(sousCles);
      montrer("q_sous_culture");
    }
    // Si sol_non_cultivé : cascade.js a déjà résolu occupation_sol=sol_non_cultive
    // et enchaîné sur le fertilisant, rien de plus à faire ici.
    mettreAJourBouton();
  }

  // Q3 culture principale : précision du type (sous_culture réel). Chaque option
  // correspond à un radio sous_culture_form rendu par cascade.js (masqué) : on
  // le coche et on dispatch son change -> résolution hidden inputs + fertilisant.
  function rendreQ3Culture(sousCles) {
    var c = el("q_sous_culture");
    var sousCultures = (referentiels || {}).sous_cultures || {};
    var opts = sousCles.map(function (sc) {
      var meta = sousCultures[sc] || {};
      return { val: sc, label: meta.libelle_public || sc };
    });
    rendreRadios(
      c,
      "cflow_sous_culture",
      opts,
      function (val) {
        pilotherCascade("sous_culture_form", val);
        mettreAJourBouton();
      },
      function () {
        focusApresCouvert();
      }
    );
  }

  function rendreQ3() {
    var c = el("q_couvert_recolte");
    rendreRadios(
      c,
      "cflow_couvert_recolte",
      Q3_OPTIONS,
      onChangeRecolte,
      function () {
        // Q4 (dates) vient d'être révélée : focus son 1er champ date.
        var d = document.querySelector("#q_dates_couvert input[data-input-id]");
        if (d && d.offsetParent !== null) d.focus();
        else focusApresCouvert();
      }
    );
  }

  // #272 : les 2 champs dates n'apparaissent à GAUCHE que pendant la SAISIE.
  // Une fois le résultat affiché, ils feraient doublon avec ceux du calendrier
  // dynamique (à droite, au-dessus du calendrier) qui pilotent déjà le rendu.
  // On ne les montre donc pas à gauche sur la page résultat.
  function resultatAffiche() {
    var form = el("form-simulateur");
    return !!(form && form.hasAttribute("data-resultat-affiche"));
  }

  function montrerDatesGauche() {
    if (resultatAffiche()) {
      cacher("q_dates_couvert");
      return;
    }
    montrer("q_dates_couvert");
    monterDatesSiBesoin();
  }

  function onChangeRecolte() {
    // Q3 répondue : on révèle Q4 (dates) puis on tente de recomposer.
    montrerDatesGauche();
    appliquerCouvert();
    mettreAJourBouton();
  }

  // ─── Q4 : dates de semis + destruction (picker JJ/MM DSFR) ──────────────
  // Composant self-contained (ne dépend pas du calendrier dynamique de droite,
  // qu'on ne touche pas — cf. #272). Réutilise les classes .calc-cal__* pour le
  // look et le picker calendrier.

  var datesMontees = false;

  var DATE_INPUTS = [
    {
      id: "date_semis_couvert",
      hidden: "id_date_semis_couvert",
      label: "Date prévue de semis du couvert",
      placeholder: "15/08",
    },
    {
      id: "date_destruction_couvert",
      hidden: "id_date_destruction_couvert",
      label: "Date prévue de destruction du couvert",
      placeholder: "15/12",
    },
  ];

  function monterDatesSiBesoin() {
    if (datesMontees) return;
    var mount = el("q_dates_couvert");
    if (!mount) return;
    mount.innerHTML = renderDatesForm();
    bindDates(mount);
    datesMontees = true;
  }

  var SVG_CAL =
    '<svg class="calc-cal__field-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">' +
    '<rect x="3.5" y="5" width="17" height="15" rx="2"/>' +
    '<line x1="3.5" y1="9.5" x2="20.5" y2="9.5"/>' +
    '<line x1="8" y1="3" x2="8" y2="6.5"/>' +
    '<line x1="16" y1="3" x2="16" y2="6.5"/>' +
    "</svg>";

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderDatesForm() {
    return (
      '<div class="calc-cal__form">' +
      DATE_INPUTS.map(function (inp) {
        var cur = (el(inp.hidden) || {}).value || "";
        // #272 : PAS de placeholder gris (15/08) tant que rien n'est saisi -> il
        // faisait croire que le champ était rempli et masquait que « Suivant »
        // était désactivé. Le champ reste VIDE (état requis visible, encadré
        // rouge via aria-invalid), mais le date-picker s'ouvre quand même sur le
        // mois indicatif (data-mois-defaut).
        var champVide = !cur;
        return (
          '<label class="calc-cal__field">' +
          '<span class="calc-cal__field-label">' +
          escapeHtml(inp.label) +
          "</span>" +
          '<input type="text" class="fr-input" ' +
          'data-input-id="' +
          escapeHtml(inp.id) +
          '" data-mois-defaut="' +
          escapeHtml(inp.placeholder) +
          '" value="' +
          escapeHtml(cur) +
          '" placeholder="jj/mm"' +
          ' pattern="^\\d{2}/\\d{2}$" maxlength="5"' +
          (champVide ? ' aria-invalid="true"' : "") +
          ">" +
          SVG_CAL +
          "</label>"
        );
      }).join("") +
      "</div>"
    );
  }

  function inputMeta(id) {
    for (var i = 0; i < DATE_INPUTS.length; i++) {
      if (DATE_INPUTS[i].id === id) return DATE_INPUTS[i];
    }
    return null;
  }

  function bindDates(mount) {
    mount.querySelectorAll("input[data-input-id]").forEach(function (elmt) {
      elmt.addEventListener("focus", function () {
        elmt.removeAttribute("data-default");
      });
      elmt.addEventListener("change", function () {
        onDateChange(elmt);
      });
      // Accessibilité clavier (#272) : Entrée ou flèche bas sur le champ ouvre
      // le calendrier et donne le focus au jour sélectionné -> tout se fait au
      // clavier (Tab pour entrer, Entrée pour ouvrir, flèches pour naviguer,
      // Entrée pour valider, focus passe ensuite au champ/section suivant).
      elmt.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === "ArrowDown") {
          // N'ouvre pas si l'utilisateur a tapé une date valide et appuie
          // Entrée pour la valider : dans ce cas on laisse le change + on avance.
          if (e.key === "Enter" && /^\d{2}\/\d{2}$/.test(elmt.value.trim())) {
            elmt.dispatchEvent(new Event("change", { bubbles: true }));
            avancerApresDate(elmt);
            return;
          }
          e.preventDefault();
          ouvrirPicker(elmt);
        }
      });
      attachPicker(elmt);
    });
  }

  // Après qu'une date est saisie/choisie, on avance le focus : semis -> champ
  // destruction ; destruction -> 1er radio du fertilisant (ou bouton si prêt).
  function avancerApresDate(inputEl) {
    var id = inputEl.dataset.inputId;
    if (id === "date_semis_couvert") {
      var destr = document.querySelector(
        '#q_dates_couvert input[data-input-id="date_destruction_couvert"]'
      );
      if (destr) {
        destr.focus();
        return;
      }
    }
    // destruction (ou pas de champ suivant) : on passe au fertilisant.
    focusApresCouvert();
  }

  function onDateChange(elmt) {
    var id = elmt.dataset.inputId;
    var meta = inputMeta(id);
    var val = elmt.value.trim();
    if (val && !/^\d{2}\/\d{2}$/.test(val)) {
      // Saisie invalide : on revient à la valeur hidden précédente.
      elmt.value = (el(meta.hidden) || {}).value || "";
      return;
    }
    if (el(meta.hidden)) el(meta.hidden).value = val;
    // Encadré rouge (aria-invalid) tant que le champ est vide : la date est
    // obligatoire, il faut que ça se voie (sinon l'utilisateur ne comprend pas
    // pourquoi « Suivant » est désactivé). #272.
    if (val) elmt.removeAttribute("aria-invalid");
    else elmt.setAttribute("aria-invalid", "true");
    // La date de destruction pilote l'axe présence (interculture longue).
    appliquerCouvert();
    mettreAJourBouton();
  }

  // ─── Date picker JJ/MM (grille calendrier d'un mois, sans année) ─────────
  var MOIS_LABELS = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
  ];
  var JOURS_PAR_MOIS = {
    1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
    7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31,
  };
  var openPicker = null;

  // Ouvre le date-picker pour `inputEl`. Fonction module-level pour être
  // appelable depuis le keydown du champ (Entrée/flèche bas) et depuis le clic.
  function ouvrirPicker(inputEl) {
    var field = inputEl.closest(".calc-cal__field");
    if (!field) return;
    if (openPicker) openPicker.close();
    var popup = createPickerPopup(inputEl);
    // Le popup est ancré sur <body> en position: fixed, PAS dans le
    // .calc-cal__field : un ancêtre du form (.results-row { overflow: clip })
    // clippait sinon la grille du calendrier -> impossible de choisir un jour
    // (bug remonté #272). On le place à la main sous l'input via son rect.
    popup.classList.add("calc-cal__picker--fixed");
    document.body.appendChild(popup);
    var positionner = function () {
      var r = inputEl.getBoundingClientRect();
      // Le popup est en position: fixed. On le place sous l'input si la place
      // le permet, sinon AU-DESSUS (sinon il déborde sous le viewport quand le
      // champ est bas dans la page). left borné pour rester à l'écran.
      var h = popup.offsetHeight || 300;
      var placeDessous = r.bottom + 6 + h <= window.innerHeight;
      var top = placeDessous ? r.bottom + 6 : Math.max(6, r.top - 6 - h);
      var left = Math.min(
        r.left,
        Math.max(6, window.innerWidth - (popup.offsetWidth || 268) - 6)
      );
      popup.style.top = top + "px";
      popup.style.left = left + "px";
    };
    positionner();
    var outside = function (e) {
      if (!popup.contains(e.target) && e.target !== inputEl) {
        openPicker.close();
      }
    };
    openPicker = {
      input: inputEl,
      close: function (opts) {
        popup.remove();
        openPicker = null;
        document.removeEventListener("mousedown", outside, true);
        window.removeEventListener("scroll", positionner, true);
        window.removeEventListener("resize", positionner);
        // Fermeture au clavier (Échap/Entrée) : on rend le focus au champ pour
        // que Tab reprenne la navigation à partir de là.
        if (opts && opts.focusInput) inputEl.focus();
      },
    };
    // Repositionne le popup si la page scrolle / se redimensionne pendant
    // qu'il est ouvert (position: fixed -> il faut suivre l'input).
    window.addEventListener("scroll", positionner, true);
    window.addEventListener("resize", positionner);
    setTimeout(function () {
      document.addEventListener("mousedown", outside, true);
    }, 0);
    // Focus le jour sélectionné pour la navigation clavier immédiate.
    var jourSel =
      popup.querySelector(".calc-cal__picker-day--selected") ||
      popup.querySelector(".calc-cal__picker-day:not([disabled])");
    if (jourSel) jourSel.focus();
  }

  function attachPicker(inputEl) {
    var field = inputEl.closest(".calc-cal__field");
    if (!field) return;
    inputEl.addEventListener("click", function () {
      ouvrirPicker(inputEl);
    });
    var picto = field.querySelector(".calc-cal__field-icon");
    if (picto) {
      picto.style.pointerEvents = "auto";
      picto.style.cursor = "pointer";
      picto.addEventListener("click", function (e) {
        e.preventDefault();
        inputEl.focus();
        ouvrirPicker(inputEl);
      });
    }
  }

  function parseJjmm(s) {
    var m = /^(\d{2})\/(\d{2})$/.exec(s || "");
    if (!m) return null;
    return { jour: parseInt(m[1], 10), mois: parseInt(m[2], 10) };
  }

  function createPickerPopup(inputEl) {
    // Ouvre le calendrier sur la date saisie ; à défaut sur le MOIS INDICATIF
    // (data-mois-defaut : 15/08 pour le semis -> août, 15/12 pour la
    // destruction -> décembre), et seulement en dernier recours sur le 15
    // janvier. Le champ n'affiche plus de placeholder gris (#272) mais garde ce
    // repère pour l'ouverture du picker.
    var current =
      parseJjmm(inputEl.value) ||
      parseJjmm(inputEl.getAttribute("data-mois-defaut")) || {
        jour: 15,
        mois: 1,
      };
    var state = { mois: current.mois };
    var popup = document.createElement("div");
    popup.className = "calc-cal__picker";
    popup.innerHTML =
      '<div class="calc-cal__picker-header">' +
      '<button type="button" class="calc-cal__picker-nav" data-nav="prev" aria-label="Mois précédent">‹</button>' +
      '<span class="calc-cal__picker-mois-label" data-mois-label></span>' +
      '<button type="button" class="calc-cal__picker-nav" data-nav="next" aria-label="Mois suivant">›</button>' +
      "</div>" +
      '<div class="calc-cal__picker-weekdays">' +
      "<span>L</span><span>M</span><span>M</span><span>J</span><span>V</span><span>S</span><span>D</span>" +
      "</div>" +
      '<div class="calc-cal__picker-grid" data-grid></div>';
    var moisLabel = popup.querySelector("[data-mois-label]");
    var grid = popup.querySelector("[data-grid]");

    function render() {
      moisLabel.textContent = MOIS_LABELS[state.mois - 1];
      var maxJour = JOURS_PAR_MOIS[state.mois] || 31;
      var RYEAR = 2024; // bissextile ; l'année ne sert qu'à aligner la grille.
      var firstDay = new Date(RYEAR, state.mois - 1, 1);
      var offset = (firstDay.getDay() + 6) % 7; // Lun=0
      var cells = [];
      for (var i = 0; i < offset; i++) {
        cells.push(
          '<button type="button" class="calc-cal__picker-day calc-cal__picker-day--empty" disabled></button>'
        );
      }
      for (var j = 1; j <= maxJour; j++) {
        var isSel = j === current.jour && state.mois === current.mois;
        var cls =
          "calc-cal__picker-day" +
          (isSel ? " calc-cal__picker-day--selected" : "");
        cells.push(
          '<button type="button" class="' +
            cls +
            '" data-jour="' +
            j +
            '">' +
            j +
            "</button>"
        );
      }
      grid.innerHTML = cells.join("");

      function choisir(jour) {
        var jj = String(jour).padStart(2, "0");
        var mm = String(state.mois).padStart(2, "0");
        inputEl.value = jj + "/" + mm;
        inputEl.removeAttribute("data-default");
        inputEl.dispatchEvent(new Event("change", { bubbles: true }));
        if (openPicker) openPicker.close();
        // Clavier : après validation d'une date, on avance au champ/section
        // suivant (destruction après semis, fertilisant après destruction).
        avancerApresDate(inputEl);
      }

      grid.querySelectorAll("[data-jour]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          choisir(parseInt(btn.dataset.jour, 10));
        });
        // Navigation clavier dans la grille (#272, a11y) : flèches pour se
        // déplacer d'un jour (±1) ou d'une semaine (±7), Entrée/Espace pour
        // valider, Échap pour fermer sans choisir.
        btn.addEventListener("keydown", function (e) {
          var jour = parseInt(btn.dataset.jour, 10);
          var cible = null;
          if (e.key === "ArrowRight") cible = jour + 1;
          else if (e.key === "ArrowLeft") cible = jour - 1;
          else if (e.key === "ArrowDown") cible = jour + 7;
          else if (e.key === "ArrowUp") cible = jour - 7;
          else if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            choisir(jour);
            return;
          } else if (e.key === "Escape") {
            e.preventDefault();
            if (openPicker) openPicker.close({ focusInput: true });
            return;
          } else {
            return;
          }
          e.preventDefault();
          var next = grid.querySelector('[data-jour="' + cible + '"]');
          if (next) next.focus();
        });
      });
    }

    popup.querySelectorAll(".calc-cal__picker-nav").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var dir = btn.dataset.nav === "prev" ? -1 : 1;
        state.mois = ((state.mois - 1 + dir + 12) % 12) + 1;
        render();
        // Refocus un jour après changement de mois (garde la nav clavier).
        var d = grid.querySelector(".calc-cal__picker-day:not([disabled])");
        if (d) d.focus();
      });
    });

    render();
    return popup;
  }

  // ─── Focus / séquencement ───────────────────────────────────────────────

  function focusApresCouvert() {
    // Après Q3 sans dates montées (courte fera quand même les dates) : on tente
    // le fertilisant, sinon le bouton.
    var fert = document.querySelector(
      '[data-cascade="categorie_fertilisant"] input[type="radio"]'
    );
    if (fert && fert.offsetParent !== null) {
      fert.focus();
      return;
    }
    focusBoutonSiPret();
  }

  // ─── Reset ──────────────────────────────────────────────────────────────

  // Reset des questions EN AVAL de Q2 (type) : Q3 (récolté/sous-culture) + Q4
  // (dates). Ne touche NI Q1 (destination) NI Q2 (type) : appelé quand on
  // (re)choisit un type, il ne doit pas décocher le choix qu'on vient de faire.
  function resetApresType() {
    ["cflow_couvert_recolte", "cflow_sous_culture"].forEach(function (name) {
      document
        .querySelectorAll('input[type="radio"][name="' + name + '"]')
        .forEach(function (r) {
          r.checked = false;
        });
    });
    cacher("q_sous_culture");
    var scMount = el("q_sous_culture");
    if (scMount) scMount.innerHTML = "";
    resetDates();
  }

  // Reset complet du bloc couvert/culture SOUS Q1 : décoche aussi Q2 (type).
  // Appelé quand on change la destination (Q1).
  function resetCouvertAval() {
    document
      .querySelectorAll('input[type="radio"][name="cflow_type_couvert"]')
      .forEach(function (r) {
        r.checked = false;
      });
    resetApresType();
  }

  function resetDates() {
    DATE_INPUTS.forEach(function (inp) {
      var h = el(inp.hidden);
      if (h) h.value = "";
    });
    datesMontees = false;
    var mountDates = el("q_dates_couvert");
    if (mountDates) mountDates.innerHTML = "";
  }

  // ─── Bouton submit ──────────────────────────────────────────────────────
  // On délègue la logique de gating à cascade.js : on force juste un
  // recalcul en dispatchant un event que cascade.js écoute déjà. En plus, on
  // pose un flag sur le form quand Q4 (dates couvert) est visible mais que les
  // 2 dates ne sont pas encore saisies -> cascade.js bloque le bouton (les
  // dates sont marquées obligatoires « * » dans la carte #272).
  function majGatingDates() {
    var form = el("form-simulateur");
    if (!form) return;
    var q4Visible = false;
    var w = wrapper("q_dates_couvert");
    if (w && !w.hidden) q4Visible = true;
    var incompletes =
      q4Visible &&
      (!el("id_date_semis_couvert").value ||
        !el("id_date_destruction_couvert").value);
    if (incompletes) form.setAttribute("data-couvert-dates-incompletes", "1");
    else form.removeAttribute("data-couvert-dates-incompletes");
  }

  function mettreAJourBouton() {
    majGatingDates();
    document.dispatchEvent(new Event("nitrates:form-revealed"));
  }

  // ─── Init ────────────────────────────────────────────────────────────────

  function initFlow() {
    rendreQ1();
    // Replay depuis l'URL (retour arrière / lien partagé) : si categorie_culture
    // est déjà résolu côté cascade, on repositionne le flow en conséquence.
    replayDepuisEtat();
    mettreAJourBouton();

    // #272 : quand reset_form invalide un résultat suite au changement d'une
    // question du flow (retour en mode saisie), on ré-affiche les dates Q4 à
    // gauche (elles étaient masquées sur la page résultat) pour que
    // l'utilisateur complète un parcours cohérent avant de relancer.
    document.addEventListener("nitrates:retour-saisie", function () {
      if (valeurFlow("cflow_destination") !== "couvert") return;
      if (!valeurFlow("cflow_type_couvert")) return;
      if (!valeurFlow("cflow_couvert_recolte")) return;
      montrerDatesGauche(); // resultatAffiche() est maintenant false -> montre
      appliquerCouvert();
      mettreAJourBouton();
    });
  }

  // Reconstruit l'état du flow à partir des valeurs déjà présentes (params URL
  // rejoués par cascade.js dans les hidden inputs / radios réels).
  function replayDepuisEtat() {
    var initial = window.NITRATES_INITIAL_DATA || {};
    var cat = initial.categorie_culture;
    if (!cat) return;
    var estCouvert =
      cat === "couvert_intercultures_longue" ||
      cat === "couvert_intercultures_courte";
    // Q1
    var destVal = estCouvert ? "couvert" : "culture_principale";
    cocherFlow("cflow_destination", destVal);
    if (estCouvert) {
      rendreQ2Couvert();
      montrer("q_type_couvert");
      cocherFlow("cflow_type_couvert", cat);
      rendreQ3();
      montrer("q_couvert_recolte");
      // Q3 + Q4 depuis sous_culture_form initial.
      replayCouvertDepuisSousCulture(cat, initial.sous_culture_form);
    } else {
      rendreQ2Culture();
      montrer("q_type_couvert");
      cocherFlow("cflow_type_couvert", cat);
      var cats = (referentiels || {}).categories_cultures || {};
      var sousCles = (cats[cat] || {}).sous_cultures || [];
      if (sousCles.length > 0) {
        rendreQ3Culture(sousCles);
        montrer("q_sous_culture");
        if (initial.sous_culture_form) {
          cocherFlow("cflow_sous_culture", initial.sous_culture_form);
        }
      }
    }
  }

  function cocherFlow(name, val) {
    var r = document.querySelector(
      'input[type="radio"][name="' + name + '"][value="' + val + '"]'
    );
    if (r) r.checked = true;
  }

  function replayCouvertDepuisSousCulture(cat, sousCulture) {
    if (!sousCulture) return;
    if (cat === "couvert_intercultures_courte") {
      var recolteCourte =
        sousCulture === "couvert_courte_recolte" ? "recolte" : "non_recolte";
      cocherFlow("cflow_couvert_recolte", recolteCourte);
      montrerDatesGauche(); // masqué sur page résultat (doublon calendrier droite)
      return;
    }
    // Longue : couvert_{recolte|non_recolte}_{presence}
    var m = /^couvert_(recolte|non_recolte)_/.exec(sousCulture);
    if (m) {
      cocherFlow("cflow_couvert_recolte", m[1]);
      montrerDatesGauche();
      // Les dates elles-mêmes viennent des hidden inputs (params URL), déjà
      // pré-remplis côté template -> renderDatesForm les a repris.
    }
  }

  // ─── Boot ──────────────────────────────────────────────────────────────
  // Le flow a besoin des référentiels (libellés catégories culture). cascade.js
  // les fetche déjà ; on refait un fetch léger (même URL, mise en cache HTTP)
  // pour rester découplé, puis on initialise dès que le container Q1 existe.

  function boot() {
    var q1 = el("q_destination_epandage");
    if (!q1) return;
    fetch(window.NITRATES_REFERENTIELS_URL)
      .then(function (r) {
        return r.json();
      })
      .then(function (r) {
        referentiels = r;
        initFlow();
      })
      .catch(function (err) {
        console.error("couvert-flow : échec chargement référentiels", err);
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
