/**
 * Tests des helpers purs des parcelles RPG (#583) :
 *   node --test envergo/static/nitrates/rpg_parcelle.test.js
 */
const test = require("node:test");
const assert = require("node:assert");
const rpg = require("./rpg_parcelle.js");

// Carre de ~100 m autour de (48.75, 4.55), en [lng, lat] comme le GeoJSON.
const carre = {
  type: "Polygon",
  coordinates: [
    [
      [4.55, 48.75],
      [4.5514, 48.75],
      [4.5514, 48.7509],
      [4.55, 48.7509],
      [4.55, 48.75],
    ],
  ],
};

// Parcelle en L : le centroide (moyenne des sommets) tombe dans le coin vide.
const enL = {
  type: "Polygon",
  coordinates: [
    [
      [0, 0],
      [10, 0],
      [10, 1],
      [1, 1],
      [1, 10],
      [0, 10],
      [0, 0],
    ],
  ],
};

test("url WFS : ordre lat lon dans le filtre, une seule parcelle", () => {
  const url = rpg.urlParcelleAuPoint(48.75, 4.55);
  assert.ok(url.startsWith("https://data.geopf.fr/wfs/ows?"));
  assert.ok(url.includes("TYPENAMES=RPG.LATEST:parcelles_graphiques"));
  assert.ok(url.includes("COUNT=1"));
  assert.ok(
    decodeURIComponent(url).includes("INTERSECTS(geom,POINT(48.75 4.55))")
  );
});

test("point dans la parcelle : dedans, dehors, MultiPolygon, geometrie vide", () => {
  assert.strictEqual(rpg.pointDansGeometrie(48.7504, 4.5507, carre), true);
  assert.strictEqual(rpg.pointDansGeometrie(48.76, 4.5507, carre), false);
  const multi = { type: "MultiPolygon", coordinates: [enL.coordinates, carre.coordinates] };
  assert.strictEqual(rpg.pointDansGeometrie(48.7504, 4.5507, multi), true);
  assert.strictEqual(rpg.pointDansGeometrie(5, 5, enL), false);
  assert.strictEqual(rpg.pointDansGeometrie(48.75, 4.55, null), false);
});

test("point central d'un carre : au milieu", () => {
  const c = rpg.pointCentral(carre);
  assert.ok(Math.abs(c.lat - 48.75045) < 1e-4);
  assert.ok(Math.abs(c.lng - 4.5507) < 1e-4);
});

test("point central d'une parcelle en L : toujours dedans", () => {
  // Coordonnees ramenees pres de l'equateur : cos(lat) ~ 1, pas de deformation.
  const c = rpg.pointCentral(enL);
  assert.ok(rpg.pointDansGeometrie(c.lat, c.lng, enL));
  // Le centroide des sommets, lui, tombe dehors : c'est tout l'interet.
  const pts = enL.coordinates[0].slice(0, -1);
  const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
  const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
  assert.strictEqual(rpg.pointDansGeometrie(cy, cx, enL), false);
});

test("point central d'un MultiPolygon : dans le plus grand morceau", () => {
  const petit = [[[20, 20], [20.1, 20], [20.1, 20.1], [20, 20.1], [20, 20]]];
  const multi = { type: "MultiPolygon", coordinates: [petit, enL.coordinates] };
  const c = rpg.pointCentral(multi);
  assert.ok(rpg.pointDansGeometrie(c.lat, c.lng, enL));
});

test("point central d'une geometrie vide ou degeneree : null", () => {
  assert.strictEqual(rpg.pointCentral(null), null);
  assert.strictEqual(rpg.pointCentral({ type: "Polygon", coordinates: [] }), null);
  assert.strictEqual(rpg.pointCentral({ type: "Point", coordinates: [1, 2] }), null);
});
