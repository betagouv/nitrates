(function () {
  "use strict";

  // Centered on Grand Est (Châlons-en-Champagne area), zoom regional.
  const INITIAL_CENTER = [48.96, 4.36];
  const INITIAL_ZOOM = 8;

  const mapEl = document.getElementById("nitrates-map");
  const debugEl = document.getElementById("nitrates-debug");
  if (!mapEl || !debugEl) return;

  const map = L.map(mapEl).setView(INITIAL_CENTER, INITIAL_ZOOM);
  // Exposé pour les tests E2E (Playwright) et le debug console.
  window.nitratesMap = map;

  // Fond de carte IGN Plan v2 (Géoplateforme, cf. pattern Envergo).
  L.tileLayer(
    "https://data.geopf.fr/wmts?" +
      "&REQUEST=GetTile&SERVICE=WMTS&VERSION=1.0.0" +
      "&STYLE=normal" +
      "&TILEMATRIXSET=PM" +
      "&FORMAT=image/png" +
      "&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2" +
      "&TILEMATRIX={z}" +
      "&TILEROW={y}" +
      "&TILECOL={x}",
    {
      maxZoom: 22,
      maxNativeZoom: 19,
      tileSize: 256,
      attribution: '&copy; <a href="https://www.ign.fr/">IGN</a>',
    }
  ).addTo(map);

  let marker = null;

  function renderDebug(data) {
    const parcel = data.rpg_parcelle;
    const parcelHtml = parcel
      ? `${parcel.id_parcel || "—"} — ${parcel.code_cultu || "?"} — ${
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
