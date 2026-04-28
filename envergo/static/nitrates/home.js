(function () {
  "use strict";

  // Centre Grand Est, on bosse cette region en priorite pour le MVP
  const INITIAL_CENTER = [48.96, 4.36];
  const INITIAL_ZOOM = 8;

  // TODO mvp 0.0.2: virer ce mapping et le remplacer par un lookup serveur sur
  // une table RpgCulture (REF_CULTURES_GROUPES_CULTURES_2024.csv cote IGN, 144
  // codes). En attendant 4 codes pour pas afficher des trigrammes obscurs.
  const CULTURE_LABELS = {
    BTH: "Blé tendre",
    MIS: "Maïs grain",
    PTR: "Prairie temporaire",
    PPH: "Prairie permanente",
  };

  // Couleurs reprises des cartes officielles ZV (arretes prefectoraux 2021),
  // une par bassin DCE
  const ZV_COLORS_BY_BASSIN = {
    FRA: "#e7a854",
    FRB1: "#7fcfcf",
    FRB2: "#02f9f9",
    FRC: "#1e7fcb",
    FRD: "#f7e269",
    FRF: "#e1ce9a",
    FRG: "#bbae98",
    FRH: "#ffcb60",
  };
  const ZV_COLOR_FALLBACK = "#a06fc7";

  const mapEl = document.getElementById("nitrates-map");
  const debugEl = document.getElementById("nitrates-debug");
  if (!mapEl || !debugEl) return;

  const map = L.map(mapEl, {
    // Sans ce flag, Leaflet rajoute son drapeau Ukraine dans l'attribution,
    // pas top sur un site d'Etat
    attributionControl: false,
  }).setView(INITIAL_CENTER, INITIAL_ZOOM);
  L.control
    .attribution({
      prefix: '<a href="https://leafletjs.com" target="_blank">Leaflet</a>',
    })
    .addTo(map);

  // Pratique pour les tests Playwright et pour debug en console
  window.nitratesMap = map;

  // Helper pour les couches WMTS IGN, repris du pattern qu'on a dans Envergo
  // (envergo/static/js/libs/moulinette_result_maps.js)
  const wmts = (layer, format) =>
    L.tileLayer(
      "https://data.geopf.fr/wmts?" +
        "&REQUEST=GetTile&SERVICE=WMTS&VERSION=1.0.0" +
        "&STYLE=normal" +
        "&TILEMATRIXSET=PM" +
        `&FORMAT=image/${format}` +
        `&LAYER=${layer}` +
        "&TILEMATRIX={z}" +
        "&TILEROW={y}" +
        "&TILECOL={x}",
      {
        maxZoom: 22,
        maxNativeZoom: 19,
        tileSize: 256,
        attribution: '&copy; <a href="https://www.ign.fr/">IGN</a>',
      }
    );

  const planLayer = wmts("GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2", "png");
  const photoLayer = wmts("ORTHOIMAGERY.ORTHOPHOTOS", "jpeg");
  planLayer.addTo(map);

  // Tuiles RPG servies par l'IGN, pas la peine de stocker cote serveur pour
  // juste afficher
  const rpgOverlay = wmts("IGNF_RPG_PARCELLES-AGRICOLES-CATEGORISEES_2024", "png");

  // ZV: 8 polygones nationaux servis en GeoJSON simplifie par notre back
  const zvLayer = L.geoJSON(null, {
    style: (feature) => {
      const bassin = (feature.properties || {}).bassin;
      const color = ZV_COLORS_BY_BASSIN[bassin] || ZV_COLOR_FALLBACK;
      return {
        color: color,
        weight: 1.5,
        fillColor: color,
        fillOpacity: 0.45,
      };
    },
    onEachFeature: (feature, layer) => {
      const p = feature.properties || {};
      layer.bindTooltip(`${p.nom || "ZV"} (bassin ${p.bassin || "?"})`, {
        sticky: true,
      });
    },
  });
  // Lazy-load a la 1ere activation de la couche, pas avant
  let zvLoaded = false;
  function loadZvIfNeeded() {
    if (zvLoaded) return;
    zvLoaded = true;
    fetch(window.NITRATES_ZV_GEOJSON_URL)
      .then((r) => r.json())
      .then((data) => zvLayer.addData(data))
      .catch((err) => console.error("ZV GeoJSON load failed:", err));
  }
  zvLayer.on("add", loadZvIfNeeded);

  L.control
    .layers(
      {
        "Plan IGN": planLayer,
        "Photo aérienne": photoLayer,
      },
      {
        "Parcelles RPG (PAC)": rpgOverlay,
        "Zones vulnérables nitrates": zvLayer,
      },
      { collapsed: false }
    )
    .addTo(map);

  let marker = null;

  function cultureLabel(code) {
    if (!code) return "";
    return CULTURE_LABELS[code] ? `${code} (${CULTURE_LABELS[code]})` : code;
  }

  function renderDebug(data) {
    const parcel = data.rpg_parcelle;
    const parcelHtml = parcel
      ? `${parcel.id_parcel || "—"} — ${cultureLabel(parcel.code_cultu)} — ${
          parcel.surf_parc != null ? parcel.surf_parc + " ha" : ""
        }`
      : "aucune parcelle RPG";

    const zvClass = data.en_zone_vulnerable
      ? "nitrates-debug__badge-yes"
      : "nitrates-debug__badge-no";
    const zvText = data.en_zone_vulnerable
      ? `OUI — ${(data.zv_info && data.zv_info.nom) || "zone inconnue"} (bassin ${
          (data.zv_info && data.zv_info.bassin) || "—"
        })`
      : "NON";

    debugEl.innerHTML = `
      <p class="nitrates-debug__title">Informations parcelle</p>
      <dl>
        <dt>Coordonnées</dt><dd>${data.lng.toFixed(5)}, ${data.lat.toFixed(5)}</dd>
        <dt>Département</dt><dd>${data.department_code || "hors métropole"}</dd>
        <dt>Région</dt><dd>${
          data.region_code
            ? `${data.region_code} (${data.region_label})`
            : "—"
        }</dd>
        <dt>Parcelle RPG</dt><dd>${parcelHtml}</dd>
        <dt>Zone vulnérable nitrates</dt><dd class="${zvClass}">${zvText}</dd>
      </dl>
    `;
  }

  function renderError(message) {
    debugEl.innerHTML = `<p class="nitrates-debug__placeholder">Erreur : ${message}</p>`;
  }

  map.on("click", function (e) {
    const { lat, lng } = e.latlng;

    if (marker) {
      marker.setLatLng(e.latlng);
    } else {
      marker = L.marker(e.latlng).addTo(map);
    }

    debugEl.innerHTML =
      '<p class="nitrates-debug__placeholder">Chargement…</p>';

    const url = `${window.NITRATES_DEBUG_URL}?lng=${lng}&lat=${lat}`;
    fetch(url, { headers: { Accept: "application/json" } })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(renderDebug)
      .catch((err) => renderError(err.message || String(err)));
  });
})();
