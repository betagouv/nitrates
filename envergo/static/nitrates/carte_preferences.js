// Preferences de la carte du simulateur (#531, amelioration carto).
//
// 1. Couches memorisees : le fond (plan / photo) et les surcouches (RPG,
//    communes, ZV, ZAR) choisis dans la legende sont gardes en localStorage.
//    Quand on revient sur le formulaire (modifier depuis les resultats, retour
//    arriere, nouvelle recherche), la carte les reaffiche au lieu du reglage
//    par defaut. Rien de memorise (ou storage indisponible) -> COUCHES_PAR_DEFAUT :
//    mode « Automatique » (cf. couchesAuto) + RPG, communes, ZV et ZAR cochees.
//
// 2. Clavier : quand la carte a le focus, fleches (avec ou sans Ctrl) pour se
//    deplacer, + / - (avec ou sans Ctrl) pour zoomer, Entree pour pointer le
//    centre de la carte, F pour le plein ecran, L pour aller a la legende. Le
//    handler clavier natif de Leaflet reste coupe (keyboard: false, #154) : on
//    ne reagit QUE quand le focus est sur le conteneur carte lui-meme, jamais
//    dans la legende ni le formulaire.
//
// Pas de DOM ici : simulator.js branche ces helpers sur la carte. En Node
// (tests unitaires), on exporte les memes helpers. cf. reset_form.js.
(function () {
  "use strict";

  // Versions des couches memorisees (#583). Les choix d'une version
  // precedente sont repris, avec les couches arrivees depuis cochees en plus :
  //  - v2 : case « Parcelles agricoles (RPG) »
  //  - v3 : case « Communes », qui remplace « Cadastre »
  const STORAGE_KEY = "nitrates.carte.couches.v3";
  const ANCIENNES_VERSIONS = [
    { cle: "nitrates.carte.couches.v2", ajouts: ["communes"] },
    { cle: "nitrates.carte.couches.v1", ajouts: ["rpg", "communes"] },
  ];
  const PAN_PX = 100;

  // Mode « Automatique » (fond par defaut) : on charge le minimum selon le zoom.
  // Mesure des tuiles data.geopf.fr (09/2026, zooms 6 a 17) : la photo aerienne
  // en JPEG pese 11-23 Ko/tuile, le Plan IGN en PNG 32-71 Ko/tuile, soit 2 a 3x
  // plus. La photo reste donc le fond le plus leger a tous les zooms.
  // #583 : le mode auto ne gere plus que le fond. Parcelles RPG et communes
  // suivent uniquement leur case dans la legende (cochees par defaut).
  function couchesAuto() {
    return { fond: "photo" };
  }

  // 1re visite (rien de memorise) : parcelles RPG, communes, ZV et ZAR
  // affichees d'office, c'est ce que l'utilisateur vient chercher. Il peut les
  // decocher, c'est alors memorise.
  const COUCHES_PAR_DEFAUT = {
    base: "auto",
    surcouches: ["rpg", "communes", "zv", "zar"],
  };

  function couchesParDefaut() {
    return { base: COUCHES_PAR_DEFAUT.base, surcouches: COUCHES_PAR_DEFAUT.surcouches.slice() };
  }

  // Ne garde que des cles connues : une cle renommee/supprimee cote carte ne
  // doit pas casser le chargement, elle est juste ignoree.
  function normaliserCouches(raw, basesConnues, surcouchesConnues) {
    if (!raw || typeof raw !== "object") return null;
    const base = basesConnues.includes(raw.base) ? raw.base : null;
    if (!base) return null;
    const surcouches = Array.isArray(raw.surcouches)
      ? raw.surcouches.filter(
          (k, i, arr) => surcouchesConnues.includes(k) && arr.indexOf(k) === i
        )
      : [];
    return { base: base, surcouches: surcouches };
  }

  function lireCouches(storage, basesConnues, surcouchesConnues) {
    try {
      const txt = storage && storage.getItem(STORAGE_KEY);
      if (txt) return normaliserCouches(JSON.parse(txt), basesConnues, surcouchesConnues);
      // Choix d'une version precedente : repris, nouvelles couches en plus.
      for (const ancienne of ANCIENNES_VERSIONS) {
        const vieux = storage && storage.getItem(ancienne.cle);
        if (!vieux) continue;
        const couches = normaliserCouches(JSON.parse(vieux), basesConnues, surcouchesConnues);
        if (!couches) return null;
        ancienne.ajouts.forEach((k) => {
          if (surcouchesConnues.includes(k) && !couches.surcouches.includes(k)) {
            couches.surcouches.push(k);
          }
        });
        // Ordre de la legende, pas d'ajout.
        couches.surcouches.sort(
          (a, b) => surcouchesConnues.indexOf(a) - surcouchesConnues.indexOf(b)
        );
        return couches;
      }
      return null;
    } catch (e) {
      return null;
    }
  }

  function ecrireCouches(storage, couches) {
    try {
      if (storage) storage.setItem(STORAGE_KEY, JSON.stringify(couches));
    } catch (e) {
      // navigation privee / quota : on perd juste la memorisation.
    }
  }

  // Traduit un keydown en action carte, ou null si la touche ne nous concerne
  // pas (on laisse alors le navigateur faire, ex. Tab). Cmd (Mac) vaut Ctrl.
  // Alt est ignore : Alt+fleche = navigation historique sur certains OS.
  function actionClavier(e) {
    if (!e || e.altKey) return null;
    switch (e.key) {
      case "ArrowUp":
        return { type: "pan", dx: 0, dy: -PAN_PX };
      case "ArrowDown":
        return { type: "pan", dx: 0, dy: PAN_PX };
      case "ArrowLeft":
        return { type: "pan", dx: -PAN_PX, dy: 0 };
      case "ArrowRight":
        return { type: "pan", dx: PAN_PX, dy: 0 };
      // "=" : touche +/= sans Maj (QWERTY) ; "Add"/"Subtract" : vieux pave num.
      case "+":
      case "=":
      case "Add":
        return { type: "zoom", delta: 1 };
      case "-":
      case "_":
      case "Subtract":
        return { type: "zoom", delta: -1 };
      case "Enter":
        if (e.ctrlKey || e.metaKey || e.shiftKey) return null;
        return { type: "pointer" };
      // Lettres sans modificateur seulement : Ctrl/Cmd+L = barre d'adresse,
      // Ctrl/Cmd+F = recherche du navigateur.
      case "f":
      case "F":
        if (e.ctrlKey || e.metaKey) return null;
        return { type: "pleinEcran" };
      case "l":
      case "L":
        if (e.ctrlKey || e.metaKey) return null;
        return { type: "legende" };
      default:
        return null;
    }
  }

  // Panneau d'aide clavier (#531) : raccourcis utiles selon l'endroit ou est
  // le focus. contexte : "carte" | "legende" | "bouton". En plein ecran
  // natif, Echap est pris par le navigateur (sortie du plein ecran) : on
  // propose C pour revenir de la legende a la carte.
  function aideClavier(contexte, pleinEcran) {
    const sortie = pleinEcran ? [["Échap", "quitter le plein écran"]] : [];
    if (contexte === "legende") {
      return [
        ["↑ ↓", "changer de fond de carte"],
        ["Espace", "cocher / décocher"],
        [pleinEcran ? "C" : "Échap ou C", "revenir à la carte"],
      ].concat(sortie);
    }
    if (contexte === "bouton") {
      return [
        ["Entrée", pleinEcran ? "quitter le plein écran" : "plein écran"],
        ["Tab", "couches de la carte"],
      ].concat(sortie);
    }
    return [
      ["← ↑ → ↓", "se déplacer"],
      ["+ −", "zoomer"],
      ["Entrée", "choisir le point au centre"],
      ["F", pleinEcran ? "quitter le plein écran" : "plein écran"],
      ["L", "couches de la carte"],
    ].concat(sortie);
  }

  const api = {
    STORAGE_KEY: STORAGE_KEY,
    ANCIENNES_VERSIONS: ANCIENNES_VERSIONS,
    normaliserCouches: normaliserCouches,
    lireCouches: lireCouches,
    ecrireCouches: ecrireCouches,
    actionClavier: actionClavier,
    couchesAuto: couchesAuto,
    couchesParDefaut: couchesParDefaut,
    aideClavier: aideClavier,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    window.NitratesCartePrefs = api;
  }
})();
