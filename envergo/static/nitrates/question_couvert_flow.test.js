/**
 * Tests de la logique pure des reponses Q1 du flow « Culture ou couvert »
 * (carte #430, bug 3 : la reponse « juste avant » devenait « sur » au retour
 * depuis le resultat).
 *
 * Lances en Node (le JS statique servi en dev peut etre perime, cf.
 * feedback_static_js_cache_dev) :
 *   node --test envergo/static/nitrates/question_couvert_flow.test.js
 *
 * Le module source detecte Node et n'exporte alors que ses fonctions pures
 * (sans toucher au DOM ni a window).
 */
const test = require("node:test");
const assert = require("node:assert");

const {
  Q1_OPTIONS,
  destinationMetier,
  premiereReponsePourMetier,
  reponseQ1AuReplay,
} = require("./question_couvert_flow.js");

test("chaque reponse Q1 a une valeur UNIQUE", () => {
  // C'est l'invariant qui corrige le bug : tant que « sur X » et « juste avant
  // X » partageaient la meme value, aucun replay ne pouvait les distinguer.
  const vals = Q1_OPTIONS.map((o) => o.val);
  assert.strictEqual(
    new Set(vals).size,
    vals.length,
    "valeurs Q1 dupliquees : " + vals.join(", ")
  );
});

test("les 5 reponses Q1 se ramenent aux 3 valeurs metier", () => {
  assert.deepStrictEqual(
    Q1_OPTIONS.map((o) => [o.val, o.metier]),
    [
      ["couvert_sur", "couvert"],
      ["couvert_avant", "couvert"],
      ["culture_principale_sur", "culture_principale"],
      ["culture_principale_avant", "culture_principale"],
      ["sol_non_cultive", "sol_non_cultive"],
    ]
  );
});

test("destinationMetier : normalise vers la valeur metier", () => {
  assert.strictEqual(destinationMetier("couvert_avant"), "couvert");
  assert.strictEqual(destinationMetier("couvert_sur"), "couvert");
  assert.strictEqual(
    destinationMetier("culture_principale_avant"),
    "culture_principale"
  );
  assert.strictEqual(destinationMetier("sol_non_cultive"), "sol_non_cultive");
});

test("destinationMetier : les anciennes valeurs d'URL restent lisibles", () => {
  // Retro-compat : une URL partagee avant #430 porte `cflow_destination=couvert`.
  // Elle doit continuer a piloter la bonne branche (seule la distinction
  // sur/avant est perdue, comme avant le fix).
  assert.strictEqual(destinationMetier("couvert"), "couvert");
  assert.strictEqual(
    destinationMetier("culture_principale"),
    "culture_principale"
  );
  assert.strictEqual(destinationMetier(""), "");
  assert.strictEqual(destinationMetier(undefined), "");
});

test("premiereReponsePourMetier : repli sur la 1ere reponse de la famille", () => {
  assert.strictEqual(premiereReponsePourMetier("couvert"), "couvert_sur");
  assert.strictEqual(
    premiereReponsePourMetier("culture_principale"),
    "culture_principale_sur"
  );
  assert.strictEqual(premiereReponsePourMetier("inconnu"), "");
});

test("replay : la reponse « juste avant » est PRESERVEE (bug 3)", () => {
  // Cas exact de la carte : l'utilisateur avait repondu « juste avant
  // l'implantation d'une culture principale ». Au retour « modifier », les
  // champs cascade ne disent que « culture_principale » -> sans la valeur
  // exacte de l'URL, on recochait « Sur une culture principale ».
  assert.strictEqual(
    reponseQ1AuReplay("culture_principale", "culture_principale_avant"),
    "culture_principale_avant"
  );
  assert.strictEqual(
    reponseQ1AuReplay("couvert", "couvert_avant"),
    "couvert_avant"
  );
});

test("replay : la reponse « sur » est preservee aussi", () => {
  assert.strictEqual(
    reponseQ1AuReplay("culture_principale", "culture_principale_sur"),
    "culture_principale_sur"
  );
});

test("replay : sans reponse dans l'URL, repli sur la 1ere de la famille", () => {
  // Cas d'une URL pilotee uniquement par les champs backend (cf. form_backfill) :
  // pas de cflow_destination, on ne peut pas deviner sur/avant.
  assert.strictEqual(
    reponseQ1AuReplay("culture_principale", ""),
    "culture_principale_sur"
  );
  assert.strictEqual(reponseQ1AuReplay("couvert", ""), "couvert_sur");
});

test("replay : une ANCIENNE valeur d'URL retombe sur le repli, pas sur elle-meme", () => {
  // Regression attrapee en e2e : `destinationMetier("culture_principale")`
  // renvoie bien "culture_principale" (retro-compat), donc la comparaison de
  // famille passait et on renvoyait la valeur telle quelle -> aucun radio ne
  // porte plus cette value, donc AUCUNE reponse Q1 n'etait cochee. Il faut une
  // vraie reponse Q1.
  assert.strictEqual(
    reponseQ1AuReplay("culture_principale", "culture_principale"),
    "culture_principale_sur"
  );
  assert.strictEqual(reponseQ1AuReplay("couvert", "couvert"), "couvert_sur");
});

test("replay : URL incoherente avec la cascade -> on suit la cascade", () => {
  // Les champs cascade sont la source de verite backend. Si l'URL porte une
  // reponse Q1 d'une autre famille (URL bricolee a la main, ou cascade modifiee
  // ailleurs), on ne recoche pas une reponse qui contredirait la branche reelle.
  assert.strictEqual(
    reponseQ1AuReplay("culture_principale", "couvert_avant"),
    "culture_principale_sur"
  );
  assert.strictEqual(
    reponseQ1AuReplay("couvert", "sol_non_cultive"),
    "couvert_sur"
  );
});
