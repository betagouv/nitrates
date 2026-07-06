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

const {
  construireQueryString,
  elaguerAvalDansUrl,
  CHAMPS_HIDDEN_DERIVES,
} = require("./reset_form.js");

// Helper : parse la query string produite en Map cle->[valeurs].
function parametres(qs) {
  const p = new URLSearchParams(qs);
  const m = new Map();
  for (const cle of p.keys()) m.set(cle, p.getAll(cle));
  return m;
}

// Ordre de parcours reel (couvert -> fertilisant -> plan -> QC).
const ORDRE = [
  "categorie_culture",
  "sous_culture_form",
  "categorie_fertilisant",
  "sous_fertilisant",
  "plan_epandage",
  "fertilisant_iaa",
];

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

// ─── elaguerAvalDansUrl : elagage AVAL + preservation amont (#175) ──────────

test("flip d'une reponse QC (dernier champ) : MAJ la valeur, garde tout l'amont", () => {
  const initial =
    "lat=49.25&lng=4.03&categorie_culture=couvert_intercultures_longue" +
    "&sous_culture_form=x&occupation_sol=couvert_intercultures&sous_culture=cine_apres_0101" +
    "&categorie_fertilisant=fumiers&sous_fertilisant=fmse&type_fertilisant=type_Ib" +
    "&plan_epandage=icpe_a&fertilisant_iaa=True";
  const out = parametres(
    elaguerAvalDansUrl(initial, ORDRE, "fertilisant_iaa", {
      fertilisant_iaa: "False",
    })
  );
  // la reponse re-choisie est mise a jour (pas perdue)
  assert.deepStrictEqual(out.get("fertilisant_iaa"), ["False"]);
  // tout l'amont survit
  assert.deepStrictEqual(out.get("type_fertilisant"), ["type_Ib"]);
  assert.deepStrictEqual(out.get("plan_epandage"), ["icpe_a"]);
  assert.deepStrictEqual(out.get("categorie_culture"), [
    "couvert_intercultures_longue",
  ]);
});

test("flip d'un champ AMONT : elague l'aval + les hidden derives, garde l'amont", () => {
  const initial =
    "lat=49.25&categorie_culture=cc&sous_culture_form=x&occupation_sol=os&sous_culture=sc" +
    "&categorie_fertilisant=fumiers&sous_fertilisant=fmse&type_fertilisant=type_Ib" +
    "&effluent_peu_charge=false&plan_epandage=icpe_a&fertilisant_iaa=True";
  const out = parametres(
    elaguerAvalDansUrl(initial, ORDRE, "categorie_fertilisant", {
      categorie_fertilisant: "lisiers",
      type_fertilisant: "",
      effluent_peu_charge: "",
      effluent_peu_charge_elevage: "",
    })
  );
  assert.deepStrictEqual(out.get("categorie_fertilisant"), ["lisiers"]);
  // aval supprime
  assert.ok(!out.has("sous_fertilisant"));
  assert.ok(!out.has("plan_epandage"));
  assert.ok(!out.has("fertilisant_iaa"));
  // hidden derives du groupe fertilisant supprimes
  assert.ok(!out.has("type_fertilisant"));
  assert.ok(!out.has("effluent_peu_charge"));
  // amont preserve
  assert.deepStrictEqual(out.get("categorie_culture"), ["cc"]);
  assert.deepStrictEqual(out.get("lat"), ["49.25"]);
});

test("preserve les parametres INCONNUS (ajouter sans ecraser)", () => {
  const initial =
    "lat=49.25&categorie_culture=cc&sous_culture_form=x&categorie_fertilisant=f" +
    "&flag_inconnu=42&leaflet-base-layers_65=on";
  const out = parametres(
    elaguerAvalDansUrl(initial, ORDRE, "sous_culture_form", {
      sous_culture_form: "y",
      occupation_sol: "os2",
      sous_culture: "sc2",
    })
  );
  // param inconnu preserve
  assert.deepStrictEqual(out.get("flag_inconnu"), ["42"]);
  assert.deepStrictEqual(out.get("leaflet-base-layers_65"), ["on"]);
  // le champ change est mis a jour
  assert.deepStrictEqual(out.get("sous_culture_form"), ["y"]);
});

test("une valeur vide supprime la cle (pas de cle=vide dans l'URL)", () => {
  const initial = "categorie_culture=cc&sous_culture_form=x&occupation_sol=os";
  const out = parametres(
    elaguerAvalDansUrl(initial, ORDRE, "sous_culture_form", {
      sous_culture_form: "",
      occupation_sol: "",
      sous_culture: "",
    })
  );
  assert.ok(!out.has("sous_culture_form"));
  assert.ok(!out.has("occupation_sol"));
});

test("champ hors ordre (ex. inconnu) : ne supprime rien, MAJ juste sa cle", () => {
  const initial = "lat=49.25&categorie_culture=cc&plan_epandage=icpe_a";
  const out = parametres(
    elaguerAvalDansUrl(initial, ORDRE, "champ_hors_ordre", {
      champ_hors_ordre: "v",
    })
  );
  assert.deepStrictEqual(out.get("categorie_culture"), ["cc"]);
  assert.deepStrictEqual(out.get("plan_epandage"), ["icpe_a"]);
  assert.deepStrictEqual(out.get("champ_hors_ordre"), ["v"]);
});
