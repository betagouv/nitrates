/**
 * Tests de la logique pure de reconstruction d'URL du reset formulaire (#135).
 *
 * Lances en Node (le JS statique servi en dev peut etre perime, cf.
 * feedback_static_js_cache_dev) :
 *   node --test envergo/static/nitrates/reset_form.test.js
 *
 * Le module source detecte Node et n'exporte alors que ses fonctions pures
 * (sans toucher au DOM ni a window).
 */
const test = require("node:test");
const assert = require("node:assert");

const { construireQueryString, CHAMPS_HIDDEN_DERIVES } = require("./reset_form.js");

// Helper : parse la query string produite en Map cle->[valeurs].
function parametres(qs) {
  const p = new URLSearchParams(qs);
  const m = new Map();
  for (const cle of p.keys()) m.set(cle, p.getAll(cle));
  return m;
}

test("cles UNIQUES : jamais de doublon, derniere valeur gagne", () => {
  // Un dict ne peut pas avoir de cle dupliquee, mais on verifie l'invariant
  // de sortie : chaque cle apparait au plus une fois dans la query string.
  const qs = construireQueryString({
    lat: "49.25",
    lng: "4.03",
    categorie_culture: "culture_hiver",
    sous_culture_form: "colza",
    occupation_sol: "culture_principale",
    sous_culture: "colza",
    type_fertilisant: "type_III",
  });
  const m = parametres(qs);
  for (const [cle, valeurs] of m) {
    assert.strictEqual(
      valeurs.length,
      1,
      `la cle ${cle} apparait ${valeurs.length} fois (attendu 1)`
    );
  }
});

test("inclut les hidden derives quand ils sont remplis", () => {
  const qs = construireQueryString({
    lat: "49.25",
    lng: "4.03",
    categorie_culture: "culture_hiver",
    sous_culture_form: "colza",
    occupation_sol: "culture_principale",
    sous_culture: "colza",
  });
  const m = parametres(qs);
  assert.deepStrictEqual(m.get("occupation_sol"), ["culture_principale"]);
  assert.deepStrictEqual(m.get("sous_culture"), ["colza"]);
});

test("ignore les valeurs vides / null / undefined", () => {
  const qs = construireQueryString({
    lat: "49.25",
    lng: "4.03",
    code_insee: "",
    categorie_culture: "culture_hiver",
    sous_culture_form: undefined,
    occupation_sol: null,
    type_fertilisant: "",
  });
  const m = parametres(qs);
  assert.ok(m.has("lat"));
  assert.ok(m.has("categorie_culture"));
  assert.ok(!m.has("code_insee"), "code_insee vide ne doit pas etre present");
  assert.ok(!m.has("sous_culture_form"));
  assert.ok(!m.has("occupation_sol"));
  assert.ok(!m.has("type_fertilisant"));
});

test("dict vide -> query string vide", () => {
  assert.strictEqual(construireQueryString({}), "");
  assert.strictEqual(construireQueryString(null), "");
  assert.strictEqual(construireQueryString(undefined), "");
});

test("n'invente pas de cle : seules les cles fournies ressortent", () => {
  const qs = construireQueryString({ lat: "1", lng: "2" });
  const m = parametres(qs);
  assert.deepStrictEqual([...m.keys()].sort(), ["lat", "lng"]);
});

test("encode correctement les valeurs (pas d'injection brute)", () => {
  const qs = construireQueryString({ code_insee: "51 454" });
  const m = parametres(qs);
  // URLSearchParams gere l'encodage : on doit retrouver la valeur decodee.
  assert.deepStrictEqual(m.get("code_insee"), ["51 454"]);
});

test("la liste des hidden derives couvre culture ET fertilisant", () => {
  // Garde-fou : si on ajoute un hidden derive cote cascade.js, ce test
  // rappelle de l'ajouter aussi ici (sinon l'URL miroir le perdrait).
  for (const champ of [
    "occupation_sol",
    "sous_culture",
    "culture_irriguee_type",
    "prairie_permanente",
    "type_fertilisant",
    "effluent_peu_charge",
    "effluent_peu_charge_elevage",
  ]) {
    assert.ok(
      CHAMPS_HIDDEN_DERIVES.includes(champ),
      `${champ} manque dans CHAMPS_HIDDEN_DERIVES`
    );
  }
});
