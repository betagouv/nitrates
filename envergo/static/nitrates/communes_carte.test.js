/**
 * Tests des helpers purs de la couche « Communes » (#583) :
 *   node --test envergo/static/nitrates/communes_carte.test.js
 */
const test = require("node:test");
const assert = require("node:assert");
const communes = require("./communes_carte.js");

test("url des noms : chefs-lieux ADMIN EXPRESS, bbox en lat/lon, champs reduits", () => {
  const url = decodeURIComponent(
    communes.urlNomsCommunes({ sud: 48.55, ouest: 4.25, nord: 48.95, est: 4.85 })
  );
  assert.ok(url.startsWith("https://data.geopf.fr/wfs/ows?"));
  assert.ok(url.includes("TYPENAMES=ADMINEXPRESS-COG.LATEST:chef_lieu_de_commune"));
  assert.ok(url.includes("PROPERTYNAME=nom_officiel,geometrie"));
  assert.ok(url.includes("BBOX=48.55000,4.25000,48.95000,4.85000,urn:ogc:def:crs:EPSG::4326"));
  assert.ok(url.includes("COUNT=300"));
});

test("noms depuis le WFS : nom + position, entrees incompletes ignorees", () => {
  const data = {
    features: [
      { geometry: { type: "Point", coordinates: [4.64, 48.91] }, properties: { nom_officiel: "Le Fresne" } },
      { geometry: null, properties: { nom_officiel: "Sans position" } },
      { geometry: { type: "Point", coordinates: [4.5, 48.7] }, properties: {} },
    ],
  };
  assert.deepStrictEqual(communes.nomsDepuisWfs(data), [{ nom: "Le Fresne", lat: 48.91, lng: 4.64 }]);
  assert.deepStrictEqual(communes.nomsDepuisWfs(null), []);
});

test("zooms : tuiles PCI du 11 au 14 seulement (au-dela, parcelles), noms a partir du 12", () => {
  assert.strictEqual(communes.ZOOM_TUILES_MIN, 11);
  assert.strictEqual(communes.ZOOM_TUILES_MAX, 14);
  assert.ok(communes.ZOOM_NOMS_MIN > communes.ZOOM_TUILES_MIN);
  assert.ok(communes.COUCHES_MASQUEES.includes("parcelle"));
  assert.ok(!communes.COUCHES_MASQUEES.includes(communes.COUCHE_COMMUNE));
});
