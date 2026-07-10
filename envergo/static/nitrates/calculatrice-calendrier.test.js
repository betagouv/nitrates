/**
 * Tests de logique pure du calendrier dynamique (calculatrice-calendrier.js).
 *
 * Lancés en Node (cf. feedback_static_js_cache_dev : on valide la logique
 * calendrier en Node, le JS statique servi en dev pouvant être périmé) :
 *   node --test envergo/static/nitrates/calculatrice-calendrier.test.js
 *
 * Le module source détecte l'environnement Node et n'exporte alors que ses
 * fonctions pures (sans toucher au DOM).
 */
const test = require("node:test");
const assert = require("node:assert");

const cal = require("./calculatrice-calendrier.js");
const { parseBorne, evalComparaison, evalCondition, computeRegimePerDay, TOTAL_JOURS } = cal;

// "JJ/MM" -> index agricole, pour des assertions lisibles.
const J = (s) => cal.jjmmToJourAgricole(s);

test("parseBorne : date fixe et event nu", () => {
  assert.strictEqual(parseBorne("01/07", {}).jour, 0);
  assert.strictEqual(parseBorne("30/06", {}).jour, TOTAL_JOURS - 1);
  // event nu = la date saisie
  assert.strictEqual(
    parseBorne("date_semis_couvert", { date_semis_couvert: "15/08" }).jour,
    J("15/08")
  );
});

test("parseBorne : event±offset expose jour (replié) ET jourRaw (brut)", () => {
  // semis=14/07 (index 13), -15 jours = 29/06.
  const p = parseBorne("date_semis_couvert-15jours", {
    date_semis_couvert: "14/07",
  });
  assert.strictEqual(p.jour, J("29/06")); // replié dans [0,365)
  assert.strictEqual(p.jourRaw, 13 - 15); // brut négatif : a franchi le 1er juil
});

test("BUG calendrier overflow : 01/07 < semis-15jours est FAUX pour un semis précoce", () => {
  // Cas signalé : semis 14/07 -> semis-15j = 29/06, qui PRÉCÈDE le 1er juillet.
  // La condition de la période d'interdiction « 01/07 -> semis-15j » doit donc
  // être fausse (intervalle non positif), la période ne s'applique pas.
  assert.strictEqual(
    evalComparaison("01/07 < date_semis_couvert-15jours", {
      date_semis_couvert: "14/07",
    }),
    false
  );
});

test("Non-régression : 01/07 < semis-15jours reste VRAI pour un semis normal", () => {
  // semis 15/08 -> semis-15j = 31/07, bien après le 1er juillet -> vrai.
  assert.strictEqual(
    evalComparaison("01/07 < date_semis_couvert-15jours", {
      date_semis_couvert: "15/08",
    }),
    true
  );
});

test("Non-régression : conditions destruction/semis±offset usuelles", () => {
  // 15/11 < destruction-20j : destruction 20/12 -> 30/11 > 15/11 -> vrai
  assert.strictEqual(
    evalComparaison("15/11 < date_destruction_couvert-20jours", {
      date_destruction_couvert: "20/12",
    }),
    true
  );
  // destruction 25/11 -> 05/11 < 15/11 -> faux
  assert.strictEqual(
    evalComparaison("15/11 < date_destruction_couvert-20jours", {
      date_destruction_couvert: "25/11",
    }),
    false
  );
  // 15/11 < semis+4semaines : semis 20/10 -> +28j = 17/11 > 15/11 -> vrai
  assert.strictEqual(
    evalComparaison("15/11 < date_semis_couvert+4semaines", {
      date_semis_couvert: "20/10",
    }),
    true
  );
  // semis 20/09 -> +28j = 18/10 < 15/11 -> faux
  assert.strictEqual(
    evalComparaison("15/11 < date_semis_couvert+4semaines", {
      date_semis_couvert: "20/09",
    }),
    false
  );
});

test("evalComparaison : opérateurs <=, >, >=, ==, !=", () => {
  const v = { date_semis_couvert: "15/08" }; // semis-15j = 31/07
  assert.strictEqual(evalComparaison("date_semis_couvert-15jours >= 01/07", v), true);
  assert.strictEqual(evalComparaison("date_semis_couvert-15jours > 30/07", v), true);
  assert.strictEqual(evalComparaison("date_semis_couvert-15jours == 31/07", v), true);
  assert.strictEqual(evalComparaison("date_semis_couvert-15jours != 31/07", v), false);
  assert.strictEqual(evalComparaison("01/07 <= date_semis_couvert-15jours", v), true);
});

test("evalCondition : permissif si event non saisi", () => {
  // Aucune valeur -> terme non résolvable -> permissif (true).
  assert.strictEqual(evalComparaison("01/07 < date_semis_couvert-15jours", {}), true);
  // Conjonction && : toutes vraies
  assert.strictEqual(
    evalCondition("01/07 < date_semis_couvert-15jours", { date_semis_couvert: "15/08" }),
    true
  );
});

test("REGRESSION cœur du bug : computeRegimePerDay ne peint pas toute l'année en interdit", () => {
  // Règle réelle r_cine_avant_3112_type_Ib_icpe_ed_non_iaa (extrait servi).
  const periodes = [
    { au: "date_semis_couvert-15jours", du: "01/07", regime: "interdiction",
      condition: "01/07 < date_semis_couvert-15jours" },
    { au: "date_destruction_couvert-20jours", du: "15/11",
      regime: "autorisation_sous_condition",
      condition: "15/11 < date_destruction_couvert-20jours" },
    { au: "15/01", du: "date_destruction_couvert-20jours", regime: "interdiction" },
    { au: "15/01", du: "15/12" },
  ];
  cal.setData({ type: "calculatrice", periodes });

  // Cas buggé : semis 14/07, destruction 20/12.
  const valeurs = { date_semis_couvert: "14/07", date_destruction_couvert: "20/12" };
  const regime = computeRegimePerDay(periodes, valeurs);

  // La 1re période d'interdiction (01/07 -> semis-15j) doit être éliminée par
  // sa condition -> le calendrier n'est PAS interdit du 1er juillet à l'automne.
  const nbInterdit = regime.filter((r) => r === "interdiction").length;
  assert.ok(
    nbInterdit < TOTAL_JOURS / 2,
    `Trop de jours interdits (${nbInterdit}/${TOTAL_JOURS}) : la période overflow ` +
      `n'a pas été filtrée (régression du bug calendrier).`
  );
  // Sanity : début juillet (avant 15/11) doit être autorisé (libre), pas interdit.
  assert.strictEqual(regime[J("15/07")], "libre");
  assert.strictEqual(regime[J("01/09")], "libre");
});

test("ROBUSTESSE moteur : période SANS condition de garde mais fenêtre dégénérée", () => {
  // Cas du fichier arbre_decision_national.yaml : la période d'interdiction
  // 01/07 -> semis-15j n'a PAS de `condition` explicite. Le garde moteur
  // (_fenetreDegeneree) doit quand même neutraliser le wrap pour un semis
  // précoce, sinon tout le calendrier est peint en interdit.
  const periodes = [
    { au: "date_semis_couvert-15jours", du: "01/07", regime: "interdiction" },
  ];
  cal.setData({ type: "calculatrice", periodes });

  // semis 14/07 -> semis-15j = 29/06 (avant 01/07) -> fenêtre vide -> rien.
  const rEarly = computeRegimePerDay(periodes, { date_semis_couvert: "14/07" });
  assert.strictEqual(
    rEarly.filter((r) => r === "interdiction").length,
    0,
    "Période dégénérée non gardée par condition : doit être supprimée par le moteur."
  );

  // semis 15/08 -> interdit 01/07 -> 31/07 normalement.
  const rNormal = computeRegimePerDay(periodes, { date_semis_couvert: "15/08" });
  assert.strictEqual(rNormal[J("01/07")], "interdiction");
  assert.strictEqual(rNormal[J("31/07")], "interdiction");
  assert.strictEqual(rNormal[J("15/08")], "libre");
});

test("ROBUSTESSE : wrap d'année légitime (event nu/offset sans franchissement) préservé", () => {
  // du: destruction-20j (en range), au: 15/01 : enjambe déc->jan, LÉGITIME.
  // Ne doit PAS être supprimé.
  const periodes = [
    { au: "15/01", du: "date_destruction_couvert-20jours", regime: "interdiction" },
  ];
  cal.setData({ type: "calculatrice", periodes });
  const r = computeRegimePerDay(periodes, { date_destruction_couvert: "20/12" });
  // dest-20j = 30/11 -> interdit du 30/11 au 15/01 (à cheval).
  assert.strictEqual(r[J("30/11")], "interdiction");
  assert.strictEqual(r[J("31/12")], "interdiction");
  assert.strictEqual(r[J("15/01")], "interdiction");
  assert.strictEqual(r[J("16/01")], "libre");
});

test("REGRESSION : un semis normal applique bien l'interdit 01/07 -> semis-15j", () => {
  const periodes = [
    { au: "date_semis_couvert-15jours", du: "01/07", regime: "interdiction",
      condition: "01/07 < date_semis_couvert-15jours" },
  ];
  cal.setData({ type: "calculatrice", periodes });
  // semis 15/08 -> interdit du 01/07 au 31/07.
  const regime = computeRegimePerDay(periodes, { date_semis_couvert: "15/08" });
  assert.strictEqual(regime[J("01/07")], "interdiction");
  assert.strictEqual(regime[J("31/07")], "interdiction");
  assert.strictEqual(regime[J("15/08")], "libre"); // après semis-15j
});

test("BUG inversion : du=destruction-20j au=31/01 avec destruction tardive (mars) -> période neutralisée", () => {
  // Cas signalé (#repro) : destruction 15/03 -> destruction-20j = 23/02, qui
  // tombe APRÈS le 31/01. L'intervalle `du:23/02 au:31/01` s'inverse : sans
  // garde il wrappe et peint quasi toute l'année. Une borne est un event
  // (destruction-20j) -> inversion involontaire -> période neutralisée.
  const periodes = [
    { du: "date_destruction_prevue-20jours", au: "31/01", regime: "interdiction" },
  ];
  cal.setData({ type: "calculatrice", periodes });
  const r = computeRegimePerDay(periodes, { date_destruction_prevue: "15/03" });
  assert.strictEqual(
    r.filter((v) => v === "interdiction").length,
    0,
    "La période inversée (event passé de l'autre côté d'une date fixe) doit être neutralisée."
  );
});

test("NON-REGRESSION : wrap volontaire entre 2 dates fixes (15/10 -> 31/01) conservé", () => {
  // Les deux bornes sont des dates FIXES : l'inversion 15/10 > 31/01 est un
  // wrap d'année VOLONTAIRE (oct -> jan suivant), il NE doit PAS être neutralisé.
  const periodes = [{ du: "15/10", au: "31/01", regime: "interdiction" }];
  cal.setData({ type: "calculatrice", periodes });
  const r = computeRegimePerDay(periodes, {});
  assert.strictEqual(r[J("15/10")], "interdiction");
  assert.strictEqual(r[J("01/12")], "interdiction");
  assert.strictEqual(r[J("31/01")], "interdiction");
  assert.strictEqual(r[J("01/02")], "libre");
});

test("BUG inversion : semis saisi APRÈS destruction (du=semis au=destruction) -> neutralisée", () => {
  // Deux events inversés : semis 15/11 (idx 137) > destruction 15/08 (idx 45).
  const periodes = [
    { du: "date_semis_couvert", au: "date_destruction_couvert", regime: "autorisation_sous_condition" },
  ];
  cal.setData({ type: "calculatrice", periodes });
  const r = computeRegimePerDay(periodes, {
    date_semis_couvert: "15/11", date_destruction_couvert: "15/08",
  });
  assert.strictEqual(
    r.filter((v) => v === "autorisation_sous_condition").length, 0,
    "Fenêtre semis>destruction (deux events inversés) doit être neutralisée."
  );
});

test("BUG borne dynamique ignorée : du=destruction-20j (antérieur au 15/10) au=30/06 étend l'interdit vers l'amont", () => {
  // Cas validation staging (PAR/ICPE-A digestats, r_cine_avant_3112_type_II_icpe_a_digestats) :
  // deux interdits jusqu'au 30/06, l'un fixe `du: 15/10`, l'autre dynamique
  // `du: destruction-20j`. Avec destruction 01/11 -> destruction-20j = 12/10,
  // ANTÉRIEUR au 15/10 : l'interdit doit démarrer au 12/10 (la borne dynamique
  // étend vers l'amont), pas au 15/10.
  //
  // Régression corrigée : `_alignerSurAncre` repliait `au: 30/06` (idx 364)
  // sur -1, jugeait la fenêtre `12/10 -> 30/06` inversée et neutralisait toute
  // la période dynamique -> l'interdit démarrait à tort au 15/10.
  const periodes = [
    { au: "date_semis_couvert-15jours", du: "01/07", regime: "interdiction",
      condition: "01/07 < date_semis_couvert-15jours" },
    { au: "30/06", du: "date_destruction_couvert-20jours", regime: "interdiction" },
    { au: "30/06", du: "15/10", regime: "interdiction" },
  ];
  cal.setData({ type: "calculatrice", periodes });
  const r = computeRegimePerDay(periodes, {
    date_semis_couvert: "15/08", date_destruction_couvert: "01/11",
  });
  assert.strictEqual(r[J("11/10")], "libre", "veille de destruction-20j : encore autorisé");
  assert.strictEqual(r[J("12/10")], "interdiction", "destruction-20j : l'interdit dynamique démarre ici");
  assert.strictEqual(r[J("14/10")], "interdiction", "entre 12/10 et 15/10 : interdit par la borne dynamique");
  assert.strictEqual(r[J("15/10")], "interdiction");
  assert.strictEqual(r[J("30/06")], "interdiction");
});

// ─── conditionToText : justification métier couvert (#159, retour Emma) ──────
// La phrase remplace l'entièreté de l'ancien "(annotation) — car ...". Format :
// "Car interdit jusqu'à / à partir de <N unités> avant/après
//  l'implantation du couvert | la destruction ou la récolte du couvert".
test("conditionToText #159 : semis + offset -> 'après l'implantation'", () => {
  assert.strictEqual(
    cal.conditionToText("15/10 < date_semis_couvert+4semaines"),
    "Car interdit jusqu’à 4 semaines après l’implantation du couvert"
  );
  assert.strictEqual(
    cal.conditionToText("date_semis_couvert+15jours < 15/01"),
    "Car interdit à partir de 15 jours après l’implantation du couvert"
  );
});

test("conditionToText #159 : destruction - offset -> 'avant la destruction ou la récolte'", () => {
  assert.strictEqual(
    cal.conditionToText("15/10 < date_destruction_couvert-20jours"),
    "Car interdit jusqu’à 20 jours avant la destruction ou la récolte du couvert"
  );
  assert.strictEqual(
    cal.conditionToText("date_destruction_couvert-20jours < 15/01"),
    "Car interdit à partir de 20 jours avant la destruction ou la récolte du couvert"
  );
  assert.strictEqual(
    cal.conditionToText("date_destruction_couvert-20jours > 15/11"),
    "Car interdit jusqu’à 20 jours avant la destruction ou la récolte du couvert"
  );
});

test("conditionToText : fallback ancienne tournure hors couvert", () => {
  // Pas d'event couvert connu -> ancienne phrase "car ... est ...".
  const txt = cal.conditionToText("15/12 < 15/01");
  assert.ok(txt && txt.startsWith("car "), "fallback attendu pour deux dates fixes");
});

test("conditionToText : condition vide/nulle -> null", () => {
  assert.strictEqual(cal.conditionToText(""), null);
  assert.strictEqual(cal.conditionToText(null), null);
});
