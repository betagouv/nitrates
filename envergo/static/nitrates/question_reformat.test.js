/**
 * Tests de la logique pure de matching du reformatage de questions (#192).
 *
 * Lances en Node (le JS statique servi en dev peut etre perime, cf.
 * feedback_static_js_cache_dev) :
 *   node --test envergo/static/nitrates/question_reformat.test.js
 *
 * Le module source detecte Node et n'exporte alors que ses fonctions pures
 * (normalize / similarity / classify / suffixHtml), sans toucher au DOM.
 *
 * On verifie les 2 invariants critiques :
 *   1. Les 3 formulations reelles de la question fertilisant_iaa (relevees dans
 *      les arbres actifs national / region GE / zar) matchent la BONNE entree
 *      du dictionnaire, malgre leurs variantes de ponctuation / reformulation.
 *   2. Les autres questions du formulaire ne matchent JAMAIS (pas de faux
 *      positif) : c'est ce qui rend sur d'ajouter d'autres entrees plus tard.
 */
const test = require("node:test");
const assert = require("node:assert");

const { classify, suffixHtml, normalize, similarity } =
  require("./question_reformat.js");

// index 0 = entree A (version longue, enumeration vin+distillation)
// index 1 = entree B/C (version courte, produits alimentaires / aliments animaux)
const ENTREE_A = 0;
const ENTREE_BC = 1;

// Textes REELS releves dans les arbres actifs (psql sur les contenus jsonb).
const A_LONG_VIRGULE_INTERNE =
  "Le fertilisant utilisé est-il issu de traitement et transformations de matières premières en vue de la fabrication de produit alimentaire pour l'alimentation humaine ou animale ou, de la préparation et du conditionnement de vins, ou de la production par distillation d'alcools de bouche d'origine agricole ?";
const A_LONG_VIRGULE_APRES =
  "Le fertilisant utilisé est-il issu de traitement et transformations de matières premières en vue de la fabrication de produit alimentaire pour l'alimentation humaine ou animale, ou de la préparation et du conditionnement de vins, ou de la production par distillation d'alcools de bouche d'origine agricole ? *";
const B_NOTE12 =
  "Le fertilisant utilisé est-il issu du traitement et/ou de la transformation de matières premières en vue de la fabrication de produits alimentaires ou d'aliments pour animaux ? (Note 12) *";
const C_COURT =
  "Le fertilisant utilisé est-il issu du traitement et/ou de la transformation de matières premières en vue de la fabrication de produits alimentaires ou d'aliments pour animaux? *";

// Autres questions du meme formulaire (ne doivent PAS matcher).
const AUTRES = [
  "Quel fertilisant souhaitez-vous épandre ? *",
  "Précisez la catégorie de fertilisant utilisé : *",
  "Quelle est l'occupation du sol en cours ou à venir sur la parcelle ? *",
  "S'agit-il d'un épandage prévu dans le cadre d'un plan d'épandage ICPE ? *",
  "Votre plan d'épandage est-il soumis à autorisation? *",
];

test("les 2 variantes de la version LONGUE matchent l'entree A", () => {
  assert.strictEqual(classify(A_LONG_VIRGULE_INTERNE).index, ENTREE_A);
  assert.strictEqual(classify(A_LONG_VIRGULE_APRES).index, ENTREE_A);
});

test("les versions COURTES (Note 12 et sans) matchent l'entree B/C", () => {
  assert.strictEqual(classify(B_NOTE12).index, ENTREE_BC);
  assert.strictEqual(classify(C_COURT).index, ENTREE_BC);
});

test("longue et courte ne se confondent pas (formulations distinctes)", () => {
  // La longue ne doit pas matcher l'entree courte, et inversement : ce sont
  // deux questions differentes (la courte a perdu les clauses vin/distillation).
  assert.notStrictEqual(classify(A_LONG_VIRGULE_APRES).index, ENTREE_BC);
  assert.notStrictEqual(classify(C_COURT).index, ENTREE_A);
});

test("aucune autre question du formulaire ne matche (pas de faux positif)", () => {
  for (const q of AUTRES) {
    const { index, score } = classify(q);
    assert.strictEqual(
      index,
      -1,
      `"${q.slice(0, 40)}..." ne devrait matcher aucune entree (score ${score.toFixed(3)})`
    );
  }
});

test("suffixHtml preserve « (Note 12) » puis « * », dans cet ordre", () => {
  const s = suffixHtml(B_NOTE12);
  assert.match(s, /\(Note 12\)/);
  assert.match(s, /\*/);
  // (Note 12) apparait AVANT l'asterisque
  assert.ok(s.indexOf("Note 12") < s.indexOf("*"));
});

test("suffixHtml preserve « * » seul quand pas de note", () => {
  const s = suffixHtml(C_COURT);
  assert.match(s, /\*/);
  assert.doesNotMatch(s, /Note/);
});

test("suffixHtml vide si ni note ni asterisque", () => {
  assert.strictEqual(suffixHtml("Une question sans marqueur"), "");
});

test("normalize neutralise ponctuation, note, casse et insecables", () => {
  // deux formes de la meme question longue -> meme forme normalisee
  assert.strictEqual(
    normalize(A_LONG_VIRGULE_INTERNE),
    normalize(A_LONG_VIRGULE_APRES.replace(/ \*$/, ""))
  );
  // le « (Note 12) » ne change pas la forme normalisee
  assert.strictEqual(
    normalize(B_NOTE12),
    normalize(C_COURT)
  );
});

test("similarity vaut 1 pour deux chaines normalisant a l'identique", () => {
  assert.strictEqual(similarity(normalize(B_NOTE12), normalize(C_COURT)), 1);
});
