// Parcelles RPG (Registre Parcellaire Graphique, parcelles declarees a la PAC)
// sur la carte du simulateur (#583).
//
// Rien en base chez nous : tout est servi par la Geoplateforme IGN.
//  - contours : tuiles vectorielles RPG-2025-TMS (zooms 11 a 16), dessinees
//    en canvas par Leaflet.VectorGrid (vendor/). Le canvas est le rendu le plus
//    rapide mais VectorGrid n'y gere pas le clic -> l'identification passe par
//    le WFS.
//  - clic : WFS RPG.LATEST:parcelles_graphiques, la parcelle sous le point
//    (geometrie + toutes les metadonnees, ~50-200 ms).
//
// La moulinette travaille sur UN point : on lui envoie le point central de la
// parcelle selectionnee, garanti a l'interieur (pole d'inaccessibilite, algo
// « polylabel » de Mapbox). Le centroide classique peut tomber dehors pour une
// parcelle en L ou en U.
//
// Pas de DOM ici : simulator.js branche ces helpers sur la carte. En Node
// (tests unitaires), on exporte les memes helpers. cf. carte_preferences.js.
(function () {
  "use strict";

  const MILLESIME = "2025";
  const URL_TUILES = "https://data.geopf.fr/tms/1.0.0/RPG-2025-TMS/{z}/{x}/{y}.pbf";
  const COUCHE_TUILES = "parcelles_graphiques_libelle";
  // L'IGN sert ces tuiles des le zoom 11, mais on n'affiche rien avant le 14
  // (echelle ~500 m, une centaine de parcelles par tuile au plus). Au 12-13,
  // des centaines de parcelles par tuile a decoder et dessiner bloquaient le
  // navigateur : la molette passait a la page et la faisait sauter (Firefox).
  const ZOOM_AFFICHAGE_MIN = 14;
  const ZOOM_NATIF_MAX = 16;
  const URL_WFS = "https://data.geopf.fr/wfs/ows";
  const TYPENAME_WFS = "RPG.LATEST:parcelles_graphiques";

  // WFS 2.0 en EPSG:4326 : l'ordre des axes est lat lon dans le filtre CQL
  // (la reponse GeoJSON, elle, reste en lon lat).
  function urlParcelleAuPoint(lat, lng) {
    const cql = "INTERSECTS(geom,POINT(" + lat + " " + lng + "))";
    return (
      URL_WFS +
      "?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature" +
      "&TYPENAMES=" + TYPENAME_WFS +
      "&OUTPUTFORMAT=application/json&COUNT=1" +
      "&CQL_FILTER=" + encodeURIComponent(cql)
    );
  }

  function polygones(geometry) {
    if (!geometry) return [];
    if (geometry.type === "Polygon") return [geometry.coordinates];
    if (geometry.type === "MultiPolygon") return geometry.coordinates;
    return [];
  }

  // Ray casting sur des anneaux [[x, y], ...]. Trous geres (parite).
  function dansAnneaux(x, y, anneaux) {
    let dedans = false;
    anneaux.forEach((r) => {
      for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
        const a = r[i];
        const b = r[j];
        if (
          a[1] > y !== b[1] > y &&
          x < ((b[0] - a[0]) * (y - a[1])) / (b[1] - a[1]) + a[0]
        ) {
          dedans = !dedans;
        }
      }
    });
    return dedans;
  }

  function pointDansGeometrie(lat, lng, geometry) {
    return polygones(geometry).some((anneaux) => dansAnneaux(lng, lat, anneaux));
  }

  function aireAnneau(r) {
    let s = 0;
    for (let i = 0; i < r.length; i++) {
      const p = r[i];
      const q = r[(i + 1) % r.length];
      s += p[0] * q[1] - q[0] * p[1];
    }
    return Math.abs(s) / 2;
  }

  function distCarreeSegment(px, py, a, b) {
    let x = a[0];
    let y = a[1];
    let dx = b[0] - x;
    let dy = b[1] - y;
    if (dx || dy) {
      const t = ((px - x) * dx + (py - y) * dy) / (dx * dx + dy * dy);
      if (t > 1) {
        x = b[0];
        y = b[1];
      } else if (t > 0) {
        x += dx * t;
        y += dy * t;
      }
    }
    dx = px - x;
    dy = py - y;
    return dx * dx + dy * dy;
  }

  // polylabel (Mapbox, ISC) en version compacte. On passe en coordonnees
  // ~metriques (lng * cos(lat)) pour ne pas favoriser l'axe nord-sud.
  // precision en degres de latitude (1e-6 ~ 10 cm). Retourne [lat, lng].
  function polylabel(anneaux, precision) {
    const k = Math.cos((anneaux[0][0][1] * Math.PI) / 180);
    const pr = anneaux.map((r) => r.map((p) => [p[0] * k, p[1]]));
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    pr[0].forEach((p) => {
      minX = Math.min(minX, p[0]);
      minY = Math.min(minY, p[1]);
      maxX = Math.max(maxX, p[0]);
      maxY = Math.max(maxY, p[1]);
    });
    const taille = Math.min(maxX - minX, maxY - minY);
    if (!taille) return [minY, minX / k];

    // Distance signee au bord : > 0 dedans, < 0 dehors.
    function dist(x, y) {
      let min = Infinity;
      pr.forEach((r) => {
        for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
          min = Math.min(min, distCarreeSegment(x, y, r[i], r[j]));
        }
      });
      return (dansAnneaux(x, y, pr) ? 1 : -1) * Math.sqrt(min);
    }
    function cellule(x, y, h) {
      const d = dist(x, y);
      return { x: x, y: y, h: h, d: d, max: d + h * Math.SQRT2 };
    }

    let h = taille / 2;
    const file = [];
    for (let x = minX; x < maxX; x += taille) {
      for (let y = minY; y < maxY; y += taille) {
        file.push(cellule(x + h, y + h, h));
      }
    }
    let meilleure = cellule((minX + maxX) / 2, (minY + maxY) / 2, 0);
    // Garde-fou : une geometrie tordue ne doit pas geler la page.
    let tours = 0;
    while (file.length && tours++ < 10000) {
      file.sort((a, b) => a.max - b.max);
      const c = file.pop();
      if (c.d > meilleure.d) meilleure = c;
      if (c.max - meilleure.d <= precision) continue;
      h = c.h / 2;
      file.push(
        cellule(c.x - h, c.y - h, h),
        cellule(c.x + h, c.y - h, h),
        cellule(c.x - h, c.y + h, h),
        cellule(c.x + h, c.y + h, h)
      );
    }
    return [meilleure.y, meilleure.x / k];
  }

  // Point central d'une parcelle (Polygon ou MultiPolygon) : celui du plus
  // grand morceau. Retourne {lat, lng} ou null si geometrie vide.
  function pointCentral(geometry) {
    const polys = polygones(geometry).filter((p) => p.length && p[0].length >= 3);
    if (!polys.length) return null;
    const plusGrand = polys.reduce((a, b) => (aireAnneau(b[0]) > aireAnneau(a[0]) ? b : a));
    const c = polylabel(plusGrand, 1e-6);
    return { lat: c[0], lng: c[1] };
  }

  const api = {
    MILLESIME: MILLESIME,
    URL_TUILES: URL_TUILES,
    COUCHE_TUILES: COUCHE_TUILES,
    ZOOM_AFFICHAGE_MIN: ZOOM_AFFICHAGE_MIN,
    ZOOM_NATIF_MAX: ZOOM_NATIF_MAX,
    urlParcelleAuPoint: urlParcelleAuPoint,
    pointDansGeometrie: pointDansGeometrie,
    pointCentral: pointCentral,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    window.NitratesRpg = api;
  }
})();
