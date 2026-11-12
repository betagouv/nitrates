/**
 * Tests du relais des events metier vers Matomo (nitrates_analytics.js).
 *
 *   node --test envergo/static/nitrates/nitrates_analytics.test.js
 *
 * Le module est une IIFE navigateur : on l'execute dans un bac a sable vm avec
 * un window/document minimal, puis on rejoue l'ordre de chargement reel de la
 * prod (ce script en defer AVANT matomo.js en async).
 */
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = fs.readFileSync(path.join(__dirname, "nitrates_analytics.js"), "utf8");

function chargerModule() {
  const ecouteurs = {};
  const document = {
    title: "Simulateur",
    addEventListener(type, fn) {
      (ecouteurs[type] = ecouteurs[type] || []).push(fn);
    },
  };
  const stockage = new Map();
  const window = {
    location: { href: "https://nitrates.beta.gouv.fr/" },
    localStorage: {
      getItem: (k) => (stockage.has(k) ? stockage.get(k) : null),
      setItem: (k, v) => stockage.set(k, String(v)),
    },
  };
  vm.runInNewContext(SOURCE, { window, document });
  const emettre = (type, detail) => (ecouteurs[type] || []).forEach((fn) => fn({ detail }));
  return { window, emettre };
}

// Les tableaux crees dans le bac a sable vm n'ont pas le prototype Array du
// test : on les recopie avant de comparer.
const copie = (cmds) => JSON.parse(JSON.stringify(cmds));

// Ce que fait matomo.js en se chargeant : il depile le tableau existant puis
// remplace window._paq par un objet dont push() envoie directement.
function chargerMatomo(window) {
  const recus = [...window._paq];
  window._paq = { push: (cmd) => recus.push(cmd) };
  return recus;
}

test("un event emis apres le chargement de matomo.js arrive a Matomo", () => {
  const { window, emettre } = chargerModule();
  const recus = chargerMatomo(window);

  emettre("nitrates:simulation-lancee", { department: "62" });

  assert.deepStrictEqual(copie(recus), [
    ["alwaysUseSendBeacon"],
    ["trackEvent", "Simulateur", "SimulationLancee", "62"],
  ]);
});

test("Simulation2Plus part une seule fois, au passage a la 2e simulation", () => {
  const { window, emettre } = chargerModule();
  const recus = chargerMatomo(window);

  emettre("nitrates:simulation-lancee", { department: "59" });
  emettre("nitrates:simulation-lancee", { department: "59" });
  emettre("nitrates:simulation-lancee", { department: "59" });

  const plus = recus.filter((c) => c[2] === "Simulation2Plus");
  assert.strictEqual(plus.length, 1);
});

test("la page vue htmx (#273) arrive aussi a Matomo", () => {
  const { window, emettre } = chargerModule();
  const recus = chargerMatomo(window);

  emettre("nitrates:rendu-remplace", { url: "https://nitrates.beta.gouv.fr/?lat=1", urlPrecedente: "https://nitrates.beta.gouv.fr/" });

  assert.deepStrictEqual(copie(recus.slice(1)), [
    ["setReferrerUrl", "https://nitrates.beta.gouv.fr/"],
    ["setCustomUrl", "https://nitrates.beta.gouv.fr/?lat=1"],
    ["setDocumentTitle", "Simulateur"],
    ["trackPageView"],
  ]);
});

test("avant le chargement de matomo.js, les events restent en file", () => {
  const { window, emettre } = chargerModule();

  emettre("nitrates:recherche-commune");

  assert.deepStrictEqual(copie(window._paq.slice(-1)), [["trackEvent", "Simulateur", "RechercheCommune"]]);
});
