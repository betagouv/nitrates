// JS du formulaire /simulateur/ : carte cliquable qui pre-remplit les
// inputs lat/lng + meme panneau debug que la home (sans toucher au JS de
// la home, qui est utilise comme demonstrateur).
//
// On factorise un jour si besoin, pour l'instant c'est une variante.

(function () {
  "use strict";

  // #531 : vue par defaut centree France (echelle ~100 km), plus Grand Est.
  const INITIAL_CENTER = [46.6, 2.45];
  const INITIAL_ZOOM = 6;

  // Couleur par bassin DCE, editable dans l'admin (CouleurZone) et injectee
  // dans la page (json_script). La palette ci-dessous n'est qu'un filet si
  // l'injection manque ; elle reprend le seed de la migration 0038.
  const ZV_COLORS_BY_BASSIN = Object.assign(
    {
      FRA: "#00b0ff",
      FRB2: "#00b0ff",
      "FRB1-FRC": "#7c4dff",
      FRB1: "#7c4dff",
      FRC: "#7c4dff",
      FRD: "#00c853",
      FRF: "#ff6d00",
      FRG: "#f50057",
      FRH: "#ffd600",
    },
    (function () {
      const el = document.getElementById("nitrates-zv-couleurs");
      try {
        return el ? JSON.parse(el.textContent) : {};
      } catch (e) {
        return {};
      }
    })()
  );
  const ZV_COLOR_FALLBACK = ZV_COLORS_BY_BASSIN["*"] || "#a06fc7";
  // Couleurs vives + remplissage leger : le fond doit rester lisible sous la
  // couche. La photo, plus chargee, supporte moins de remplissage que le plan.
  const ZV_FILL_OPACITY_PAR_FOND = { plan: 0.2, photo: 0.15 };
  let zvFillOpacity = ZV_FILL_OPACITY_PAR_FOND.photo;

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
  // Carte #154 : apres un choix de lieu au clavier (recherche commune, ou
  // Entree sur la carte #531), le focus passe au 1er radio de la 1re question
  // des que le form est revele, pour enchainer au clavier. once:true -> ne se
  // declenche que pour CE choix.
  function focusFormulaireApresRevelation() {
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
  }

  // #531 : place le point de depart de la navigation au Tab juste avant la 1re
  // question visible, SANS deplacer la vue ni activer de radio (focus sur son
  // fieldset, rendu focusable le temps de ce focus). Pas en plein ecran : sortir
  // le focus de la carte en fermerait le plein ecran.
  // Les radios du flow culture/couvert (#272) sont rendus juste APRES
  // l'evenement form-revealed (jusqu'a ~5 s sur un serveur lent) : on reessaie.
  // 1er choix visible de la 1re question (« culture ou couvert », #272).
  function premierRadioFormulaire() {
    const zone = document.getElementById("form-after-localisation");
    if (!zone || zone.hidden) return null;
    return (
      Array.from(zone.querySelectorAll('input[type="radio"]')).find(
        (r) => r.offsetParent !== null && !r.disabled
      ) || null
    );
  }

  function poserDepartTabFormulaire(essai) {
    essai = typeof essai === "number" ? essai : 0;
    if (mapEl.classList.contains("nitrates-map--plein-ecran") || document.fullscreenElement) {
      return;
    }
    // L'utilisateur a deja repris la main ailleurs : on ne lui vole pas le focus.
    if (document.activeElement !== mapEl && document.activeElement !== document.body) {
      return;
    }
    const radio = premierRadioFormulaire();
    if (!radio) {
      if (essai < 50) setTimeout(() => poserDepartTabFormulaire(essai + 1), 100);
      return;
    }
    const bloc =
      radio.closest("fieldset, .fr-fieldset, [role='radiogroup']") || radio.parentElement;
    bloc.setAttribute("tabindex", "-1");
    bloc.classList.add("nitrates-depart-tab");
    bloc.addEventListener(
      "blur",
      () => {
        bloc.removeAttribute("tabindex");
        bloc.classList.remove("nitrates-depart-tab");
      },
      { once: true }
    );
    bloc.focus({ preventScroll: true });
  }

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

  // #437 : la mention « *Champs obligatoires » ne s'affiche que quand le
  // formulaire est visible. #form-after-localisation.hidden est la source de
  // vérité (togglé ici, par recap_choix.js et par le retour saisie) -> on
  // observe cet attribut plutôt que de dupliquer la condition partout.
  (function () {
    const formZone = document.getElementById("form-after-localisation");
    const mention = document.getElementById("mention-champs-obligatoires");
    if (!formZone || !mention) return;
    const sync = function () {
      mention.hidden = formZone.hidden;
    };
    new MutationObserver(sync).observe(formZone, {
      attributes: true,
      attributeFilter: ["hidden"],
    });
    sync();
  })();

  // #271 : re-clic carte sur une page résultat. On ne réévalue le backend que si
  // le SCOPE d'interprétation change ; sinon on garde le résultat affiché.
  //
  // Champs de scope comparés (ceux qui pilotent l'arbre / la région / les zones) :
  //   en_zone_vulnerable, en_zar, region_code, zone_grand_est_1/2, et le code
  //   INSEE (dont dépendent la zone montagne D113-14 et la note 5).
  function scopeDepuisData(data, codeInsee) {
    return {
      zv: !!data.en_zone_vulnerable,
      zar: !!data.en_zar,
      region: data.region_code || "",
      zge1: !!data.zone_grand_est_1,
      zge2: !!data.zone_grand_est_2,
      zmb: data.zone_mais_bretagne || "",
      insee: codeInsee || "",
    };
  }

  function scopeDepuisCatalog(cat, ancienInsee) {
    if (!cat) return null;
    return {
      zv: !!cat.en_zone_vulnerable,
      zar: !!cat.en_zar,
      region: cat.region_code || "",
      zge1: !!cat.zone_grand_est_1,
      zge2: !!cat.zone_grand_est_2,
      zmb: cat.zone_mais_bretagne || "",
      // Le catalog ne porte pas le code INSEE : on passe l'ancien code capturé
      // AVANT écrasement du hidden (celui de la simulation en cours).
      insee: ancienInsee || "",
    };
  }

  function scopesDifferents(a, b) {
    if (!a || !b) return true;
    if (
      a.zv !== b.zv ||
      a.zar !== b.zar ||
      a.region !== b.region ||
      a.zge1 !== b.zge1 ||
      a.zge2 !== b.zge2
    ) {
      return true;
    }
    // Code INSEE : ne le compare QUE si l'ancien est connu (une simulation
    // lancée par clic carte l'a renseigné). Si l'ancien est vide (résultat
    // rejoué depuis une URL sans code_insee), on ne déclenche pas une
    // invalidation sur la seule commune -> les zones (ci-dessus) suffisent.
    if (a.insee && a.insee !== b.insee) return true;
    return false;
  }

  // Scope de RÉFÉRENCE de la simulation actuellement affichée. On l'établit à
  // partir de la MÊME source que le re-clic (DebugView), pour comparer des
  // valeurs cohérentes (le catalog moulinette peut diverger de DebugView sur
  // certains champs, ex zone_grand_est_2 sans code_insee). Renseigné au 1er
  // re-clic si absent (le scope de référence = celui du point qui a produit le
  // résultat, dont les coordonnées sont dans les hidden lat/lng).
  let scopeReference = null;

  function gererReclicCarteResultat(data, nouveauInsee, ancienInsee) {
    const form = document.getElementById("form-simulateur");
    // Rien à faire si on n'est pas sur une page résultat affiché.
    if (!form || !form.hasAttribute("data-resultat-affiche")) return;

    const nouveau = scopeDepuisData(data, nouveauInsee);

    // Établit la référence si pas encore connue : on interroge DebugView sur le
    // point d'ORIGINE (lat/lng du résultat affiché, avant ce re-clic). Comme
    // c'est asynchrone et qu'on veut une décision immédiate, on retombe sur le
    // catalog moulinette pour cette première comparaison, puis on mémorise la
    // référence DebugView pour les fois suivantes.
    const ref =
      scopeReference || scopeDepuisCatalog(window.NITRATES_CATALOG, ancienInsee);

    if (!scopesDifferents(ref, nouveau)) {
      // Même scope géographique : le résultat reste valide. On mémorise le
      // nouveau scope comme référence (DebugView, cohérent) pour la suite.
      scopeReference = nouveau;
      return;
    }

    // Scope changé -> le résultat n'est plus valide. On l'invalide et on repasse
    // en mode saisie, en forçant un re-clic « Lancer la simulation ».
    form.removeAttribute("data-resultat-affiche");
    const resultCol = document.querySelector(".result-col");
    if (resultCol) resultCol.remove();
    const row = document.querySelector(".results-row");
    if (row) row.classList.remove("layout--split");
    const formCol = document.querySelector(".form-col");
    if (formCol) formCol.classList.remove("fr-col-lg-4");
    // Masque l'encart récap, ré-affiche le formulaire complet.
    const recap = document.getElementById("recap-choix");
    if (recap) recap.hidden = true;
    const formApres = document.getElementById("form-after-localisation");
    if (formApres) formApres.hidden = false;
    // Ré-affiche le bouton « Lancer la simulation » (masqué sur page résultat).
    const submitRow = document.getElementById("form-submit-row");
    if (submitRow) submitRow.hidden = false;
    // Notifie les autres modules (recap_choix / reset_form / flow) du retour saisie.
    document.dispatchEvent(new Event("nitrates:retour-saisie"));
    // Le scope courant est désormais celui du nouveau point : on met à jour le
    // catalog en mémoire pour les comparaisons suivantes (avant re-soumission).
    window.NITRATES_CATALOG = Object.assign({}, window.NITRATES_CATALOG || {}, {
      en_zone_vulnerable: nouveau.zv,
      en_zar: nouveau.zar,
      region_code: nouveau.region,
      zone_grand_est_1: nouveau.zge1,
      zone_grand_est_2: nouveau.zge2,
      zone_mais_bretagne: nouveau.zmb,
    });
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

  function afficherMessageFerme(regionLabel, departmentCode, regionCode) {
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
    // #287 : mémorise la région tentée (envoyée avec l'email d'intérêt) et
    // réarme le mini-formulaire (au cas où on reclique une autre zone fermée).
    fermee.setAttribute("data-region-code", regionCode || "");
    const alerte = fermee.querySelector("[data-region-alerte]");
    const merci = fermee.querySelector("[data-region-alerte-merci]");
    if (alerte) alerte.hidden = false;
    if (merci) merci.hidden = true;
    fermee.hidden = false;
  }

  // keyboard: false (Carte #154, a11y) : par defaut Leaflet rend le conteneur
  // carte focusable (tabindex=0) et capture les fleches pour paner. Resultat :
  // au Tab, le focus se coincait sur la carte, les fleches ne naviguaient plus
  // dans les radios du formulaire, et "Entree sur la carte" ne faisait rien.
  // La carte s'opere a la souris / via la recherche : on la sort donc de
  // l'ordre de tabulation et on libere les fleches pour les radios.
  // #531 : la carte redevient focusable, mais avec notre propre handler clavier
  // qui n'agit que si le focus est sur la carte (cf. plus bas).
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

  const wmts = (layer, format, extra) =>
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
        // #531 : pas de tuiles intermediaires pendant l'animation de zoom
        // (requetes jetees aussitot), on charge au niveau d'arrivee.
        updateWhenZooming: false,
        ...extra,
      }
    );

  const planLayer = wmts("GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2", "png");
  const photoLayer = wmts("ORTHOIMAGERY.ORTHOPHOTOS", "jpeg");
  // Carte #193 : fond par defaut = Photo aerienne (ortho), pas le Plan IGN
  // (choix maquette : plus parlant pour reperer sa parcelle). #531 : le defaut
  // devient le mode « Automatique » (cf. autoLayer), ajoute plus bas apres
  // lecture des couches memorisees.

  // #583 : parcelles RPG (Registre Parcellaire Graphique, parcelles declarees
  // a la PAC) en couche principale. La couche cadastre (parcelles) est
  // remplacee par « Communes » (limites + noms, cf. plus bas). Contours en tuiles vectorielles IGN dessinees en canvas
  // (cf. rpg_parcelle.js), rien en base chez nous. Pane au-dessus des ZV/ZAR
  // (sinon leur remplissage noie les contours), sans evenements souris : les
  // infobulles ZV/ZAR et le clic carte passent au travers.
  const rpg = window.NitratesRpg;
  [
    ["nitratesCommunes", 440],
    ["nitratesRpg", 450],
    ["nitratesSelection", 460],
    ["nitratesCommunesNoms", 470],
  ].forEach(([nom, z]) => {
    const pane = map.createPane(nom);
    pane.style.zIndex = z;
    pane.style.pointerEvents = "none";
  });
  // Blanc sur photo aerienne, gris fonce sur plan IGN (cf. majContourRpg).
  let couleurContourRpg = "#ffffff";
  function coucheRpg() {
    // VectorGrid absent (script bloque) : couche vide, la carte marche quand meme.
    if (!rpg || !L.vectorGrid) return L.layerGroup();
    const couche = L.vectorGrid.protobuf(rpg.URL_TUILES, {
      pane: "nitratesRpg",
      rendererFactory: L.canvas.tile,
      interactive: false,
      // Pas de minZoom : Leaflet griserait la case en vue large. Les tuiles
      // sous ZOOM_AFFICHAGE_MIN sont court-circuitees plus bas. Pas
      // d'attribution : « © IGN » est deja affiche par les fonds.
      maxNativeZoom: rpg.ZOOM_NATIF_MAX,
      maxZoom: 22,
      updateWhenZooming: false,
      vectorTileLayerStyles: {
        [rpg.COUCHE_TUILES]: () => ({
          color: couleurContourRpg,
          weight: 1.2,
          opacity: 0.9,
          fill: false,
        }),
      },
    });
    // Trop dezoome : tuile vide, sans requete ni dessin.
    const tuileIgn = couche._getVectorTilePromise;
    couche._getVectorTilePromise = function (coords) {
      if (coords.z < rpg.ZOOM_AFFICHAGE_MIN) return Promise.resolve({ layers: {} });
      return tuileIgn.call(this, coords);
    };
    return couche;
  }
  const rpgOverlay = coucheRpg();

  // #583 : couche « Communes » = limites des communes en violet (le blanc est
  // pris par le RPG, l'orange du cadastre IGN par une ZV) + leurs noms, sans
  // les parcelles cadastrales, redondantes avec le RPG (cf. communes_carte.js).
  const communesCarte = window.NitratesCommunes;
  const COULEUR_COMMUNES = "#6a1b9a";
  // Noms recharges apres chaque deplacement, une fois la carte posee.
  const DELAI_NOMS_COMMUNES_MS = 250;
  function coucheCommunes() {
    if (!communesCarte || !L.vectorGrid) return L.layerGroup();
    const styles = {
      [communesCarte.COUCHE_COMMUNE]: {
        color: COULEUR_COMMUNES,
        weight: 2,
        opacity: 0.9,
        dashArray: "6,4",
        fill: false,
      },
    };
    communesCarte.COUCHES_MASQUEES.forEach((k) => {
      styles[k] = [];
    });
    const limites = L.vectorGrid.protobuf(communesCarte.URL_TUILES, {
      pane: "nitratesCommunes",
      rendererFactory: L.canvas.tile,
      interactive: false,
      // Plus pres, on agrandit les tuiles du 14 : celles du 15+ embarquent
      // toutes les parcelles cadastrales, lourdes et inutiles ici.
      maxNativeZoom: communesCarte.ZOOM_TUILES_MAX,
      maxZoom: 22,
      updateWhenZooming: false,
      vectorTileLayerStyles: styles,
    });
    // Trop dezoome : pas encore de communes dans les tuiles, aucune requete.
    const tuileIgn = limites._getVectorTilePromise;
    limites._getVectorTilePromise = function (coords) {
      if (coords.z < communesCarte.ZOOM_TUILES_MIN) return Promise.resolve({ layers: {} });
      return tuileIgn.call(this, coords);
    };

    const noms = L.layerGroup();
    const groupe = L.layerGroup([limites, noms]);
    let ctrl = null;
    let timer = null;

    // Zoome pres, le chef-lieu (qui porte le nom) est souvent hors champ : on
    // affiche alors en bas a gauche le nom de la commune au centre de la carte.
    const encart = L.control({ position: "bottomleft" });
    encart.onAdd = () => {
      const el = L.DomUtil.create("div", "nitrates-commune-courante");
      el.hidden = true;
      return el;
    };
    function majEncart(nom) {
      const el = encart.getContainer();
      if (!el) return;
      el.textContent = nom ? "Commune : " + nom : "";
      el.hidden = !nom;
    }
    function nomAuCentre(monCtrl) {
      const c = map.getCenter();
      return fetch(
        `https://geo.api.gouv.fr/communes?lat=${c.lat}&lon=${c.lng}&fields=nom&format=json`,
        monCtrl ? { signal: monCtrl.signal } : {}
      )
        .then((r) => (r.ok ? r.json() : []))
        .then((arr) => (Array.isArray(arr) && arr.length ? arr[0].nom : null));
    }

    function chargerNoms() {
      if (ctrl) ctrl.abort();
      ctrl = null;
      if (!map.hasLayer(groupe) || map.getZoom() < communesCarte.ZOOM_NOMS_MIN) {
        noms.clearLayers();
        majEncart(null);
        return;
      }
      const b = map.getBounds();
      const monCtrl = typeof AbortController !== "undefined" ? new AbortController() : null;
      ctrl = monCtrl;
      fetch(
        communesCarte.urlNomsCommunes({
          sud: b.getSouth(),
          ouest: b.getWest(),
          nord: b.getNorth(),
          est: b.getEast(),
        }),
        monCtrl ? { signal: monCtrl.signal } : {}
      )
        .then((r) => {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then((data) => {
          if (ctrl !== monCtrl) return null;
          noms.clearLayers();
          const liste = communesCarte.nomsDepuisWfs(data);
          liste.forEach((c) => {
            const texte = document.createElement("span");
            texte.textContent = c.nom;
            L.marker([c.lat, c.lng], {
              pane: "nitratesCommunesNoms",
              interactive: false,
              keyboard: false,
              icon: L.divIcon({ className: "nitrates-commune-nom", html: texte, iconSize: null }),
            }).addTo(noms);
          });
          if (liste.length) {
            majEncart(null);
            return null;
          }
          return nomAuCentre(monCtrl).then((nom) => {
            if (ctrl === monCtrl) majEncart(nom);
          });
        })
        .catch((err) => {
          if (err && err.name === "AbortError") return;
          console.warn("Communes : noms IGN en echec", err);
        });
    }
    function planifierNoms() {
      clearTimeout(timer);
      timer = setTimeout(chargerNoms, DELAI_NOMS_COMMUNES_MS);
    }

    groupe.on("add", () => {
      encart.addTo(map);
      map.on("moveend", planifierNoms);
      chargerNoms();
    });
    groupe.on("remove", () => {
      encart.remove();
      map.off("moveend", planifierNoms);
      clearTimeout(timer);
      if (ctrl) ctrl.abort();
      ctrl = null;
      noms.clearLayers();
    });
    return groupe;
  }
  const communesOverlay = coucheCommunes();

  // #531 : chargement des couches ZV / ZAR a la 1re activation, avec une
  // ligne d'etat par couche dans la legende (visible aussi en plein ecran) :
  // « Chargement des zones vulnerables… » + barre facon chargement de
  // localisation (#154). Une ligne par couche -> ZV et ZAR peuvent charger en
  // meme temps sans se marcher dessus. Decocher pendant le chargement masque la
  // ligne mais laisse finir la requete (la recocher reprend ou elle en est).
  // En cas d'echec : message + bouton « Réessayer ».
  const chargementsEl = L.DomUtil.create("div", "nitrates-map-chargements");
  chargementsEl.setAttribute("role", "status");
  chargementsEl.setAttribute("aria-live", "polite");

  function coucheDifferee(layer, url, libelle, apresChargement) {
    let etat = "vide"; // vide | encours | ok | erreur
    let pct = 0;
    let timer = null;
    const ligne = L.DomUtil.create("div", "nitrates-map-chargement", chargementsEl);
    ligne.hidden = true;
    const texte = L.DomUtil.create("p", "nitrates-map-chargement__texte", ligne);
    const barre = L.DomUtil.create("div", "nitrates-loc-loading__bar", ligne);
    const fill = L.DomUtil.create("div", "nitrates-loc-loading__fill", barre);
    const reessayer = L.DomUtil.create("button", "nitrates-map-chargement__reessayer", ligne);
    reessayer.type = "button";
    reessayer.textContent = "Réessayer";
    L.DomEvent.on(reessayer, "click", charger);

    function maj() {
      const utile = etat === "encours" || etat === "erreur";
      ligne.hidden = !(utile && map.hasLayer(layer));
      texte.textContent =
        etat === "erreur"
          ? `Échec du chargement des ${libelle}.`
          : `Chargement des ${libelle}…`;
      barre.hidden = etat === "erreur";
      reessayer.hidden = etat !== "erreur";
    }

    function charger() {
      if (etat === "encours" || etat === "ok") return;
      etat = "encours";
      pct = 0;
      fill.style.width = "0%";
      clearInterval(timer);
      timer = setInterval(() => {
        pct += (90 - pct) * 0.08;
        fill.style.width = pct.toFixed(1) + "%";
      }, 120);
      maj();
      fetch(url)
        .then((r) => {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then((data) => {
          layer.addData(data);
          if (apresChargement) apresChargement();
          etat = "ok";
          clearInterval(timer);
          fill.style.width = "100%";
          setTimeout(maj, 300);
        })
        .catch((err) => {
          console.error(`${libelle} : chargement GeoJSON en échec`, err);
          etat = "erreur";
          clearInterval(timer);
          maj();
        });
    }

    layer.on("add", charger);
    layer.on("add remove", maj);
    return { estCharge: () => etat === "ok" };
  }

  // #531 a11y : Leaflet pose un listener « focus » sur chaque polygone a
  // info-bulle (ZV, ZAR), ce qui suffit a Chrome pour rendre le <path> SVG
  // tabulable : des centaines d'arrets de Tab sans interet, qui noient la
  // legende et la carte. tabindex=-1 explicite a chaque rendu (le <path> est
  // recree quand la couche est re-cochee).
  function horsTabulation(layer) {
    layer.on("add", () => {
      const el = layer.getElement && layer.getElement();
      if (el) el.setAttribute("tabindex", "-1");
    });
  }

  const zvLayer = L.geoJSON(null, {
    style: (feature) => {
      const bassin = (feature.properties || {}).bassin;
      const color = ZV_COLORS_BY_BASSIN[bassin] || ZV_COLOR_FALLBACK;
      return {
        color: color,
        weight: 1.5,
        fillColor: color,
        fillOpacity: zvFillOpacity,
      };
    },
    onEachFeature: (feature, layer) => {
      horsTabulation(layer);
      const p = feature.properties || {};
      layer.bindTooltip(`${p.nom || "ZV"} (bassin ${p.bassin || "?"})`, {
        sticky: true,
      });
    },
  });
  coucheDifferee(zvLayer, window.NITRATES_ZV_GEOJSON_URL, "zones vulnérables", () => {
    // ZV chargee apres la ZAR (couches restaurees, #531) : garder la ZAR devant.
    if (map.hasLayer(zarLayer)) zarLayer.bringToFront();
  });
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
      horsTabulation(layer);
      const p = feature.properties || {};
      const titre = p.nom_complet || p.nom || "ZAR";
      layer.bindTooltip(`${titre}${p.departement ? " (" + p.departement + ")" : ""}`, {
        sticky: true,
      });
    },
  });
  const zarChargement = coucheDifferee(
    zarLayer,
    window.NITRATES_ZAR_GEOJSON_URL,
    "zones d'action renforcée",
    // ZAR au premier plan : sinon la ZV (ajoutée avant) la masque.
    () => zarLayer.bringToFront()
  );
  zarLayer.on("add", function () {
    // Si la couche est déjà chargée, on la repasse au premier plan au ré-add.
    if (zarChargement.estCharge()) zarLayer.bringToFront();
  });

  const prefs = window.NitratesCartePrefs;

  // #531 : fond « Automatique » = on ne charge que ce qui est utile au zoom
  // courant (cf. couchesAuto). #583 : il ne gere plus que le fond ; le
  // cadastre qu'il ajoutait une fois zoome est remplace par la case
  // « Parcelles agricoles (RPG) », cochee par defaut. (Un RPG ajoute par le
  // mode auto revenait des qu'on decochait la case.) Instances propres (et non
  // photoLayer) : sinon le controle de couches cocherait « Photo aerienne » a
  // la place de l'utilisateur.
  const autoFonds = {
    plan: wmts("GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2", "png"),
    photo: wmts("ORTHOIMAGERY.ORTHOPHOTOS", "jpeg"),
  };
  const autoLayer = L.layerGroup();
  function syncAuto() {
    const voulu = prefs ? prefs.couchesAuto(map.getZoom()) : { fond: "photo" };
    Object.keys(autoFonds).forEach((k) => {
      if (k === voulu.fond) autoLayer.addLayer(autoFonds[k]);
      else autoLayer.removeLayer(autoFonds[k]);
    });
    majOpaciteZv();
  }

  function fondPlan() {
    return map.hasLayer(planLayer) || map.hasLayer(autoFonds.plan);
  }

  // Remplissage ZV selon le fond reellement affiche (le mode automatique
  // peut basculer de l'un a l'autre au zoom).
  function majOpaciteZv() {
    majContourRpg();
    const o = ZV_FILL_OPACITY_PAR_FOND[fondPlan() ? "plan" : "photo"];
    if (o === zvFillOpacity) return;
    zvFillOpacity = o;
    zvLayer.setStyle({ fillOpacity: o });
  }

  // #583 : contour RPG blanc illisible sur le plan IGN (fond clair).
  function majContourRpg() {
    const c = fondPlan() ? "#4d4d4d" : "#ffffff";
    if (c === couleurContourRpg) return;
    couleurContourRpg = c;
    if (rpgOverlay.redraw && map.hasLayer(rpgOverlay)) rpgOverlay.redraw();
  }
  map.on("baselayerchange", majOpaciteZv);
  autoLayer.on("add", () => {
    syncAuto();
    map.on("zoomend overlayadd overlayremove", syncAuto);
  });
  autoLayer.on("remove", () => {
    map.off("zoomend overlayadd overlayremove", syncAuto);
    autoLayer.clearLayers();
  });

  // #531 : couches memorisees (localStorage) sinon reglage par defaut : mode
  // automatique + RPG, communes, ZV et ZAR cochees (#583, avant : aucune).
  const fonds = { auto: autoLayer, plan: planLayer, photo: photoLayer };
  const surcouches = {
    rpg: rpgOverlay,
    communes: communesOverlay,
    zv: zvLayer,
    zar: zarLayer,
  };
  let storage = null;
  try {
    storage = window.localStorage;
  } catch (e) {
    storage = null;
  }
  const couches = (prefs &&
    prefs.lireCouches(storage, Object.keys(fonds), Object.keys(surcouches))) ||
    (prefs && prefs.couchesParDefaut()) || {
      base: "auto",
      surcouches: ["rpg", "communes", "zv", "zar"],
    };
  fonds[couches.base].addTo(map);
  majOpaciteZv();
  // Ordre fixe (rpg, communes, zv, zar) : la ZAR reste au-dessus de la ZV.
  Object.keys(surcouches).forEach((k) => {
    if (couches.surcouches.includes(k)) surcouches[k].addTo(map);
  });

  function memoriserCouches() {
    if (!prefs) return;
    const base = Object.keys(fonds).find((k) => map.hasLayer(fonds[k]));
    prefs.ecrireCouches(storage, {
      base: base || "auto",
      surcouches: Object.keys(surcouches).filter((k) =>
        map.hasLayer(surcouches[k])
      ),
    });
  }
  map.on("baselayerchange overlayadd overlayremove", memoriserCouches);

  const layersControl = L.control
    .layers(
      {
        "Automatique (selon le zoom)": autoLayer,
        "Plan IGN": planLayer,
        "Photo aérienne": photoLayer,
      },
      {
        "Parcelles agricoles (RPG)": rpgOverlay,
        "Communes": communesOverlay,
        "Zones vulnérables nitrates": zvLayer,
        "Zones d'action renforcée (ZAR)": zarLayer,
      },
      { collapsed: false }
    )
    .addTo(map);

  // #531 : plein ecran. Bouton sous le zoom, 1er arret de Tab apres la carte.
  // API Fullscreen si dispo (Echap natif du navigateur), sinon repli CSS
  // (iPhone) avec Echap gere ici. Jamais enferme : bouton toujours visible,
  // Echap sort, et sortir du cadre carte au Tab quitte aussi le plein ecran.
  const ICONE_PLEIN_ECRAN =
    '<svg aria-hidden="true" focusable="false" viewBox="0 0 49 49" fill="none" xmlns="http://www.w3.org/2000/svg">' +
    '<path fill-rule="evenodd" clip-rule="evenodd" d="M39.6277 10.7278L31.0208 19.3347L29.6066 17.9204L38.2135 9.31354L30.6277 9.31354L30.6277 7.31384H41.6274V18.3136L39.6277 18.3136V10.7278Z" fill="currentColor"/>' +
    '<path fill-rule="evenodd" clip-rule="evenodd" d="M38.3997 39.6276L29.7928 31.0207L31.207 29.6065L39.8139 38.2134L39.8139 30.6276L41.8136 30.6276L41.8136 41.6273L30.8138 41.6273L30.8138 39.6276L38.3997 39.6276Z" fill="currentColor"/>' +
    '<path fill-rule="evenodd" clip-rule="evenodd" d="M9.49958 38.3997L18.1065 29.7928L19.5207 31.207L10.9138 39.8139L18.4996 39.8139L18.4996 41.8136L7.49988 41.8136L7.49988 30.8138L9.49958 30.8138L9.49958 38.3997Z" fill="currentColor"/>' +
    '<path fill-rule="evenodd" clip-rule="evenodd" d="M10.7276 9.49958L19.3345 18.1065L17.9203 19.5207L9.31342 10.9138L9.31342 18.4996L7.31372 18.4996V7.49988H18.3135L18.3135 9.49958H10.7276Z" fill="currentColor"/>' +
    "</svg>";
  const ICONE_QUITTER_PLEIN_ECRAN =
    '<svg aria-hidden="true" focusable="false" viewBox="0 0 49 49" fill="none" xmlns="http://www.w3.org/2000/svg">' +
    '<path fill-rule="evenodd" clip-rule="evenodd" d="M32.3134 15.2134L40.9203 6.60651L42.3346 8.02072L33.7276 16.6276L41.3135 16.6276L41.3135 18.6273L30.3137 18.6273L30.3137 7.62757L32.3134 7.62757L32.3134 15.2134Z" fill="currentColor"/>' +
    '<path fill-rule="evenodd" clip-rule="evenodd" d="M33.9138 32.3135L42.5207 40.9204L41.1065 42.3347L32.4996 33.7278L32.4996 41.3136L30.4999 41.3136L30.4999 30.3138L41.4996 30.3138L41.4996 32.3135L33.9138 32.3135Z" fill="currentColor"/>' +
    '<path fill-rule="evenodd" clip-rule="evenodd" d="M16.8139 33.9138L8.20699 42.5207L6.79277 41.1065L15.3997 32.4996L7.81384 32.4996L7.81384 30.4999H18.8136V41.4996L16.8139 41.4996V33.9138Z" fill="currentColor"/>' +
    '<path fill-rule="evenodd" clip-rule="evenodd" d="M15.2135 16.8139L6.60661 8.207L8.02083 6.79278L16.6277 15.3997L16.6277 7.81384L18.6274 7.81384V18.8136H7.62767L7.62767 16.8139H15.2135Z" fill="currentColor"/>' +
    "</svg>";

  const pleinEcran = (function () {
    const CLASSE_REPLI = "nitrates-map--plein-ecran";
    let bouton = null;

    function natif() {
      return document.fullscreenElement === mapEl;
    }
    function actif() {
      return natif() || mapEl.classList.contains(CLASSE_REPLI);
    }
    function majBouton() {
      if (!bouton) return;
      const on = actif();
      bouton.innerHTML = on ? ICONE_QUITTER_PLEIN_ECRAN : ICONE_PLEIN_ECRAN;
      const label = on
        ? "Quitter le plein écran (Échap)"
        : "Afficher la carte en plein écran";
      bouton.setAttribute("aria-label", label);
      bouton.setAttribute("title", label);
      bouton.setAttribute("aria-pressed", on ? "true" : "false");
    }
    // Sortie du plein ecran (Echap, bouton, F) : on ne laisse pas l'utilisateur
    // en haut de page. Point deja pose -> on l'amene a la 1re question (focus
    // clavier sur son 1er choix, sans le cocher) ; sinon -> carte recentree a
    // l'ecran, focus dessus. Sortie par Tab : l'utilisateur deplace lui-meme
    // le focus, on ne touche a rien.
    let etaitActif = false;
    let sortieParTab = false;
    function recadrerApresSortie() {
      const comportement = window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth";
      const radio = latInput.value ? premierRadioFormulaire() : null;
      if (radio) {
        (radio.closest(".form-section") || radio).scrollIntoView({
          behavior: comportement,
          block: "center",
        });
        radio.focus({ preventScroll: true });
      } else {
        mapEl.scrollIntoView({ behavior: comportement, block: "center" });
        mapEl.focus({ preventScroll: true });
      }
    }
    function apresBascule() {
      majBouton();
      map.invalidateSize();
      majAideClavier();
      const on = actif();
      if (etaitActif && !on && !sortieParTab) {
        // Laisse le navigateur restaurer sa position de defilement d'abord.
        setTimeout(recadrerApresSortie, 150);
      }
      if (!on) sortieParTab = false;
      etaitActif = on;
    }
    function repli(on) {
      mapEl.classList.toggle(CLASSE_REPLI, on);
      document.documentElement.classList.toggle("nitrates-plein-ecran-ouvert", on);
      apresBascule();
    }
    // clavier : on arrive au clavier -> le focus passe sur toute la carte
    // (cadre visible), prete a naviguer. A la souris, il reste sur le bouton.
    function entrer(clavier) {
      const focusCarte = () => {
        if (clavier) mapEl.focus({ preventScroll: true });
      };
      if (mapEl.requestFullscreen && document.fullscreenEnabled) {
        mapEl
          .requestFullscreen()
          .then(focusCarte)
          .catch(() => {
            repli(true);
            focusCarte();
          });
      } else {
        repli(true);
        focusCarte();
      }
    }
    function sortir() {
      if (natif()) document.exitFullscreen();
      else repli(false);
    }

    const Controle = L.Control.extend({
      options: { position: "topleft" },
      onAdd: function () {
        const conteneur = L.DomUtil.create(
          "div",
          "leaflet-bar nitrates-map-plein-ecran"
        );
        bouton = L.DomUtil.create("button", "", conteneur);
        bouton.type = "button";
        majBouton();
        L.DomEvent.disableClickPropagation(conteneur);
        // detail === 0 : clic declenche au clavier (Entree / Espace).
        L.DomEvent.on(bouton, "click", (e) =>
          actif() ? sortir() : entrer(e.detail === 0)
        );
        return conteneur;
      },
    });
    new Controle().addTo(map);

    document.addEventListener("fullscreenchange", apresBascule);
    // Repli CSS : Echap n'est pas gere par le navigateur, on s'en charge.
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && actif() && !natif()) {
        e.preventDefault();
        repli(false);
      }
    });
    // Tab hors de la carte en plein ecran : on n'y reste pas coince derriere
    // un cadre qui masque la page, on sort du plein ecran.
    mapEl.addEventListener("focusout", (e) => {
      if (actif() && e.relatedTarget && !mapEl.contains(e.relatedTarget)) {
        sortieParTab = true;
        sortir();
      }
    });

    return {
      actif: actif,
      basculer: (clavier) => (actif() ? sortir() : entrer(clavier)),
    };
  })();

  // #531 : echelle metrique en bas a gauche, pour situer la maille des couches.
  L.control.scale({ position: "bottomleft", imperial: false }).addTo(map);

  // Lignes de chargement ZV / ZAR sous les cases de la legende.
  layersControl
    .getContainer()
    .querySelector(".leaflet-control-layers-list")
    .appendChild(chargementsEl);

  // #531 a11y : la legende Leaflet est une suite de cases sans nom de groupe,
  // et Entree ne coche pas une case (seul Espace le fait nativement). On nomme
  // les 2 groupes et on fait agir Entree comme Espace.
  (function rendreLegendeAccessible() {
    const container = layersControl.getContainer();
    const groupes = [
      [".leaflet-control-layers-base", "Fond de carte"],
      [".leaflet-control-layers-overlays", "Couches affichées sur la carte"],
    ];
    groupes.forEach(([sel, label]) => {
      const el = container.querySelector(sel);
      if (!el) return;
      el.setAttribute("role", "group");
      el.setAttribute("aria-label", label);
    });
    const toggle = container.querySelector(".leaflet-control-layers-toggle");
    if (toggle) {
      // Lien masque (legende depliee) mais signale « lien sans intitule ».
      toggle.setAttribute("title", "Couches de la carte");
      toggle.setAttribute("aria-label", "Couches de la carte");
    }
    container.addEventListener("keydown", (e) => {
      // Echap : retour sur la carte (pour zoomer / se deplacer / pointer). En
      // plein ecran, Echap en sort (gere plus bas), on ne l'intercepte pas.
      // C (carte) : meme chose, utilisable aussi en plein ecran natif.
      const versCarte =
        (e.key === "Escape" && !pleinEcran.actif()) ||
        ((e.key === "c" || e.key === "C") && !e.ctrlKey && !e.metaKey && !e.altKey);
      if (versCarte) {
        e.preventDefault();
        mapEl.focus();
        return;
      }
      if (e.key !== "Enter") return;
      const input = e.target;
      if (!input.classList || !input.classList.contains("leaflet-control-layers-selector")) {
        return;
      }
      e.preventDefault();
      if (input.type === "checkbox" || !input.checked) input.click();
    });
  })();

  // #531 a11y bonus : carte pilotable au clavier. Le handler natif Leaflet
  // reste coupe (keyboard: false, cf. #154) ; on rend le conteneur focusable
  // et on ne reagit qu'aux touches tapees AVEC le focus sur la carte elle-meme.
  mapEl.setAttribute("tabindex", "0");
  // Les boutons +/- font doublon avec les touches + et - de la carte : on les
  // sort de l'ordre de tabulation pour que Tab depuis la carte mene tout droit
  // a la legende (retour Max : legende introuvable au clavier sinon).
  mapEl.querySelectorAll(".leaflet-control-zoom a").forEach((a) => {
    a.setAttribute("tabindex", "-1");
    a.setAttribute("title", a.classList.contains("leaflet-control-zoom-in") ? "Zoomer" : "Dézoomer");
    a.setAttribute("aria-label", a.getAttribute("title"));
  });
  mapEl.setAttribute("role", "application");
  mapEl.setAttribute(
    "aria-label",
    "Carte. Flèches pour se déplacer, plus et moins pour zoomer, " +
      "Entrée pour choisir le point au centre de la carte, " +
      "F pour le plein écran, L pour les couches affichées."
  );
  // Un clic / glisser sur la carte (y compris sur une zone ZV/ZAR) lui donne
  // le focus : on enchaine ensuite fleches / + / - sans chercher la carte au Tab.
  mapEl.addEventListener("pointerup", (e) => {
    if (e.target.closest(".leaflet-control")) return;
    mapEl.focus({ preventScroll: true });
  });
  // #531 : panneau d'aide clavier, visible seulement quand on navigue au
  // clavier dans la carte (le focus y est et la derniere interaction etait une
  // touche). Il liste les raccourcis du contexte courant (carte, legende,
  // bouton plein ecran). Visuel seulement (aria-hidden) : le lecteur d'ecran a
  // deja les consignes dans l'aria-label de la carte.
  const aideEl = L.DomUtil.create("div", "nitrates-map-aide", mapEl);
  aideEl.setAttribute("aria-hidden", "true");
  aideEl.hidden = true;
  L.DomEvent.disableClickPropagation(aideEl);
  let modaliteClavier = false;

  function contexteFocus(el) {
    if (el.closest(".leaflet-control-layers")) return "legende";
    if (el.closest(".nitrates-map-plein-ecran")) return "bouton";
    return "carte";
  }

  function majAideClavier() {
    const actifEl = document.activeElement;
    if (!prefs || !modaliteClavier || !actifEl || !mapEl.contains(actifEl)) {
      aideEl.hidden = true;
      return;
    }
    const lignes = prefs.aideClavier(contexteFocus(actifEl), pleinEcran.actif());
    aideEl.innerHTML = "";
    lignes.forEach(([touche, action]) => {
      const item = L.DomUtil.create("span", "nitrates-map-aide__item", aideEl);
      L.DomUtil.create("kbd", "", item).textContent = touche;
      item.appendChild(document.createTextNode(" " + action));
    });
    aideEl.hidden = false;
  }

  document.addEventListener(
    "keydown",
    () => {
      modaliteClavier = true;
      // Apres l'action par defaut de la touche (deplacement du focus au Tab).
      setTimeout(majAideClavier, 0);
    },
    true
  );
  document.addEventListener(
    "pointerdown",
    () => {
      modaliteClavier = false;
      majAideClavier();
    },
    true
  );
  mapEl.addEventListener("focusin", majAideClavier);
  mapEl.addEventListener("focusout", () => setTimeout(majAideClavier, 0));

  mapEl.addEventListener("keydown", (e) => {
    if (e.target !== mapEl || !prefs) return;
    const action = prefs.actionClavier(e);
    if (!action) return;
    e.preventDefault();
    if (action.type === "pan") {
      map.panBy([action.dx, action.dy]);
    } else if (action.type === "zoom") {
      map.setZoom(map.getZoom() + action.delta);
    } else if (action.type === "pleinEcran") {
      pleinEcran.basculer(true);
    } else if (action.type === "legende") {
      const cible = layersControl
        .getContainer()
        .querySelector(".leaflet-control-layers-base input:checked");
      if (cible) cible.focus();
    } else if (action.type === "pointer") {
      // Au clavier, on reste sur la carte (pas de saut vers le formulaire) :
      // l'utilisateur peut affiner son point, puis Tab pour continuer.
      // originalEvent : c'est un vrai pointage utilisateur (compte en analytics).
      map.fire("click", { latlng: map.getCenter(), originalEvent: e });
    }
  });

  let marker = null;

  // #583 : selection de LA parcelle RPG cliquee, une seule a la fois. En gris :
  // les zones ont deja violet, jaune, bleu ciel, rose, orange, vert clair et
  // rouge, une couleur de plus clasherait. Halo blanc dessous pour rester
  // lisible sur les champs sombres de la photo aerienne.
  const STYLE_SELECTION_HALO = { color: "#ffffff", weight: 6, opacity: 0.9, fill: false };
  const STYLE_SELECTION = {
    color: "#3a3a3a",
    weight: 3,
    opacity: 1,
    fillColor: "#808080",
    fillOpacity: 0.45,
  };
  // IGN qui rame : au-dela on garde le point clique, la simulation n'attend pas.
  const DELAI_WFS_RPG_MS = 2500;

  // La selection suit la case « Parcelles agricoles (RPG) » : decochee, plus
  // de contours ni de zone grise (le point, lui, reste pose) ; un clic carte
  // pose alors le point clique, sans chercher de parcelle. Recochee, la
  // parcelle selectionnee reapparait.
  const rpgActif = () => !!rpg && map.hasLayer(rpgOverlay);

  const selectionRpg = (function () {
    let courante = null; // { feature, point: {lat, lng}, layer }

    function deselectionner() {
      if (courante) map.removeLayer(courante.layer);
      courante = null;
    }

    function contient(lat, lng) {
      return (
        rpgActif() && !!courante && rpg.pointDansGeometrie(lat, lng, courante.feature.geometry)
      );
    }

    rpgOverlay.on("add", () => {
      if (courante) courante.layer.addTo(map);
    });
    rpgOverlay.on("remove", () => {
      if (courante) map.removeLayer(courante.layer);
    });

    // Parcelle RPG sous le point -> la selectionne et resout { feature, point }
    // (point = point central, garanti dans la parcelle). Resout null hors RPG
    // (parcelle hors PAC), si l'IGN ne repond pas ou si la reponse est
    // perimee (clic plus recent entre-temps).
    let jeton = 0;
    function selectionnerAuPoint(lat, lng) {
      deselectionner();
      const mon = ++jeton;
      if (!rpg) return Promise.resolve(null);
      const ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
      const timer = ctrl ? setTimeout(() => ctrl.abort(), DELAI_WFS_RPG_MS) : null;
      return fetch(rpg.urlParcelleAuPoint(lat, lng), ctrl ? { signal: ctrl.signal } : {})
        .then((r) => {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then((data) => {
          if (mon !== jeton) return null;
          const f = (data.features || [])[0];
          const point = f ? rpg.pointCentral(f.geometry) : null;
          if (!point) return null;
          const opts = (style) => ({ pane: "nitratesSelection", interactive: false, style: style });
          const layer = L.layerGroup([
            L.geoJSON(f, opts(STYLE_SELECTION_HALO)),
            L.geoJSON(f, opts(STYLE_SELECTION)),
          ]);
          if (rpgActif()) layer.addTo(map);
          courante = { feature: f, point: point, layer: layer };
          return courante;
        })
        .catch((err) => {
          console.warn("Parcelle RPG : WFS IGN en echec", err);
          return null;
        })
        .finally(() => {
          if (timer) clearTimeout(timer);
        });
    }

    return {
      deselectionner: deselectionner,
      contient: contient,
      selectionnerAuPoint: selectionnerAuPoint,
      courante: () => courante,
    };
  })();

  const echapperHtml = (v) =>
    String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  // Panneau debug : tout ce que l'IGN donne sur la parcelle RPG (#583), pour
  // voir ce qui est a disposition.
  function rpgDebugHtml(sel) {
    if (!sel) {
      return rpgActif()
        ? "<dt>Parcelle RPG</dt><dd>aucune parcelle RPG (hors PAC ?)</dd>"
        : "<dt>Parcelle RPG</dt><dd>couche « Parcelles agricoles » décochée</dd>";
    }
    const p = sel.feature.properties || {};
    const meta = Object.keys(p)
      .map((k) => `${echapperHtml(k)}=${p[k] === null ? "∅" : echapperHtml(p[k])}`)
      .join(", ");
    return (
      `<dt>Parcelle RPG ${rpg.MILLESIME}</dt><dd>n° ${echapperHtml(p.num_parcel || "—")}, îlot ${echapperHtml(p.num_ilot || "—")}</dd>` +
      `<dt>Point central (moulinette)</dt><dd>${sel.point.lng.toFixed(6)}, ${sel.point.lat.toFixed(6)}</dd>` +
      `<dt>Métadonnées RPG</dt><dd><code>${meta}</code></dd>`
    );
  }

  function cultureLabel(parcel) {
    if (!parcel || !parcel.code_cultu) return "";
    if (parcel.libelle_cultu) {
      return `${parcel.code_cultu} (${parcel.libelle_cultu})`;
    }
    return parcel.code_cultu;
  }

  function renderDebug(data, communeInfo, parcelInfo, rpgSel) {
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
    // Zone maïs Bretagne (annexe 7 du PAR) : affichée seulement en Bretagne.
    const bretagneHtml = data.en_bretagne
      ? `<dt>Zone maïs Bretagne</dt><dd class="${data.zone_mais_bretagne ? "nitrates-debug__badge-yes" : "nitrates-debug__badge-no"}">${data.zone_mais_bretagne === "zone_1" ? "ZONE 1" : data.zone_mais_bretagne === "zone_2" ? "ZONE 2" : "AUCUNE"}</dd>`
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
        ${rpgDebugHtml(rpgSel)}
        <dt>Parcelle cadastre</dt><dd>${parcelHtml}</dd>
        <dt>Zone vulnérable nitrates</dt><dd class="${zvClass}">${zvText}</dd>
        <dt>Zone d'action renforcée (ZAR)</dt><dd class="${zarClass}">${zarText}</dd>
        ${grandEstHtml}
        ${bretagneHtml}
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
    marker = L.marker([initialLat, initialLng], { keyboard: false }).addTo(map);
    map.setView([initialLat, initialLng], 13);
    if (window.NITRATES_CATALOG) {
      Promise.all([
        fetchCommuneInfo(initialLat, initialLng),
        fetchParcelInfo(initialLat, initialLng),
        // Le point vient d'une selection precedente (point central) : il est
        // dans la parcelle, on la resurligne.
        rpgActif() ? selectionRpg.selectionnerAuPoint(initialLat, initialLng) : null,
      ]).then(([communeInfo, parcelInfo, rpgSel]) => {
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
            en_bretagne: cat.en_bretagne,
            zone_mais_bretagne: cat.zone_mais_bretagne,
          },
          communeInfo,
          parcelInfo,
          rpgSel
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

  function demarrerChargementLoc(defiler) {
    if (!locLoadingEl || !locFillEl) return;
    clearInterval(locLoadingTimer);
    locLoadingEl.hidden = false;
    // #531 : pas de defilement quand on pointe au clavier (Entree) ni en plein
    // ecran : la carte, qui garde le focus, sortirait de la vue.
    if (defiler) {
      // Le panneau est SOUS la carte : si l'utilisateur a la carte plein ecran
      // il ne le verrait pas. On l'amene dans le viewport pour que le
      // chargement soit visible (Carte #154).
      requestAnimationFrame(() => {
        locLoadingEl.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    }
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

  // Clics carte successifs : seul le dernier met a jour formulaire et panneaux.
  let numeroClic = 0;
  const PERIME = new Error("clic perime");

  map.on("click", function (e) {
    const latClic = e.latlng.lat;
    const lngClic = e.latlng.lng;

    // #583 : reclic dans la parcelle selectionnee = deselection. Le point reste
    // pose (le formulaire en depend), seul le surlignage part.
    if (e.originalEvent && selectionRpg.contient(latClic, lngClic)) {
      selectionRpg.deselectionner();
      return;
    }
    const clic = ++numeroClic;

    // Analytics (#Matomo) : ne compter que les clics carte REELS. selectCommune
    // rejoue ce handler via map.fire(...) sans originalEvent -> on l'exclut ici
    // (il est deja compte comme "RechercheCommune").
    if (e.originalEvent) {
      document.dispatchEvent(new CustomEvent("nitrates:point-carte"));
    }
    // #531 : point choisi a la souris -> le Tab suivant mene a la 1re question
    // (et non a la legende). Au clavier (Entree), on reste sur la carte.
    if (e.originalEvent && !(e.originalEvent instanceof KeyboardEvent)) {
      document.addEventListener("nitrates:form-revealed", poserDepartTabFormulaire, {
        once: true,
      });
    }

    // Pre-remplit le form -- c'est l'objectif principal de cette page.
    // Point clique d'abord, remplace par le point central de la parcelle RPG
    // des qu'on la connait (plus bas).
    lngInput.value = lngClic.toFixed(6);
    latInput.value = latClic.toFixed(6);

    demarrerChargementLoc(
      !(e.originalEvent instanceof KeyboardEvent) && !pleinEcran.actif()
    );

    // Carte #57 : on NE devoile PAS le formulaire immediatement. On attend
    // la reponse localisation (DebugView) qui indique si le simulateur est
    // ouvert pour ce departement. Si ouvert -> on revele le form ; sinon ->
    // message "pas encore ouvert". cf. .then() ci-dessous.

    if (marker) {
      marker.setLatLng(e.latlng);
    } else {
      // keyboard: false (#531) : marqueur decoratif, hors ordre de tabulation.
      marker = L.marker(e.latlng, { keyboard: false }).addTo(map);
    }

    if (debugEl) {
      debugEl.innerHTML =
        '<p class="nitrates-debug__placeholder">Chargement…</p>';
    }

    // #583 : la moulinette travaille sur UN point -> le point central de la
    // parcelle RPG cliquee (garanti dedans). Hors RPG ou IGN indisponible : le
    // point clique, comme avant (idem case RPG decochee). La recherche commune
    // (map.fire sans originalEvent) pointe le centre-ville : pas de parcelle.
    const resolutionRpg =
      e.originalEvent && rpgActif()
        ? selectionRpg.selectionnerAuPoint(latClic, lngClic)
        : (selectionRpg.deselectionner(), Promise.resolve(null));
    let lat = latClic;
    let lng = lngClic;
    let rpgSel = null;

    // On resout d'abord la commune (code INSEE) puis on interroge l'endpoint
    // debug AVEC ce code : les Zones Est (ZGE1/ZGE2) se resolvent par INSEE
    // cote serveur, sinon elles ressortent toujours None dans le panneau.
    resolutionRpg
      .then((sel) => {
        // Clic plus recent entre-temps : c'est lui qui finit le travail.
        if (clic !== numeroClic) throw PERIME;
        if (sel) {
          rpgSel = sel;
          lat = sel.point.lat;
          lng = sel.point.lng;
          latInput.value = lat.toFixed(6);
          lngInput.value = lng.toFixed(6);
          marker.setLatLng([lat, lng]);
        }
        return Promise.all([fetchCommuneInfo(lat, lng), fetchParcelInfo(lat, lng)]);
      })
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
        if (clic !== numeroClic) throw PERIME;
        renderDebug(data, communeInfo, parcelInfo, rpgSel);
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
          afficherMessageFerme(
            data.region_label,
            data.department_code,
            data.region_code
          );
        }
        // Pousse le code INSEE dans le hidden : il sera soumis avec
        // le form et utilise cote backend pour resoudre la zone
        // montagne (D113-14) sans charger les polygones communes.
        const codeInseeInput = document.getElementById("id_code_insee");
        // #271 : on capture l'ANCIEN code INSEE (celui de la simulation en cours)
        // AVANT de l'écraser, pour comparer les scopes.
        const ancienInsee = codeInseeInput ? codeInseeInput.value || "" : "";
        if (codeInseeInput) codeInseeInput.value = communeInfo.code || "";
        // #271 : gestion du re-clic carte quand un RÉSULTAT est déjà affiché.
        // Si le nouveau point change le SCOPE d'interprétation (zones : ZV, ZAR,
        // région, Grand Est 1/2, commune -> montagne/note5), le résultat n'est
        // plus valide -> on l'invalide et on force un re-clic « Lancer ». Si le
        // scope est identique, on garde l'affichage (rien à réévaluer).
        gererReclicCarteResultat(data, communeInfo.code || "", ancienInsee);
        terminerChargementLoc();
      })
      .catch((err) => {
        if (err === PERIME) return;
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
      // Analytics (#Matomo) : l'utilisateur a utilise la recherche de commune.
      document.dispatchEvent(new CustomEvent("nitrates:recherche-commune"));
      // Carte #154 : Tab/Entree enchainent sur le formulaire sans re-cliquer.
      focusFormulaireApresRevelation();
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

  // Analytics (#Matomo) : "Lancer la simulation" = submit du formulaire (le
  // parcours est un GET full-reload). On emet l'event AVANT la navigation ;
  // sendBeacon (cf. nitrates_analytics.js) garantit qu'il parte. On enrichit
  // avec le departement (2 premiers chiffres du code INSEE) quand il est connu.
  (function trackSimulationSubmit() {
    const form = document.getElementById("form-simulateur");
    if (!form) return;
    form.addEventListener("submit", function () {
      const insee =
        (document.getElementById("id_code_insee") || {}).value || "";
      const department = insee ? insee.slice(0, 2) : undefined;
      document.dispatchEvent(
        new CustomEvent("nitrates:simulation-lancee", {
          detail: { department: department },
        })
      );
    });
  })();

  // #271 : au chargement d'une PAGE RÉSULTAT, on établit le scope de RÉFÉRENCE
  // en interrogeant DebugView pour le point du résultat (lat/lng des hidden).
  // Ainsi la 1re comparaison au re-clic se fait DebugView vs DebugView (valeurs
  // cohérentes), sans dépendre du catalog moulinette qui peut diverger.
  (function initScopeReference() {
    const form = document.getElementById("form-simulateur");
    if (!form || !form.hasAttribute("data-resultat-affiche")) return;
    const lat = (latInput.value || "").trim();
    const lng = (lngInput.value || "").trim();
    if (!lat || !lng) return;
    const insee = (document.getElementById("id_code_insee") || {}).value || "";
    const url =
      `${window.NITRATES_DEBUG_URL}?lng=${lng}&lat=${lat}` +
      (insee ? `&code_insee=${encodeURIComponent(insee)}` : "") +
      (window.NITRATES_GEO_APPLIQUEE ? "&geo=1" : "");
    fetch(url, { headers: { Accept: "application/json" } })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) scopeReference = scopeDepuisData(data, insee);
      })
      .catch(() => {});
  })();
})();
