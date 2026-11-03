/**
 * Tests de logique pure de qc_reponses_precedentes.js (#273).
 *
 * Lancés en Node : `node --test envergo/static/nitrates/*.test.js`.
 */
const test = require("node:test");
const assert = require("node:assert");

const { valeurAReprendre } = require("./qc_reponses_precedentes.js");

test("reprend la reponse donnee si elle fait partie des choix", () => {
  assert.strictEqual(
    valeurAReprendre({ plan_epandage: "icpe_a" }, "plan_epandage", [
      "icpe_a",
      "icpe_ed",
      "autre",
    ]),
    "icpe_a"
  );
});

test("ne reprend rien si la question n'a pas encore ete repondue", () => {
  assert.strictEqual(
    valeurAReprendre({ fertirrigation: "True" }, "plan_epandage", ["icpe_a"]),
    null
  );
  assert.strictEqual(valeurAReprendre({}, "plan_epandage", ["icpe_a"]), null);
});

test("ne reprend pas une valeur absente des choix de la nouvelle question", () => {
  // Meme champ, autre jeu de reponses selon l'arbre (cf. plan_epandage, #620).
  assert.strictEqual(
    valeurAReprendre({ plan_epandage: "non_concerne" }, "plan_epandage", [
      "icpe_a",
      "autre",
    ]),
    null
  );
});

test("compare sans casse (True / true) et rend la valeur du choix", () => {
  assert.strictEqual(
    valeurAReprendre({ fertirrigation: "true" }, "fertirrigation", [
      "True",
      "False",
    ]),
    "True"
  );
});

test("valeur vide ou memoire absente -> rien", () => {
  assert.strictEqual(valeurAReprendre({ x: "" }, "x", [""]), null);
  assert.strictEqual(valeurAReprendre(null, "x", ["a"]), null);
});
