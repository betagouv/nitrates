// Preferences de la carte du simulateur (#531, amelioration carto).
//
// 1. Couches memorisees : le fond (plan / photo) et les surcouches (cadastre,
//    ZV, ZAR) choisis dans la legende sont gardes en localStorage. Quand on
//    revient sur le formulaire (modifier depuis les resultats, retour arriere,
//    nouvelle recherche), la carte les reaffiche au lieu du reglage par defaut.
//    Rien de memorise (ou storage indisponible) -> reglage par defaut.
//
// 2. Clavier : quand la carte a le focus, fleches (avec ou sans Ctrl) pour se
//    deplacer, + / - (avec ou sans Ctrl) pour zoomer, Entree pour pointer le
//    centre de la carte. Le handler clavier natif de Leaflet reste coupe
//    (keyboard: false, #154) : on ne reagit QUE quand le focus est sur le
//    conteneur carte lui-meme, jamais dans la legende ni le formulaire.
//
// Pas de DOM ici : simulator.js branche ces helpers sur la carte. En Node
// (tests unitaires), on exporte les memes helpers. cf. reset_form.js.
(function () {
  "use strict";

  const STORAGE_KEY = "nitrates.carte.couches.v1";
  const PAN_PX = 100;

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
      if (!txt) return null;
      return normaliserCouches(JSON.parse(txt), basesConnues, surcouchesConnues);
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
      default:
        return null;
    }
  }

  const api = {
    STORAGE_KEY: STORAGE_KEY,
    normaliserCouches: normaliserCouches,
    lireCouches: lireCouches,
    ecrireCouches: ecrireCouches,
    actionClavier: actionClavier,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    window.NitratesCartePrefs = api;
  }
})();
