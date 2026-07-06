// Hack FRONT (UI seulement) : scinde "Precisez le type de culture" en 2 mini
// questions pour les couverts d'interculture longue.
//
// Pourquoi : la categorie "couvert d'interculture longue" propose 4 sous-types
// dont les libelles sont longs et confusants (recolte/non recolte croise avec
// "plus en place apres le 31/12" / "toujours en place apres le 01/01"). Plutot
// que de complexifier l'arbre YAML (qui marche), on garde EXACTEMENT le meme
// champ `sous_culture_form` a 4 valeurs, mais on le saisit via deux questions
// binaires, puis on recompose la valeur et on coche le vrai radio.
//
// INERTE pour le reste du formulaire : on ne touche ni au YAML, ni a
// cascade.js. Les 4 radios d'origine restent dans le DOM (caches) et c'est en
// cochant l'un d'eux + dispatch de son `change` que toute la mecanique
// existante (resolution hidden inputs, cascade fertilisant, auto-scroll) se
// declenche, comme si l'utilisateur avait clique le radio directement.
//
// Les 4 valeurs suivent le motif :
//   couvert_{recolte|non_recolte}_{plus_en_place_apres_3112|toujours_en_place_apres_0101}

(function () {
  "use strict";

  var CATEGORIE = "couvert_intercultures_longue";
  var CONTAINER_SEL = '[data-cascade="sous_culture_form"]';

  // Axe A : recolte ?  -> fragment de valeur
  var AXE_RECOLTE = [
    {
      val: "recolte",
      label: "Couvert récolté, fauché ou pâturé (dérobée, CIVE…)",
    },
    {
      val: "non_recolte",
      label: "Couvert ni récolté, ni fauché, ni pâturé (CIPAN, engrais vert…)",
    },
  ];
  // Axe B : encore en place apres l'hiver ? -> fragment de valeur
  var AXE_PRESENCE = [
    {
      val: "toujours_en_place_apres_0101",
      label: "Toujours en place après le 1ᵉʳ janvier",
    },
    {
      val: "plus_en_place_apres_3112",
      label: "Plus en place après le 31 décembre",
    },
  ];

  function valeurComposee(recolte, presence) {
    return "couvert_" + recolte + "_" + presence;
  }

  // Decompose une valeur sous_culture_form en (recolte, presence) ou null.
  function decomposer(valeur) {
    var m = /^couvert_(recolte|non_recolte)_(plus_en_place_apres_3112|toujours_en_place_apres_0101)$/.exec(
      valeur || ""
    );
    return m ? { recolte: m[1], presence: m[2] } : null;
  }

  function categorieCourante() {
    var r = document.querySelector(
      'input[type="radio"][name="categorie_culture"]:checked'
    );
    return r ? r.value : "";
  }

  // Construit (une seule fois) le bloc des 2 sous-questions, insere avant le
  // conteneur des radios d'origine (qu'on masque).
  function construireSplit(container) {
    var wrap = document.createElement("div");
    wrap.className = "couvert-split";
    wrap.dataset.couvertSplit = "1";

    function groupe(titre, axe, name) {
      var g = document.createElement("div");
      g.className = "form-question-group couvert-split__group";
      var p = document.createElement("p");
      p.className = "form-question-text";
      p.textContent = titre;
      g.appendChild(p);
      axe.forEach(function (opt) {
        var rg = document.createElement("div");
        rg.className = "fr-radio-group";
        var input = document.createElement("input");
        input.type = "radio";
        input.name = name;
        input.id = "id_" + name + "__" + opt.val;
        input.value = opt.val;
        // Carte #154 (a11y) : meme modele clavier que le form principal
        // (cascade.js). Sans ca, les radios du split (construits ici) gardaient
        // le comportement natif : Tab sautait tout le groupe et Entree ne
        // cochait pas -> seule la fleche marchait.
        input.tabIndex = 0;
        input.addEventListener("change", onSplitChange);
        input.addEventListener("keydown", function (e) {
          onSplitRadioKeydown(e, input, name);
        });
        var label = document.createElement("label");
        label.className = "fr-label";
        label.htmlFor = input.id;
        label.textContent = opt.label;
        rg.appendChild(input);
        rg.appendChild(label);
        g.appendChild(rg);
      });
      return g;
    }

    wrap.appendChild(
      groupe(
        "Le couvert est-il récolté, fauché ou pâturé ?",
        AXE_RECOLTE,
        "couvert_split_recolte"
      )
    );
    wrap.appendChild(
      groupe(
        "Est-il encore en place après le 1er janvier ?",
        AXE_PRESENCE,
        "couvert_split_presence"
      )
    );
    container.parentNode.insertBefore(wrap, container);
    return wrap;
  }

  function valeur(name) {
    var r = document.querySelector(
      'input[type="radio"][name="' + name + '"]:checked'
    );
    return r ? r.value : "";
  }

  // Ordre des 2 sous-questions du split (pour le saut Entree "groupe suivant").
  var SPLIT_NAMES = ["couvert_split_recolte", "couvert_split_presence"];

  function radiosSplit(name) {
    return Array.prototype.slice.call(
      document.querySelectorAll('input[type="radio"][name="' + name + '"]')
    );
  }

  // Modele clavier des radios du split (Carte #154, a11y), aligne sur cascade.js :
  //  - Entree : coche + saut au 1er radio de la sous-question suivante ; si
  //    c'etait la derniere (presence), les 2 axes sont repondus -> onSplitChange
  //    a coche le vrai radio et revele le fertilisant : on focus son 1er radio
  //    (ou le bouton si rien en aval).
  //  - Tab / fleches : navigation dans la sous-question courante.
  function onSplitRadioKeydown(e, input, name) {
    if (e.key === "Enter") {
      e.preventDefault();
      if (!input.checked) {
        input.checked = true;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
      Promise.resolve().then(function () {
        var idx = SPLIT_NAMES.indexOf(name);
        var suivantName = SPLIT_NAMES[idx + 1];
        if (suivantName) {
          var rs = radiosSplit(suivantName);
          if (rs.length) {
            rs[0].focus();
            return;
          }
        }
        // Derniere sous-question repondue : le fertilisant vient d'etre revele
        // par cascade.js (via onSplitChange). On lui passe le focus.
        focusApresSplit();
      });
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Tab") {
      var radios = radiosSplit(name);
      var i = radios.indexOf(input);
      if (i === -1) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        radios[(i + 1) % radios.length].focus();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        radios[(i - 1 + radios.length) % radios.length].focus();
      } else if (e.key === "Tab") {
        if (e.shiftKey) {
          if (i > 0) {
            e.preventDefault();
            radios[i - 1].focus();
          }
        } else if (i < radios.length - 1) {
          e.preventDefault();
          radios[i + 1].focus();
        }
      }
    }
  }

  // Apres le split complet : focus sur le 1er radio du fertilisant (revele par
  // la cascade), sinon sur le bouton "Lancer".
  function focusApresSplit() {
    var fert = document.querySelector(
      '[data-cascade="categorie_fertilisant"] input[type="radio"]'
    );
    if (fert && fert.offsetParent !== null) {
      fert.focus();
      return;
    }
    var btn = document.querySelector(
      "#form-submit-row button[type=submit]"
    );
    if (btn && !btn.disabled) btn.focus();
  }

  // Quand les 2 axes sont repondus : recompose la valeur, coche le vrai radio
  // d'origine et dispatch son `change` -> cascade.js prend le relais.
  function onSplitChange() {
    var r = valeur("couvert_split_recolte");
    var p = valeur("couvert_split_presence");
    if (!r || !p) return;
    var cible = valeurComposee(r, p);
    var radioReel = document.querySelector(
      'input[type="radio"][name="sous_culture_form"][value="' + cible + '"]'
    );
    if (!radioReel) return;
    if (!radioReel.checked) {
      radioReel.checked = true;
      radioReel.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  // Applique le split sur le conteneur de radios sous_culture_form : masque les
  // 4 radios d'origine, monte les 2 sous-questions, et pre-coche si une valeur
  // est deja selectionnee (replay depuis l'URL).
  function appliquer(container) {
    if (categorieCourante() !== CATEGORIE) return;
    // Pas de radios rendus (cascade pas encore passee) -> rien a faire.
    var radios = container.querySelectorAll(
      'input[type="radio"][name="sous_culture_form"]'
    );
    if (radios.length === 0) return;

    // Masque les radios d'origine (conserves comme source de verite).
    container.classList.add("couvert-split__origin-hidden");

    // (Re)construit le bloc split s'il n'existe pas deja a cote.
    var split = container.parentNode.querySelector(
      '[data-couvert-split="1"]'
    );
    if (!split) split = construireSplit(container);

    // Pre-cochage depuis la valeur deja selectionnee (replay URL / retour).
    var dejaCoche = container.querySelector(
      'input[type="radio"][name="sous_culture_form"]:checked'
    );
    var parts = decomposer(dejaCoche ? dejaCoche.value : "");
    if (parts) {
      var rr = split.querySelector(
        'input[name="couvert_split_recolte"][value="' + parts.recolte + '"]'
      );
      var pp = split.querySelector(
        'input[name="couvert_split_presence"][value="' + parts.presence + '"]'
      );
      if (rr) rr.checked = true;
      if (pp) pp.checked = true;
    }
  }

  // Retire le split (quand on quitte la categorie interculture longue).
  function retirer(container) {
    var split = container.parentNode.querySelector(
      '[data-couvert-split="1"]'
    );
    if (split) split.remove();
    container.classList.remove("couvert-split__origin-hidden");
  }

  function synchroniser() {
    var container = document.querySelector(CONTAINER_SEL);
    if (!container) return;
    if (categorieCourante() === CATEGORIE) appliquer(container);
    else retirer(container);
  }

  function init() {
    var container = document.querySelector(CONTAINER_SEL);
    if (!container) return;
    // cascade.js re-rend les radios dynamiquement (fetch referentiels, puis a
    // chaque changement amont). On observe le conteneur pour (re)appliquer le
    // split apres chaque rendu.
    var obs = new MutationObserver(function () {
      synchroniser();
    });
    obs.observe(container, { childList: true });
    // Et on observe le choix de categorie pour basculer in/out.
    document.addEventListener("change", function (e) {
      if (e.target && e.target.name === "categorie_culture") {
        // laisse cascade.js rendre les nouveaux radios d'abord
        setTimeout(synchroniser, 0);
      }
    });
    synchroniser();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
