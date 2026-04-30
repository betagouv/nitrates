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

  // Cadastre IGN (parcellaire express) : layer principal pour
  // identifier la parcelle utilisateur. Pattern Envergo (frontend-only) :
  // tuiles WMTS raster + identification a la demande via l'API
  // data.geopf.fr/geocodage/reverse au clic.
  const cadastreOverlay = wmts(
    "CADASTRALPARCELS.PARCELLAIRE_EXPRESS",
    "png"
  );
  cadastreOverlay.addTo(map);

  // RPG (Registre Parcellaire Graphique) : desactive en MVP (retour
  // juriste 0.0.1 : la donnee correcte pour la zone d'activation est
  // le cadastre, pas le RPG). On garde l'import et la table en DB
  // pour reactivation V1+ : resoudre la culture declaree par
  // l'agriculteur a partir de la parcelle RPG. Le layer reste defini
  // mais n'est pas ajoute au LayerControl.
  // const rpgOverlay = wmts(
  //   "IGNF_RPG_PARCELLES-AGRICOLES-CATEGORISEES_2024",
  //   "png"
  // );

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
        "Cadastre": cadastreOverlay,
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

  function renderDebug(data, communeInfo, parcelInfo) {
    if (!debugEl) return;

    const zvClass = data.en_zone_vulnerable
      ? "nitrates-debug__badge-yes"
      : "nitrates-debug__badge-no";
    const zvText = data.en_zone_vulnerable
      ? `OUI — ${(data.zv_info && data.zv_info.nom) || "zone inconnue"} (bassin ${
          (data.zv_info && data.zv_info.bassin) || "—"
        })`
      : "NON";

    const ci = communeInfo || {};
    const communeHtml = ci.nom
      ? `${ci.nom} (INSEE ${ci.code || "—"})`
      : "—";

    // Cadastre : id complet (14 car) + section + numero pour debug
    const parcelHtml = parcelInfo && parcelInfo.id
      ? `${parcelInfo.id} (section ${parcelInfo.section || "—"}, n° ${parcelInfo.number || "—"})`
      : "aucune parcelle cadastrale identifiée";

    debugEl.innerHTML = `
      <p class="nitrates-debug__title">Informations parcelle</p>
      <dl>
        <dt>Coordonnées</dt><dd>${data.lng.toFixed(5)}, ${data.lat.toFixed(5)}</dd>
        <dt>Commune</dt><dd>${communeHtml}</dd>
        <dt>Département</dt><dd>${data.department_code || "hors métropole"}</dd>
        <dt>Région</dt><dd>${
          data.region_code
            ? `${data.region_code} (${data.region_label})`
            : "—"
        }</dd>
        <dt>Parcelle cadastre</dt><dd>${parcelHtml}</dd>
        <dt>Zone vulnérable nitrates</dt><dd class="${zvClass}">${zvText}</dd>
      </dl>
    `;
  }

  function renderError(message) {
    if (!debugEl) return;
    debugEl.innerHTML = `<p class="nitrates-debug__placeholder">Erreur : ${message}</p>`;
  }

  // Panel "Commune / Departement / Region" sous la carte (visible meme
  // hors mode debug, c'est UX maquette).
  const localisationReadonly = document.getElementById(
    "nitrates-localisation-info"
  );
  const communeDisplay = document.getElementById("commune-display");
  const deptDisplay = document.getElementById("departement-display");
  const regionDisplay = document.getElementById("region-display");

  function updateLocalisationReadonly(data, communeNom) {
    if (!localisationReadonly) return;
    if (communeDisplay) communeDisplay.textContent = communeNom || "—";
    if (deptDisplay)
      deptDisplay.textContent = data.department_code || "—";
    if (regionDisplay) {
      const r = data.region_code
        ? `${data.region_label || ""} (${data.region_code})`
        : "—";
      regionDisplay.textContent = r;
    }
    localisationReadonly.hidden = false;
  }

  // Reverse geocode pour recuperer commune + code INSEE au clic carte.
  // Le code INSEE est utilise par le backend pour resoudre la zone
  // montagne (D113-14) sans avoir a charger les polygones de communes.
  async function fetchCommuneInfo(lat, lng) {
    try {
      const r = await fetch(
        `https://geo.api.gouv.fr/communes?lat=${lat}&lon=${lng}&fields=nom,code&format=json`
      );
      const arr = await r.json();
      if (Array.isArray(arr) && arr.length) {
        return { nom: arr[0].nom || null, code: arr[0].code || null };
      }
      return { nom: null, code: null };
    } catch {
      return { nom: null, code: null };
    }
  }

  // Reverse geocode parcellaire IGN : on appelle data.geopf.fr/geocodage
  // pour recuperer l'identifiant de la parcelle cadastrale au point
  // clique. Retourne {id, section, number, city} ou null si echec.
  async function fetchParcelInfo(lat, lng) {
    try {
      const r = await fetch(
        `https://data.geopf.fr/geocodage/reverse?lat=${lat}&lon=${lng}&index=parcel&limit=1`
      );
      const json = await r.json();
      const f = (json.features || [])[0];
      if (!f) return null;
      const p = f.properties || {};
      return {
        id: p.id || null,
        section: p.section || null,
        number: p.number || null,
        city: p.city || null,
      };
    } catch {
      return null;
    }
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
    Promise.all([
      fetch(url, { headers: { Accept: "application/json" } }).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      }),
      fetchCommuneInfo(lat, lng),
      fetchParcelInfo(lat, lng),
    ])
      .then(([data, communeInfo, parcelInfo]) => {
        renderDebug(data, communeInfo, parcelInfo);
        updateLocalisationReadonly(data, communeInfo.nom);
        // Pousse le code INSEE dans le hidden : il sera soumis avec
        // le form et utilise cote backend pour resoudre la zone
        // montagne (D113-14) sans charger les polygones communes.
        const codeInseeInput = document.getElementById("id_code_insee");
        if (codeInseeInput) codeInseeInput.value = communeInfo.code || "";
      })
      .catch((err) => renderError(err.message || String(err)));
  });

  // ─── Recherche commune BAN ─────────────────────────────────────────
  const searchInput = document.getElementById("map-search");
  const searchList = document.getElementById("map-search-list");
  if (searchInput && searchList) {
    let searchTimer = null;
    let searchResults = [];

    async function searchCommune(q) {
      if (q.length < 2) {
        closeSearch();
        return;
      }
      try {
        const res = await fetch(
          `https://api-adresse.data.gouv.fr/search/?q=${encodeURIComponent(q)}&type=municipality&limit=6`
        );
        const data = await res.json();
        renderSearch(data.features || []);
      } catch {
        closeSearch();
      }
    }

    function renderSearch(features) {
      searchResults = features;
      searchList.innerHTML = "";
      if (!features.length) {
        closeSearch();
        return;
      }
      features.forEach((f) => {
        const li = document.createElement("li");
        li.setAttribute("role", "option");
        li.textContent = f.properties.label;
        li.addEventListener("mousedown", (e) => {
          e.preventDefault();
          selectCommune(f);
        });
        searchList.appendChild(li);
      });
      searchList.hidden = false;
    }

    function selectCommune(feature) {
      const [lng, lat] = feature.geometry.coordinates;
      searchInput.value = feature.properties.label;
      closeSearch();
      map.flyTo([lat, lng], 13);
    }

    function closeSearch() {
      searchList.hidden = true;
      searchList.innerHTML = "";
    }

    searchInput.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(
        () => searchCommune(searchInput.value.trim()),
        250
      );
    });
    searchInput.addEventListener("blur", () =>
      setTimeout(closeSearch, 150)
    );
  }
})();
