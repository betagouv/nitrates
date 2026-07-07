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

  // Issues #89 + #96 : devoile la suite du form (Culture / Fertilisant /
  // Submit) quand l'utilisateur clique sur la carte. Initial state pose
  // cote serveur via `hidden` sur #form-after-localisation + message
  // #form-locked-message visible. Idempotent (peut etre appele plusieurs
  // fois sans effet de bord).
  function revealFormAfterLocalisation() {
    const formZone = document.getElementById("form-after-localisation");
    const lockedMsg = document.getElementById("form-locked-message");
    if (formZone) formZone.hidden = false;
    if (lockedMsg) lockedMsg.hidden = true;
    // Carte #154 : le form vient d'apparaitre, les questions cascade
    // deviennent visibles mais non repondues. On notifie cascade.js pour qu'il
    // (re)calcule l'etat du bouton « Lancer la simulation » (-> disabled tant
    // que le parcours n'est pas complet).
    document.dispatchEvent(new CustomEvent("nitrates:form-revealed"));
  }

  // ─── Carte #57 : bornage geographique ────────────────────────────────
  // Quand la parcelle cliquee est dans un departement non ouvert, on masque
  // le formulaire et on affiche un message dedie (#form-region-fermee).

  function masquerFormulaire() {
    const formZone = document.getElementById("form-after-localisation");
    const lockedMsg = document.getElementById("form-locked-message");
    if (formZone) formZone.hidden = true;
    if (lockedMsg) lockedMsg.hidden = true;
  }

  function masquerMessageFerme() {
    const fermee = document.getElementById("form-region-fermee");
    if (fermee) fermee.hidden = true;
  }

  function afficherMessageFerme(regionLabel, departmentCode) {
    const fermee = document.getElementById("form-region-fermee");
    if (!fermee) return;
    const lieu = document.getElementById("form-region-fermee-lieu");
    if (lieu) {
      if (regionLabel) {
        lieu.textContent = regionLabel;
      } else if (departmentCode) {
        lieu.textContent = "votre département (" + departmentCode + ")";
      } else {
        lieu.textContent = "votre secteur";
      }
    }
    fermee.hidden = false;
  }

  // keyboard: false (Carte #154, a11y) : par defaut Leaflet rend le conteneur
  // carte focusable (tabindex=0) et capture les fleches pour paner. Resultat :
  // au Tab, le focus se coincait sur la carte, les fleches ne naviguaient plus
  // dans les radios du formulaire, et "Entree sur la carte" ne faisait rien.
  // La carte s'opere a la souris / via la recherche : on la sort donc de
  // l'ordre de tabulation et on libere les fleches pour les radios.
  const map = L.map(mapEl, {
    attributionControl: false,
    keyboard: false,
  }).setView(INITIAL_CENTER, INITIAL_ZOOM);
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
  // Carte #193 : fond par defaut = Photo aerienne (ortho), pas le Plan IGN
  // (choix maquette : plus parlant pour reperer sa parcelle).
  photoLayer.addTo(map);

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
  // Carte #193 : Zones vulnerables DECOCHEES par defaut (l'utilisateur peut
  // les activer via la tickbox). On ne fait donc plus zvLayer.addTo(map).

  // Carte #34 : overlay ZAR (Zone d'Action Renforcée). Couvre toutes les ZAR
  // chargées (potentiellement plusieurs régions ; aujourd'hui le Grand Est).
  // Non affiché par défaut : c'est une tickbox que l'utilisateur active.
  const zarLayer = L.geoJSON(null, {
    style: () => ({
      color: "#c9191e",
      weight: 2.5,
      fillColor: "#ff1a1a",
      fillOpacity: 0.6,
    }),
    onEachFeature: (feature, layer) => {
      const p = feature.properties || {};
      const titre = p.nom_complet || p.nom || "ZAR";
      layer.bindTooltip(`${titre}${p.departement ? " (" + p.departement + ")" : ""}`, {
        sticky: true,
      });
    },
  });
  let zarLoaded = false;
  function loadZarIfNeeded() {
    if (zarLoaded) return;
    zarLoaded = true;
    fetch(window.NITRATES_ZAR_GEOJSON_URL)
      .then((r) => r.json())
      .then((data) => {
        zarLayer.addData(data);
        // ZAR au premier plan : sinon la ZV (ajoutée avant) la masque.
        zarLayer.bringToFront();
      })
      .catch((err) => console.error("ZAR GeoJSON load failed:", err));
  }
  zarLayer.on("add", function () {
    loadZarIfNeeded();
    // Si la couche est déjà chargée, on la repasse au premier plan au ré-add.
    if (zarLoaded) zarLayer.bringToFront();
  });

  L.control
    .layers(
      {
        "Plan IGN": planLayer,
        "Photo aérienne": photoLayer,
      },
      {
        "Cadastre": cadastreOverlay,
        "Zones vulnérables nitrates": zvLayer,
        "Zones d'action renforcée (ZAR)": zarLayer,
      },
      { collapsed: false }
    )
    .addTo(map);

  // Carte #193 : ZAR DECOCHEE par defaut (l'utilisateur peut l'activer via la
  // tickbox). On ne fait donc plus zarLayer.addTo(map) au chargement.

  let marker = null;

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

    const zarClass = data.en_zar
      ? "nitrates-debug__badge-yes"
      : "nitrates-debug__badge-no";
    const zarText = data.en_zar ? "OUI" : "NON";

    // Zones Est : affichees seulement en Grand Est (data.en_grand_est).
    const badge = (v) =>
      `<dd class="${v ? "nitrates-debug__badge-yes" : "nitrates-debug__badge-no"}">${v ? "OUI" : "NON"}</dd>`;
    const grandEstHtml = data.en_grand_est
      ? `<dt>En Grand Est</dt>${badge(true)}` +
        `<dt>Zone Grand Est 1</dt>${badge(data.zone_grand_est_1)}` +
        `<dt>Zone Grand Est 2</dt>${badge(data.zone_grand_est_2)}`
      : "";

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
        <dt>Code postal</dt><dd>${ci.codePostal || "—"}</dd>
        <dt>Département</dt><dd>${data.department_code || "hors métropole"}</dd>
        <dt>Région</dt><dd>${
          data.region_code
            ? `${data.region_code} (${data.region_label})`
            : "—"
        }</dd>
        <dt>Parcelle cadastre</dt><dd>${parcelHtml}</dd>
        <dt>Zone vulnérable nitrates</dt><dd class="${zvClass}">${zvText}</dd>
        <dt>Zone d'action renforcée (ZAR)</dt><dd class="${zarClass}">${zarText}</dd>
        ${grandEstHtml}
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
      // Carte #193 : on demande aussi codesPostaux (utile dans le panel debug).
      // Pas de requete supplementaire : c'est un champ de plus sur le meme appel.
      const r = await fetch(
        `https://geo.api.gouv.fr/communes?lat=${lat}&lon=${lng}&fields=nom,code,codesPostaux&format=json`
      );
      const arr = await r.json();
      if (Array.isArray(arr) && arr.length) {
        const c = arr[0];
        return {
          nom: c.nom || null,
          code: c.code || null,
          // Une commune peut avoir plusieurs codes postaux -> on les joint.
          codePostal: (c.codesPostaux || []).join(", ") || null,
        };
      }
      return { nom: null, code: null, codePostal: null };
    } catch {
      return { nom: null, code: null, codePostal: null };
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

  // Si lat/lng deja saisis (form pre-rempli depuis URL apres "Lancer
  // la simulation"), on positionne le marker, on repeuple le bandeau
  // localisation ET le panneau debug sans attendre un nouveau clic. Le
  // serveur nous a deja envoye le catalog dans window.NITRATES_CATALOG
  // (cf. template) ; on fetch juste commune (BAN) + parcelle (IGN).
  const initialLng = parseFloat(lngInput.value);
  const initialLat = parseFloat(latInput.value);
  if (!isNaN(initialLng) && !isNaN(initialLat)) {
    marker = L.marker([initialLat, initialLng]).addTo(map);
    map.setView([initialLat, initialLng], 13);
    if (window.NITRATES_CATALOG) {
      Promise.all([
        fetchCommuneInfo(initialLat, initialLng),
        fetchParcelInfo(initialLat, initialLng),
      ]).then(([communeInfo, parcelInfo]) => {
        updateLocalisationReadonly(window.NITRATES_CATALOG, communeInfo.nom);
        // Reconstruit le payload attendu par renderDebug a partir du
        // catalog serveur + lng/lat. Le bassin/bassin_label arrive sous
        // forme de zv_info pour matcher la structure de l'endpoint debug.
        const cat = window.NITRATES_CATALOG;
        renderDebug(
          {
            lng: initialLng,
            lat: initialLat,
            department_code: cat.department_code,
            region_code: cat.region_code,
            region_label: cat.region_label,
            en_zone_vulnerable: cat.en_zone_vulnerable,
            zv_info: cat.en_zone_vulnerable
              ? { nom: cat.bassin_label, bassin: cat.bassin }
              : null,
            // Champs ZAR / Zones Est : sans eux le panneau affichait ZAR=NON
            // au chargement par URL (ex bouton preview admin), alors que le
            // catalog serveur les connait.
            en_zar: cat.en_zar,
            en_grand_est: cat.en_grand_est,
            zone_grand_est_1: cat.zone_grand_est_1,
            zone_grand_est_2: cat.zone_grand_est_2,
          },
          communeInfo,
          parcelInfo
        );
      });
    }
  }

  // ─── Panneau de chargement localisation "fake progress" (Carte #154) ──
  // Le reverse-geocode (commune + parcelle + bornage) prend de 0.5 a plusieurs
  // secondes selon la connexion. On affiche une barre qui monte de facon
  // exponentielle vers ~90% (jamais 100% tant que ce n'est pas fini) : plus
  // rassurant qu'un spinner infini, sans mentir sur une duree qu'on ignore.
  const locLoadingEl = document.getElementById("nitrates-loc-loading");
  const locFillEl = locLoadingEl
    ? locLoadingEl.querySelector(".nitrates-loc-loading__fill")
    : null;
  let locLoadingTimer = null;

  function demarrerChargementLoc() {
    if (!locLoadingEl || !locFillEl) return;
    clearInterval(locLoadingTimer);
    locLoadingEl.hidden = false;
    // Le panneau est SOUS la carte : si l'utilisateur a la carte plein ecran il
    // ne le verrait pas. On l'amene dans le viewport pour que le chargement soit
    // visible (Carte #154). block:"nearest" -> ne bouge que si necessaire.
    requestAnimationFrame(() => {
      locLoadingEl.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    let pct = 0;
    locFillEl.style.width = "0%";
    // Approche asymptotique : a chaque tick on comble une fraction du chemin
    // restant vers 90% -> vite au debut, puis ralentit (effet "fake" naturel).
    locLoadingTimer = setInterval(() => {
      pct += (90 - pct) * 0.12;
      locFillEl.style.width = pct.toFixed(1) + "%";
    }, 120);
  }

  function terminerChargementLoc() {
    if (!locLoadingEl || !locFillEl) return;
    clearInterval(locLoadingTimer);
    // On finit a 100% puis on masque en douceur.
    locFillEl.style.width = "100%";
    setTimeout(() => {
      locLoadingEl.hidden = true;
      locFillEl.style.width = "0%";
    }, 300);
  }

  map.on("click", function (e) {
    const { lat, lng } = e.latlng;

    // Pre-remplit le form -- c'est l'objectif principal de cette page.
    lngInput.value = lng.toFixed(6);
    latInput.value = lat.toFixed(6);

    demarrerChargementLoc();

    // Carte #57 : on NE devoile PAS le formulaire immediatement. On attend
    // la reponse localisation (DebugView) qui indique si le simulateur est
    // ouvert pour ce departement. Si ouvert -> on revele le form ; sinon ->
    // message "pas encore ouvert". cf. .then() ci-dessous.

    if (marker) {
      marker.setLatLng(e.latlng);
    } else {
      marker = L.marker(e.latlng).addTo(map);
    }

    if (debugEl) {
      debugEl.innerHTML =
        '<p class="nitrates-debug__placeholder">Chargement…</p>';
    }

    // On resout d'abord la commune (code INSEE) puis on interroge l'endpoint
    // debug AVEC ce code : les Zones Est (ZGE1/ZGE2) se resolvent par INSEE
    // cote serveur, sinon elles ressortent toujours None dans le panneau.
    Promise.all([fetchCommuneInfo(lat, lng), fetchParcelInfo(lat, lng)])
      .then(([communeInfo, parcelInfo]) => {
        const code = communeInfo.code || "";
        const url =
          `${window.NITRATES_DEBUG_URL}?lng=${lng}&lat=${lat}` +
          (code ? `&code_insee=${encodeURIComponent(code)}` : "") +
          // Sur le root public (/), on demande l'application de l'ouverture
          // geographique (allowlist departement). Sur /simulateur (interne),
          // le flag reste false -> tout departement est accessible.
          (window.NITRATES_GEO_APPLIQUEE ? "&geo=1" : "");
        return fetch(url, { headers: { Accept: "application/json" } })
          .then((r) => {
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.json();
          })
          .then((data) => [data, communeInfo, parcelInfo]);
      })
      .then(([data, communeInfo, parcelInfo]) => {
        renderDebug(data, communeInfo, parcelInfo);
        updateLocalisationReadonly(data, communeInfo.nom);
        // Carte #57 : bornage geographique. Le backend renvoie
        // simulateur_ouvert selon le departement de la parcelle. Si ouvert,
        // on devoile le formulaire ; sinon on affiche le message "pas encore
        // ouvert" et on garde le formulaire masque.
        if (data.simulateur_ouvert) {
          masquerMessageFerme();
          revealFormAfterLocalisation();
        } else {
          masquerFormulaire();
          afficherMessageFerme(data.region_label, data.department_code);
        }
        // Pousse le code INSEE dans le hidden : il sera soumis avec
        // le form et utilise cote backend pour resoudre la zone
        // montagne (D113-14) sans charger les polygones communes.
        const codeInseeInput = document.getElementById("id_code_insee");
        if (codeInseeInput) codeInseeInput.value = communeInfo.code || "";
        terminerChargementLoc();
      })
      .catch((err) => {
        terminerChargementLoc();
        renderError(err.message || String(err));
      });
  });

  // Aucun lat/lng pre-rempli (arrivee sur `/` ou `/simulateur/` sans
  // parametres) : on NE pre-selectionne AUCUNE parcelle. La carte reste
  // sur sa vue Grand Est par defaut et l'utilisateur est invite a cliquer.
  // (Avant, un point ZAR etait pre-clique pour le confort dev, ce qui
  // declenchait un auto-scroll vers les questions sans laisser lire la
  // page d'accueil -- cf. #153.)

  // ─── Recherche commune BAN ─────────────────────────────────────────
  const searchInput = document.getElementById("map-search");
  const searchList = document.getElementById("map-search-list");
  if (searchInput && searchList) {
    let searchTimer = null;
    let searchResults = [];
    // Index de l'option surlignee au clavier (-1 = aucune). Sert a la
    // navigation fleches haut/bas + a la validation Entree (Carte #154, a11y).
    let activeIndex = -1;

    // ARIA combobox : le champ pilote la liste #map-search-list (role listbox).
    searchInput.setAttribute("role", "combobox");
    searchInput.setAttribute("aria-expanded", "false");
    searchInput.setAttribute("aria-autocomplete", "list");
    searchInput.setAttribute("aria-controls", "map-search-list");

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

    // Carte #193 : libelle de suggestion desambiguise pour les homonymes
    // (ex plusieurs "Saint-Martin"). L'API BAN renvoie `postcode` (code postal)
    // et un `context` du type "65, Hautes-Pyrenees, Occitanie". On affiche
    // "Nom — CP (Departement)" : le CP leve l'ambiguite, le departement aide a
    // choisir d'un coup d'oeil. On degrade proprement si un champ manque.
    function libelleSuggestion(props) {
      const nom = props.label || props.name || props.city || "";
      const cp = props.postcode || "";
      // Departement = 2e segment du context ("65, Hautes-Pyrenees, Occitanie").
      let departement = "";
      if (props.context) {
        const parts = props.context.split(",").map((s) => s.trim());
        if (parts.length >= 2) departement = parts[1];
      }
      let suffixe = "";
      if (cp && departement) suffixe = ` — ${cp} (${departement})`;
      else if (cp) suffixe = ` — ${cp}`;
      else if (departement) suffixe = ` (${departement})`;
      return nom + suffixe;
    }

    function renderSearch(features) {
      searchResults = features;
      activeIndex = -1;
      searchList.innerHTML = "";
      if (!features.length) {
        closeSearch();
        return;
      }
      features.forEach((f, i) => {
        const li = document.createElement("li");
        li.id = `map-search-opt-${i}`;
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", "false");
        // Carte #193 : libelle desambiguise "Nom — CP (Departement)" pour les
        // homonymes (donnees deja presentes dans la reponse BAN).
        li.textContent = libelleSuggestion(f.properties || {});
        // mousedown (pas click) : se declenche avant le blur du champ, evite
        // que closeSearch (sur blur) ne vide la liste avant la selection.
        li.addEventListener("mousedown", (e) => {
          e.preventDefault();
          selectCommune(f);
        });
        searchList.appendChild(li);
      });
      searchList.hidden = false;
      searchInput.setAttribute("aria-expanded", "true");
    }

    // Surligne l'option index (navigation clavier) : classe visuelle,
    // aria-selected, aria-activedescendant sur le champ, et scroll into view.
    function setActive(index) {
      const items = searchList.querySelectorAll("li");
      if (!items.length) return;
      // wrap-around haut/bas
      if (index < 0) index = items.length - 1;
      if (index >= items.length) index = 0;
      activeIndex = index;
      items.forEach((li, i) => {
        const on = i === index;
        li.classList.toggle("is-active", on);
        li.setAttribute("aria-selected", on ? "true" : "false");
        if (on) li.scrollIntoView({ block: "nearest" });
      });
      searchInput.setAttribute("aria-activedescendant", `map-search-opt-${index}`);
    }

    // Selection d'une commune (clic, Entree, ou fleches+Entree) : on place
    // TOUJOURS un point au centre de la commune EXACTEMENT comme un clic carte
    // (marker + reverse-geocode parcelle + reveal form). L'utilisateur voit un
    // point apparaitre et comprend qu'il peut recliquer ailleurs (Carte #154).
    function selectCommune(feature) {
      // BAN municipality : coordinates = centre de la commune (centre-ville).
      const [lng, lat] = feature.geometry.coordinates;
      // Dans le champ, on garde le libelle desambiguise : l'utilisateur voit
      // exactement quelle commune (parmi les homonymes) a ete retenue.
      searchInput.value = libelleSuggestion(feature.properties || {});
      closeSearch();
      // Une fois le form revele (apres le reverse-geocode async), on deplace le
      // focus sur le 1er radio de la 1re question (Carte #154, a11y) : Max veut
      // qu'apres selection d'une ville, Tab/Entree operent directement sur le
      // formulaire sans re-cliquer. once:true -> ne se declenche que pour CETTE
      // selection.
      document.addEventListener(
        "nitrates:form-revealed",
        () => {
          const premier = document.querySelector(
            '[data-cascade="categorie_culture"] input[type="radio"]'
          );
          if (premier) premier.focus();
        },
        { once: true }
      );
      map.setView([lat, lng], 13);
      // Rejoue toute la chaine du clic carte (cf. map.on("click")).
      map.fire("click", { latlng: L.latLng(lat, lng) });
    }

    function closeSearch() {
      searchList.hidden = true;
      searchList.innerHTML = "";
      activeIndex = -1;
      searchInput.setAttribute("aria-expanded", "false");
      searchInput.removeAttribute("aria-activedescendant");
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

    // Navigation clavier complete dans le champ de recherche (Carte #154, a11y) :
    //  - Fleche bas / haut : parcourt les suggestions (avec wrap-around).
    //  - Entree : selectionne l'option surlignee (ou la 1re si aucune), ce qui
    //    place le point. On preventDefault dans TOUS les cas ou une suggestion
    //    existe, pour ne jamais laisser le submit natif du <form> se declencher
    //    depuis ce champ (bug d'origine : auto-scroll + question fantome).
    //  - Echap : ferme la liste sans selectionner.
    searchInput.addEventListener("keydown", (e) => {
      const q = searchInput.value.trim();
      const ouvert = !searchList.hidden && searchResults.length > 0;
      if (e.key === "ArrowDown") {
        if (!searchResults.length) return;
        e.preventDefault();
        setActive(activeIndex + 1);
        return;
      }
      if (e.key === "ArrowUp") {
        if (!searchResults.length) return;
        e.preventDefault();
        setActive(activeIndex - 1);
        return;
      }
      // Tab quand le volet de suggestions est ouvert (Carte #154, a11y) : Max
      // veut que Tab parcoure les options COMME les fleches, au lieu de sortir
      // du champ. Tab = descendre, Shift+Tab = remonter. On ne laisse Tab
      // quitter le champ que si aucune suggestion n'est ouverte.
      if (e.key === "Tab" && ouvert) {
        e.preventDefault();
        setActive(activeIndex + (e.shiftKey ? -1 : 1));
        return;
      }
      if (e.key === "Escape") {
        closeSearch();
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        if (q.length < 2) return;
        if (searchResults.length) {
          // Option surlignee, sinon la premiere de la liste.
          const idx = activeIndex >= 0 ? activeIndex : 0;
          selectCommune(searchResults[idx]);
          return;
        }
        // Pas encore de suggestions (frappe trop rapide) : requete a la volee.
        clearTimeout(searchTimer);
        fetch(
          `https://api-adresse.data.gouv.fr/search/?q=${encodeURIComponent(q)}&type=municipality&limit=1`
        )
          .then((res) => res.json())
          .then((data) => {
            const feature = (data.features || [])[0];
            if (feature) selectCommune(feature);
          })
          .catch(() => {});
      }
    });
  }
})();
