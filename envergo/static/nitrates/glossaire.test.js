/**
 * Tests de la logique pure de matching du glossaire (#110).
 *
 * Lances en Node :
 *   node --test envergo/static/nitrates/glossaire.test.js
 *
 * Le module source detecte Node et n'exporte que les helpers purs
 * (echapperRegex / construireRegex / decouperTexte), sans DOM.
 *
 * PARITE avec le filtre Python |glossaire (test_glossaire_filter.py) : les
 * memes cas y sont testes cote serveur. Si un comportement change d'un cote,
 * changer l'autre.
 */
const test = require("node:test");
const assert = require("node:assert");

const { echapperRegex, construireRegex, decouperTexte } =
  require("./glossaire.js");

// [[variante, cle]] TRIES longest-first, comme les sert glossaire.py.
const TERMES = [
  ["Interculture longue", "definition.interculture-longue"],
  ["azote efficace", "definition.azote-efficace"],
  ["rapport C/N", "definition.c-n"],
  ["Interculture", "definition.interculture"],
  ["C/N", "definition.c-n"],
];
const PAR_VARIANTE = {};
TERMES.forEach(function (t) {
  PAR_VARIANTE[t[0].toLowerCase()] = t[1];
});
const REGEX = construireRegex(TERMES);

function cles(segments) {
  return segments
    .filter(function (s) {
      return s.cle !== undefined;
    })
    .map(function (s) {
      return s.cle;
    });
}

test("terme simple matche et decoupe", function () {
  const segs = decouperTexte(
    "Pendant l'interculture, le sol est nu.",
    REGEX,
    PAR_VARIANTE
  );
  assert.deepStrictEqual(cles(segs), ["definition.interculture"]);
  // Reassemblage sans perte.
  assert.strictEqual(
    segs.map(function (s) { return s.texte; }).join(""),
    "Pendant l'interculture, le sol est nu."
  );
});

test("longest-match prime (interculture longue)", function () {
  const segs = decouperTexte(
    "En interculture longue uniquement.",
    REGEX,
    PAR_VARIANTE
  );
  assert.deepStrictEqual(cles(segs), ["definition.interculture-longue"]);
});

test("insensible a la casse, libelle preserve", function () {
  const segs = decouperTexte("Interculture : periode.", REGEX, PAR_VARIANTE);
  assert.strictEqual(segs[0].texte, "Interculture");
  assert.strictEqual(segs[0].cle, "definition.interculture");
});

test("frontiere accentuee : pas de sous-mot", function () {
  // Parite Python : « azote efficacement » ne matche pas « azote efficace ».
  const segs = decouperTexte(
    "L'azote efficacement absorbe.",
    REGEX,
    PAR_VARIANTE
  );
  assert.deepStrictEqual(cles(segs), []);
});

test("apostrophe est une frontiere valide", function () {
  const segs = decouperTexte(
    "La part d'azote efficace apportee.",
    REGEX,
    PAR_VARIANTE
  );
  assert.deepStrictEqual(cles(segs), ["definition.azote-efficace"]);
});

test("variante avec slash (rapport C/N)", function () {
  const segs = decouperTexte(
    "Le rapport C/N conditionne le type.",
    REGEX,
    PAR_VARIANTE
  );
  assert.deepStrictEqual(cles(segs), ["definition.c-n"]);
  assert.strictEqual(
    segs.find(function (s) { return s.cle; }).texte,
    "rapport C/N"
  );
});

test("echapperRegex neutralise les metacaracteres", function () {
  assert.strictEqual(echapperRegex("C/N (a+b)"), "C/N \\(a\\+b\\)");
});

test("glossaire vide : texte rendu tel quel", function () {
  assert.deepStrictEqual(decouperTexte("Bonjour", null, {}), [
    { texte: "Bonjour" },
  ]);
  assert.deepStrictEqual(
    construireRegex([]),
    null
  );
});

test("plusieurs matches dans un meme texte", function () {
  const segs = decouperTexte(
    "Azote efficace & C/N",
    REGEX,
    PAR_VARIANTE
  );
  assert.deepStrictEqual(cles(segs), [
    "definition.azote-efficace",
    "definition.c-n",
  ]);
});
