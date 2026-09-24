/**
 * Tests des helpers purs de la carte du simulateur (#531) :
 *   node --test envergo/static/nitrates/carte_preferences.test.js
 */
const test = require("node:test");
const assert = require("node:assert");
const prefs = require("./carte_preferences.js");

const BASES = ["auto", "plan", "photo"];
const SURCOUCHES = ["cadastre", "zv", "zar"];

function fakeStorage(initial) {
  const data = Object.assign({}, initial);
  return {
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => {
      data[k] = String(v);
    },
    data,
  };
}

test("rien de memorise -> null (reglage par defaut)", () => {
  assert.strictEqual(prefs.lireCouches(fakeStorage(), BASES, SURCOUCHES), null);
  assert.strictEqual(prefs.lireCouches(null, BASES, SURCOUCHES), null);
});

test("aller-retour ecriture / lecture", () => {
  const s = fakeStorage();
  prefs.ecrireCouches(s, { base: "plan", surcouches: ["zv", "zar"] });
  assert.deepStrictEqual(prefs.lireCouches(s, BASES, SURCOUCHES), {
    base: "plan",
    surcouches: ["zv", "zar"],
  });
});

test("aucune surcouche cochee est un choix memorise", () => {
  const s = fakeStorage();
  prefs.ecrireCouches(s, { base: "photo", surcouches: [] });
  assert.deepStrictEqual(prefs.lireCouches(s, BASES, SURCOUCHES), {
    base: "photo",
    surcouches: [],
  });
});

test("JSON corrompu ou fond inconnu -> null", () => {
  const k = prefs.STORAGE_KEY;
  assert.strictEqual(
    prefs.lireCouches(fakeStorage({ [k]: "{pas du json" }), BASES, SURCOUCHES),
    null
  );
  assert.strictEqual(
    prefs.lireCouches(
      fakeStorage({ [k]: JSON.stringify({ base: "osm", surcouches: [] }) }),
      BASES,
      SURCOUCHES
    ),
    null
  );
});

test("surcouches inconnues ou en double ignorees", () => {
  const k = prefs.STORAGE_KEY;
  const s = fakeStorage({
    [k]: JSON.stringify({ base: "photo", surcouches: ["rpg", "zv", "zv"] }),
  });
  assert.deepStrictEqual(prefs.lireCouches(s, BASES, SURCOUCHES), {
    base: "photo",
    surcouches: ["zv"],
  });
});

test("storage qui leve (navigation privee) -> pas d'exception", () => {
  const casse = {
    getItem: () => {
      throw new Error("SecurityError");
    },
    setItem: () => {
      throw new Error("QuotaExceeded");
    },
  };
  assert.strictEqual(prefs.lireCouches(casse, BASES, SURCOUCHES), null);
  assert.doesNotThrow(() =>
    prefs.ecrireCouches(casse, { base: "plan", surcouches: [] })
  );
});

test("clavier : fleches avec ou sans Ctrl/Cmd -> deplacement", () => {
  assert.deepStrictEqual(prefs.actionClavier({ key: "ArrowUp" }), {
    type: "pan",
    dx: 0,
    dy: -100,
  });
  assert.deepStrictEqual(
    prefs.actionClavier({ key: "ArrowRight", ctrlKey: true }),
    { type: "pan", dx: 100, dy: 0 }
  );
  assert.deepStrictEqual(
    prefs.actionClavier({ key: "ArrowLeft", metaKey: true }),
    { type: "pan", dx: -100, dy: 0 }
  );
});

test("clavier : + / - (AZERTY, QWERTY, pave num) -> zoom", () => {
  for (const key of ["+", "=", "Add"]) {
    assert.deepStrictEqual(prefs.actionClavier({ key, ctrlKey: true }), {
      type: "zoom",
      delta: 1,
    });
  }
  for (const key of ["-", "_", "Subtract"]) {
    assert.deepStrictEqual(prefs.actionClavier({ key }), {
      type: "zoom",
      delta: -1,
    });
  }
});

test("clavier : Entree seule pointe le centre, pas avec modificateur", () => {
  assert.deepStrictEqual(prefs.actionClavier({ key: "Enter" }), {
    type: "pointer",
  });
  assert.strictEqual(prefs.actionClavier({ key: "Enter", ctrlKey: true }), null);
});

test("clavier : Tab, Alt+fleche et lettres ignores", () => {
  assert.strictEqual(prefs.actionClavier({ key: "Tab" }), null);
  assert.strictEqual(prefs.actionClavier({ key: "a" }), null);
  assert.strictEqual(
    prefs.actionClavier({ key: "ArrowLeft", altKey: true }),
    null
  );
});

test("mode automatique : photo seule en vue large, + cadastre une fois zoome", () => {
  const seuil = prefs.ZOOM_CADASTRE_AUTO;
  assert.deepStrictEqual(prefs.couchesAuto(8), { fond: "photo", cadastre: false });
  assert.deepStrictEqual(prefs.couchesAuto(seuil - 1), {
    fond: "photo",
    cadastre: false,
  });
  assert.deepStrictEqual(prefs.couchesAuto(seuil), { fond: "photo", cadastre: true });
  assert.deepStrictEqual(prefs.couchesAuto(18), { fond: "photo", cadastre: true });
});
