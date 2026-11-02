/**
 * Tests de logique pure de soumission_partielle.js (#273).
 *
 * Lancés en Node : `node --test envergo/static/nitrates/*.test.js`.
 */
const test = require("node:test");
const assert = require("node:assert");

const { actionSynchro, memePage } = require("./soumission_partielle.js");

test("actionSynchro : remplace ce qui existe des deux cotes", () => {
  assert.strictEqual(actionSynchro(true, true), "remplacer");
});

test("actionSynchro : ajoute ce qui apparait (ex. colonne resultat)", () => {
  assert.strictEqual(actionSynchro(false, true), "ajouter");
});

test("actionSynchro : retire ce qui disparait (ex. QC repondue -> resultat)", () => {
  assert.strictEqual(actionSynchro(true, false), "retirer");
});

test("actionSynchro : rien a faire si absent des deux cotes", () => {
  assert.strictEqual(actionSynchro(false, false), null);
});

const ORIGINE = "https://nitrates.beta.gouv.fr";

test("memePage : meme chemin, parametres differents -> meme page", () => {
  assert.strictEqual(
    memePage(
      "/simulateur/?lat=1&lng=2",
      "https://nitrates.beta.gouv.fr/simulateur/?lat=1&lng=2&x=3",
      ORIGINE
    ),
    true
  );
});

test("memePage : redirection vers la connexion -> autre page", () => {
  assert.strictEqual(
    memePage(
      "/simulateur/?lat=1",
      "https://nitrates.beta.gouv.fr/connexion/?next=/simulateur/",
      ORIGINE
    ),
    false
  );
});

test("memePage : racine publique / -> reste sur /", () => {
  assert.strictEqual(
    memePage("/?lat=1", "https://nitrates.beta.gouv.fr/?lat=1", ORIGINE),
    true
  );
});

test("memePage : autre origine ou URL absente -> faux", () => {
  assert.strictEqual(
    memePage("/simulateur/", "https://ailleurs.example/simulateur/", ORIGINE),
    false
  );
  assert.strictEqual(memePage(null, "/simulateur/", ORIGINE), false);
  assert.strictEqual(memePage("/simulateur/", "", ORIGINE), false);
});
