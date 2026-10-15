// Couche « Communes » de la carte du simulateur (#583) : limites et noms des
// communes, sans les parcelles cadastrales (redondantes avec le RPG).
//
// Rien en base chez nous, tout vient de la Geoplateforme IGN :
//  - limites : tuiles vectorielles du cadastre (PCI). Jusqu'au zoom 14 elles
//    ne contiennent que la couche « commune » ; les parcelles arrivent au 15.
//    On ne charge donc jamais au-dela du 14 (la carte agrandit les tuiles du
//    14 quand on zoome plus pres) et on ne dessine que les communes.
//  - noms : chefs-lieux de communes d'ADMIN EXPRESS, en WFS, sur l'emprise
//    affichee (~150 ms, ~25 Ko pour une vue a l'echelle 2 km).
//
// Pas de DOM ici : simulator.js branche ces helpers sur la carte. En Node
// (tests unitaires), on exporte les memes helpers. cf. rpg_parcelle.js.
(function () {
  "use strict";

  const URL_TUILES = "https://data.geopf.fr/tms/1.0.0/PCI/{z}/{x}/{y}.pbf";
  // Couches des tuiles PCI : on ne dessine que « commune ».
  const COUCHE_COMMUNE = "commune";
  const COUCHES_MASQUEES = [
    "arrondissement",
    "departement",
    "feuille",
    "parcelle",
    "batiment",
    "localisant",
    "borne_limite_propriete",
  ];
  const ZOOM_TUILES_MIN = 11; // avant, les tuiles n'ont pas les communes
  const ZOOM_TUILES_MAX = 14; // apres, elles embarquent les parcelles
  // Noms a partir du zoom 12 (echelle ~1 km) : en dessous, une centaine de
  // communes a l'ecran, illisible.
  const ZOOM_NOMS_MIN = 12;
  // Garde-fou : jamais plus de noms que ca d'un coup.
  const NOMS_MAX = 300;

  const URL_WFS = "https://data.geopf.fr/wfs/ows";
  const TYPENAME_CHEFS_LIEUX = "ADMINEXPRESS-COG.LATEST:chef_lieu_de_commune";

  // bounds = { sud, ouest, nord, est } en degres. WFS 2.0 en EPSG:4326 :
  // BBOX en lat/lon (sud, ouest, nord, est).
  function urlNomsCommunes(bounds) {
    const bbox = [bounds.sud, bounds.ouest, bounds.nord, bounds.est]
      .map((v) => v.toFixed(5))
      .join(",");
    return (
      URL_WFS +
      "?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature" +
      "&TYPENAMES=" + TYPENAME_CHEFS_LIEUX +
      "&OUTPUTFORMAT=application/json" +
      "&PROPERTYNAME=nom_officiel,geometrie" +
      "&COUNT=" + NOMS_MAX +
      "&BBOX=" + bbox + ",urn:ogc:def:crs:EPSG::4326"
    );
  }

  // Reponse WFS -> [{ nom, lat, lng }] (entrees incompletes ignorees).
  function nomsDepuisWfs(data) {
    return ((data && data.features) || [])
      .map((f) => {
        const c = f.geometry && f.geometry.coordinates;
        const nom = f.properties && f.properties.nom_officiel;
        if (!nom || !c || c.length < 2) return null;
        return { nom: nom, lat: c[1], lng: c[0] };
      })
      .filter(Boolean);
  }

  const api = {
    URL_TUILES: URL_TUILES,
    COUCHE_COMMUNE: COUCHE_COMMUNE,
    COUCHES_MASQUEES: COUCHES_MASQUEES,
    ZOOM_TUILES_MIN: ZOOM_TUILES_MIN,
    ZOOM_TUILES_MAX: ZOOM_TUILES_MAX,
    ZOOM_NOMS_MIN: ZOOM_NOMS_MIN,
    urlNomsCommunes: urlNomsCommunes,
    nomsDepuisWfs: nomsDepuisWfs,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    window.NitratesCommunes = api;
  }
})();
