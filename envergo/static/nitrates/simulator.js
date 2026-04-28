// JS du formulaire /simulateur/ : carte cliquable qui pre-remplit les
// inputs lat/lng + meme panneau debug que la home (sans toucher au JS de
// la home, qui est utilise comme demonstrateur).
//
// On factorise un jour si besoin, pour l'instant c'est une variante.

(function () {
  "use strict";

  const INITIAL_CENTER = [48.96, 4.36];
  const INITIAL_ZOOM = 8;

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
  const lngInput = document.getElementById("id_lng");
  const latInput = document.getElementById("id_lat");
  if (!mapEl || !lngInput || !latInput) return;

  const map = L.map(mapEl, { attributionControl: false }).setView(
    INITIAL_CENTER,
    INITIAL_ZOOM
  );
  L.control
    .attribution({
      prefix: '<a href="https://leafletjs.com" target="_blank">Leaflet</a>',
    })
    .addTo(map);

  window.nitratesMap = map;

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

  const rpgOverlay = wmts(
    "IGNF_RPG_PARCELLES-AGRICOLES-CATEGORISEES_2024",
    "png"
  );

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
  zvLayer.addTo(map);

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

  // Si lat/lng deja saisis (form pre-rempli depuis URL), on positionne le
  // marker directement.
  const initialLng = parseFloat(lngInput.value);
  const initialLat = parseFloat(latInput.value);
  if (!isNaN(initialLng) && !isNaN(initialLat)) {
    marker = L.marker([initialLat, initialLng]).addTo(map);
    map.setView([initialLat, initialLng], 13);
  }

  function cultureLabel(parcel) {
    if (!parcel || !parcel.code_cultu) return "";
    if (parcel.libelle_cultu) {
      return `${parcel.code_cultu} (${parcel.libelle_cultu})`;
    }
    return parcel.code_cultu;
  }

  function renderDebug(data) {
    if (!debugEl) return;
    const parcel = data.rpg_parcelle;
    const parcelHtml = parcel
      ? `${parcel.id_parcel || "—"} — ${cultureLabel(parcel)} — ${
          parcel.surf_parc != null ? parcel.surf_parc + " ha" : ""
        }${parcel.groupe_cultu ? " — groupe " + parcel.groupe_cultu : ""}`
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
    if (!debugEl) return;
    debugEl.innerHTML = `<p class="nitrates-debug__placeholder">Erreur : ${message}</p>`;
  }

  map.on("click", function (e) {
    const { lat, lng } = e.latlng;

    // Pre-remplit le form -- c'est l'objectif principal de cette page.
    lngInput.value = lng.toFixed(6);
    latInput.value = lat.toFixed(6);

    if (marker) {
      marker.setLatLng(e.latlng);
    } else {
      marker = L.marker(e.latlng).addTo(map);
    }

    if (debugEl) {
      debugEl.innerHTML =
        '<p class="nitrates-debug__placeholder">Chargement…</p>';
    }

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
