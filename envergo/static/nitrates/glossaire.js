// Glossaire cliquable + carte flottante de définition (carte #110).
//
// Trois responsabilités :
//   1. LINKIFICATION CLIENT : wrapper les termes définis dans les textes
//      générés côté navigateur (radios cascade.js, parcours
//      question_couvert_flow.js, swaps de question_reformat.js) — le filtre
//      serveur |glossaire ne les voit jamais. Même balise <a.def-terme> que
//      le serveur : un seul style, un seul handler.
//   2. RÉ-APPLICATION : MutationObserver sur le <main>, debouncé par
//      requestAnimationFrame, avec un verrou anti-boucle (nos propres
//      wrappings déclenchent des mutations qu'on doit ignorer).
//   3. CARTE FLOTTANTE : délégation de clic sur [data-def-cle] ->
//      preventDefault + slide-in de #def-carte remplie depuis le JSON
//      embarqué par {% glossaire_json %} (HTML précompilé serveur, on
//      n'assemble JAMAIS de HTML depuis des chaînes en JS).
//
// Ordre de chargement : EN DERNIER dans extra_js (les <script defer>
// s'exécutent dans l'ordre du document), après question_reformat.js.
(function () {
  "use strict";

  // En Node (tests unitaires), on n'expose que les helpers PURS (matching /
  // découpage en segments, pas de DOM) puis on sort. cf. question_reformat.js.
  const _isNode =
    typeof module !== "undefined" &&
    module.exports &&
    typeof document === "undefined";

  // ── Helpers purs (testés en Node, parité avec le filtre Python) ─────────

  // Échappe les métacaractères regex d'une variante (équivalent re.escape).
  function echapperRegex(s) {
    return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  // Regex d'alternation des variantes. `termes` = [[variante, cle], ...]
  // DÉJÀ trié longest-first par le serveur (glossaire.py) : la 1re branche
  // qui matche gagne -> longest-match. Frontières en lookarounds unicode
  // (\p{L}\p{N}_) : « azote efficacement » ne matche pas « azote efficace »,
  // frontière accentuée comprise (parité avec le (?<!\w) Python).
  function construireRegex(termes) {
    if (!termes || !termes.length) return null;
    const alternation = termes
      .map(function (t) {
        return echapperRegex(t[0]);
      })
      .join("|");
    try {
      return new RegExp(
        "(?<![\\p{L}\\p{N}_])(?:" + alternation + ")(?![\\p{L}\\p{N}_])",
        "giu"
      );
    } catch (e) {
      // Vieux Safari sans lookbehind : on dégrade proprement (pas de
      // linkification client ; les liens posés côté serveur restent actifs).
      return null;
    }
  }

  // Découpe un texte brut en segments [{texte} | {texte, cle}] selon les
  // matches. Pur : pas de DOM, testable en Node.
  function decouperTexte(texte, regex, parVariante) {
    const segments = [];
    if (!texte) return segments;
    if (!regex) return [{ texte: texte }];
    let dernier = 0;
    regex.lastIndex = 0;
    let m;
    while ((m = regex.exec(texte)) !== null) {
      const cle = parVariante[m[0].toLowerCase()];
      if (cle === undefined) continue;
      if (m.index > dernier) segments.push({ texte: texte.slice(dernier, m.index) });
      segments.push({ texte: m[0], cle: cle });
      dernier = m.index + m[0].length;
    }
    if (dernier < (texte || "").length) segments.push({ texte: texte.slice(dernier) });
    return segments;
  }

  if (_isNode) {
    module.exports = {
      echapperRegex: echapperRegex,
      construireRegex: construireRegex,
      decouperTexte: decouperTexte,
    };
    return;
  }

  // ── Chargement du glossaire embarqué ────────────────────────────────────

  const dataEl = document.getElementById("glossaire-data");
  if (!dataEl) return; // pas de glossaire sur cette page
  let GLOSSAIRE;
  try {
    GLOSSAIRE = JSON.parse(dataEl.textContent);
  } catch (e) {
    return;
  }
  if (!GLOSSAIRE || !GLOSSAIRE.termes || !GLOSSAIRE.termes.length) return;

  // ── Assainissement des données embarquées ───────────────────────────────
  // Le JSON vient de {% glossaire_json %} (rendu serveur, HTML produit par
  // compile_dsfr qui échappe tout texte saisi) : il est de confiance. On le
  // durcit quand même côté client — défense en profondeur, et l'analyse
  // statique (CodeQL js/xss-through-dom) ne peut pas connaître cette
  // garantie distante puisqu'elle voit une valeur lue dans le DOM.

  // URL de la page définitions : on n'accepte qu'un chemin absolu simple
  // (pas de javascript:, pas de //hote-externe). Sinon repli sur le défaut.
  const URL_DEFINITIONS = /^\/[\w\-/]*$/.test(GLOSSAIRE.url_definitions || "")
    ? GLOSSAIRE.url_definitions
    : "/definitions/";

  // Ancre d'une définition : seulement [a-z0-9-], jamais rien d'autre.
  function ancreSure(valeur) {
    return String(valeur || "").replace(/[^\w-]/g, "");
  }

  // Lien vers une définition, construit à partir de valeurs validées.
  function urlDefinition(ancre) {
    const a = ancreSure(ancre);
    return a ? URL_DEFINITIONS + "#" + a : URL_DEFINITIONS;
  }

  // ── Rendu des blocs de définition ───────────────────────────────────────
  // Le serveur envoie les BLOCS JSON typés (cf. glossaire_json), pas du HTML :
  // on construit le DOM avec createElement/textContent. Aucune chaîne HTML
  // n'est interprétée côté client, donc aucune injection possible quelle que
  // soit la donnée. Équivalent JS de compile_dsfr (contenu_rich/compilateur.py)
  // pour les types de blocs affichables dans la carte ; un type inconnu est
  // ignoré silencieusement, comme côté serveur.

  // Texte riche : chaîne simple, ou liste de segments {texte, gras}.
  function poserTexte(cible, valeur) {
    if (valeur === null || valeur === undefined) return;
    if (typeof valeur === "string") {
      cible.appendChild(document.createTextNode(valeur));
      return;
    }
    if (!Array.isArray(valeur)) {
      cible.appendChild(document.createTextNode(String(valeur)));
      return;
    }
    valeur.forEach(function (seg) {
      if (typeof seg === "string") {
        cible.appendChild(document.createTextNode(seg));
        return;
      }
      if (!seg || typeof seg !== "object") return;
      const txt = document.createTextNode(seg.texte || "");
      if (seg.gras) {
        const strong = document.createElement("strong");
        strong.appendChild(txt);
        cible.appendChild(strong);
      } else {
        cible.appendChild(txt);
      }
    });
  }

  function creerAvecTexte(balise, classe, valeur) {
    const el = document.createElement(balise);
    if (classe) el.className = classe;
    poserTexte(el, valeur);
    return el;
  }

  function rendreItemsListe(items, ul) {
    (items || []).forEach(function (item) {
      const li = document.createElement("li");
      poserTexte(li, (item || {}).texte || "");
      const enfants = (item || {}).enfants;
      if (enfants && enfants.length) {
        const sousListe = document.createElement("ul");
        rendreItemsListe(enfants, sousListe);
        li.appendChild(sousListe);
      }
      ul.appendChild(li);
    });
  }

  function rendreTableau(data, ctx) {
    const lignes = (data.lignes || []).filter(Array.isArray);
    if (!lignes.length) return null;
    const wrapper = document.createElement("div");
    wrapper.className = "fr-table fr-table--bordered";
    const inner = document.createElement("div");
    inner.className = "fr-table__wrapper";
    const conteneur = document.createElement("div");
    conteneur.className = "fr-table__container";
    const contenu = document.createElement("div");
    contenu.className = "fr-table__content";
    const table = document.createElement("table");

    let corpsLignes = lignes;
    if (data.avec_entetes !== false) {
      const thead = document.createElement("thead");
      const tr = document.createElement("tr");
      lignes[0].forEach(function (cellule) {
        const th = document.createElement("th");
        th.setAttribute("scope", "col");
        poserTexte(th, cellule);
        tr.appendChild(th);
      });
      thead.appendChild(tr);
      table.appendChild(thead);
      corpsLignes = lignes.slice(1);
    }
    const tbody = document.createElement("tbody");
    corpsLignes.forEach(function (ligne) {
      const tr = document.createElement("tr");
      ligne.forEach(function (cellule) {
        const td = document.createElement("td");
        poserTexte(td, cellule);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    contenu.appendChild(table);
    conteneur.appendChild(contenu);
    inner.appendChild(conteneur);
    wrapper.appendChild(inner);
    return wrapper;
  }

  function rendreFoldable(data, ctx) {
    // Accordéon DSFR. id unique par carte : le préfixe vient de l'ancre de
    // la définition, comme l'id_prefix côté serveur (collisions, carte #157).
    ctx.seq += 1;
    const id = ctx.prefixe + "-accordion-" + ctx.seq;
    const section = document.createElement("section");
    section.className = "fr-accordion";
    const titre = document.createElement("h5");
    titre.className = "fr-accordion__title";
    const bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "fr-accordion__btn";
    bouton.setAttribute("aria-expanded", "false");
    bouton.setAttribute("aria-controls", id);
    poserTexte(bouton, data.titre || "");
    titre.appendChild(bouton);
    const collapse = document.createElement("div");
    collapse.className = "fr-collapse";
    collapse.id = id;
    rendreBlocs(data.blocs || [], collapse, ctx);
    section.appendChild(titre);
    section.appendChild(collapse);
    return section;
  }

  function rendreBloc(bloc, ctx) {
    const data = bloc.data || {};
    switch (bloc.type) {
      case "titre_principal":
        return creerAvecTexte("h5", "fr-h5", data.texte);
      case "titre_paragraphe":
        return creerAvecTexte("h6", "fr-h6", data.texte);
      case "paragraphe":
        return creerAvecTexte("p", "", data.texte);
      case "citation": {
        const callout = document.createElement("div");
        callout.className = "fr-callout";
        callout.appendChild(creerAvecTexte("p", "fr-callout__text", data.texte));
        return callout;
      }
      case "liste": {
        const ul = document.createElement("ul");
        ul.className = "fr-mb-0";
        rendreItemsListe(data.items || [], ul);
        return ul;
      }
      case "foldable":
        return rendreFoldable(data, ctx);
      case "tableau":
        return rendreTableau(data, ctx);
      default:
        return null; // type inconnu ignoré, comme côté serveur
    }
  }

  function rendreBlocs(blocs, cible, ctx) {
    (blocs || []).forEach(function (bloc) {
      if (!bloc || typeof bloc !== "object") return;
      const el = rendreBloc(bloc, ctx);
      if (!el) return;
      // Indentation « façon Notion » (data.indent), bornée comme au serveur.
      const indent = Math.max(
        0,
        Math.min(6, parseInt((bloc.data || {}).indent, 10) || 0)
      );
      if (indent > 0) {
        const wrap = document.createElement("div");
        wrap.style.marginLeft = indent * 1.5 + "rem";
        wrap.appendChild(el);
        cible.appendChild(wrap);
      } else {
        cible.appendChild(el);
      }
    });
  }

  // Construit le contenu d'une définition. Renvoie un élément prêt à insérer.
  function rendreDefinition(def) {
    const racine = document.createElement("div");
    racine.className = "contenu-rich";
    rendreBlocs(def.blocs || [], racine, {
      prefixe: "def-panel-" + ancreSure(def.ancre),
      seq: 0,
    });
    return racine;
  }

  const REGEX = construireRegex(GLOSSAIRE.termes);
  const PAR_VARIANTE = {};
  GLOSSAIRE.termes.forEach(function (t) {
    PAR_VARIANTE[t[0].toLowerCase()] = t[1];
  });

  // ── Linkification DOM ───────────────────────────────────────────────────

  // Où linkifier : les textes de question et les labels de radios (toutes
  // sources : statiques, cascade, couvert-flow, QC), ainsi que les contenus
  // riches du panneau résultat. Volontairement PAS tout le <main> : on ne
  // touche ni aux boutons, ni au calendrier, ni aux champs.
  const SELECTEURS = [
    ".form-question-text",
    ".fr-label",
    ".fr-hint-text",
    ".contenu-rich",
    // Drawer « Conditions d'épandage » : les textes PC hors contenu riche
    // (texte_court legacy, notes) contiennent aussi des termes (batch 2).
    ".drawer-conditions__panel",
  ].join(", ");

  // Balises dont on ne traverse JAMAIS le contenu.
  const BALISES_EXCLUES = { A: 1, BUTTON: 1, SCRIPT: 1, STYLE: 1, INPUT: 1, SELECT: 1, TEXTAREA: 1 };

  let verrou = false; // anti-boucle : nos wrappings déclenchent des mutations

  function creerLien(cle) {
    const def = GLOSSAIRE.defs[cle] || {};
    const a = document.createElement("a");
    a.dataset.defCle = cle;
    a.setAttribute("href", urlDefinition(def.ancre));
    return a;
  }

  function linkifierNoeudTexte(node) {
    const segments = decouperTexte(node.nodeValue, REGEX, PAR_VARIANTE);
    if (!segments.some(function (s) { return s.cle !== undefined; })) return;
    // Dans un <label> radio/checkbox, on ne wrappe PAS le texte du terme :
    // un label comme « Sol non cultivé (…) » deviendrait presque entièrement
    // un lien et cliquer dessus ne cocherait plus le radio (constaté sur la
    // Q1 #335). Le texte garde le souligné pointillé (span) et SEULE l'icône
    // ⓘ accolée ouvre la définition.
    const dansLabel = !!(node.parentNode && node.parentNode.closest("label"));
    // Un SEUL conteneur pour tous les segments : le nœud texte d'origine était
    // un unique enfant ; certains labels sont des conteneurs flex (couvert
    // flow) où chaque enfant devient un item -> sans wrapper, l'icône et les
    // bouts de texte partent chacun à la ligne.
    const frag = document.createElement("span");
    frag.className = "def-terme-groupe";
    segments.forEach(function (s) {
      if (s.cle === undefined) {
        frag.appendChild(document.createTextNode(s.texte));
        return;
      }
      if (dansLabel) {
        const span = document.createElement("span");
        span.className = "def-terme-libelle";
        span.textContent = s.texte;
        frag.appendChild(span);
        const icone = creerLien(s.cle);
        icone.className = "def-terme def-terme--icone";
        icone.setAttribute("aria-label", "Définition : " + s.texte);
        frag.appendChild(icone);
      } else {
        const a = creerLien(s.cle);
        a.className = "def-terme";
        a.textContent = s.texte;
        frag.appendChild(a);
      }
    });
    node.parentNode.replaceChild(frag, node);
  }

  function linkifierConteneur(racine) {
    const zones = racine.matches && racine.matches(SELECTEURS)
      ? [racine]
      : Array.prototype.slice.call(racine.querySelectorAll ? racine.querySelectorAll(SELECTEURS) : []);
    if (!zones.length) return;
    verrou = true;
    try {
      zones.forEach(function (zone) {
        const walker = document.createTreeWalker(zone, NodeFilter.SHOW_TEXT, {
          acceptNode: function (n) {
            // Refuse les textes déjà dans un lien/bouton/terme wrappé.
            let p = n.parentNode;
            while (p && p !== zone) {
              if (
                BALISES_EXCLUES[p.tagName] ||
                (p.classList &&
                  (p.classList.contains("def-terme") ||
                    p.classList.contains("def-terme-libelle") ||
                    p.classList.contains("def-terme-groupe")))
              ) {
                return NodeFilter.FILTER_REJECT;
              }
              p = p.parentNode;
            }
            return NodeFilter.FILTER_ACCEPT;
          },
        });
        // Matérialise la liste AVANT de modifier le DOM (le walker se perd si
        // on remplace les nœuds pendant l'itération).
        const textes = [];
        while (walker.nextNode()) textes.push(walker.currentNode);
        textes.forEach(linkifierNoeudTexte);
      });
    } finally {
      verrou = false;
    }
  }

  // ── Carte flottante ─────────────────────────────────────────────────────

  let carteOuverte = null; // { declencheur }

  // Hauteur visible du bandeau construction (cf. drawer_conditions.js).
  function hauteurBandeau() {
    const bandeau = document.querySelector(".nitrates-construction__bar");
    if (!bandeau) return 0;
    const r = bandeau.getBoundingClientRect();
    const style = window.getComputedStyle(bandeau);
    if (r.height > 0 && parseFloat(style.opacity) > 0.1) return r.height;
    return 0;
  }

  function carte() {
    return document.getElementById("def-carte");
  }

  function ouvrirCarte(cle, declencheur) {
    const el = carte();
    const def = GLOSSAIRE.defs[cle];
    if (!el || !def) return;
    // Ré-ouverture sur un autre terme : détacher le suivi scroll précédent.
    if (el._detacherSuivi) {
      el._detacherSuivi();
      el._detacherSuivi = null;
    }
    // Reparentage sous <body> : la carte est fixed et serait clippée par
    // .results-row { overflow: clip } (cf. drawer_conditions.js).
    if (el.parentNode !== document.body) document.body.appendChild(el);
    el.querySelector("#def-carte-titre").textContent = def.titre;
    // Corps : construit depuis les blocs JSON typés (createElement /
    // textContent). Aucune chaîne HTML n'est interprétée côté client.
    const corps = el.querySelector(".def-carte__corps");
    corps.replaceChildren(rendreDefinition(def));
    const lien = el.querySelector("#def-carte-toutes");
    lien.setAttribute("href", urlDefinition(def.ancre));
    // Depuis le drawer conditions (ancré à droite) : la carte arrive par la
    // GAUCHE, sinon elle serait posée sur le drawer (batch 2).
    const dansDrawer = !!(
      declencheur &&
      declencheur.closest &&
      declencheur.closest(".drawer-conditions__panel")
    );
    el.classList.toggle("def-carte--gauche", dansDrawer);
    // Une définition avec tableau (types de fertilisants) est illisible en
    // 380px : on élargit la carte, bornée à l'espace disponible (viewport,
    // ou zone restante à gauche du drawer).
    let largeur = "";
    if (el.querySelector(".def-carte__corps table")) {
      let dispo = window.innerWidth - 32;
      if (dansDrawer) {
        const panneau = document.querySelector(".drawer-conditions__panel");
        if (panneau) {
          dispo = Math.max(340, panneau.getBoundingClientRect().left - 32);
        }
      }
      largeur = Math.min(560, dispo) + "px";
    }
    el.style.width = largeur;
    // Position verticale : au niveau du terme cliqué (Loom Coralie), bornée
    // au viewport. Il faut la hauteur réelle -> dévoiler d'abord (opacité 0
    // tant que --ouverte n'est pas posée, pas de flash).
    el.hidden = false;
    function positionner() {
      const minTop = 16 + hauteurBandeau();
      let top = minTop;
      if (declencheur && declencheur.getBoundingClientRect) {
        top = declencheur.getBoundingClientRect().top - 8;
      }
      const maxTop = Math.max(
        minTop,
        window.innerHeight - el.offsetHeight - 16
      );
      el.style.top = Math.min(Math.max(top, minTop), maxTop) + "px";
    }
    positionner();
    // La carte reste calée au niveau du terme tant qu'elle est ouverte : la
    // page peut encore bouger APRÈS l'ouverture (autoscrolls du parcours,
    // scroll utilisateur) et une position figée se retrouvait décorrélée du
    // terme cliqué. Suivi passif throttlé rAF, détaché à la fermeture.
    let rafSuivi = false;
    function suivre() {
      if (rafSuivi) return;
      rafSuivi = true;
      requestAnimationFrame(function () {
        rafSuivi = false;
        // Terme retiré du DOM (re-rendu cascade) : on garde la position.
        if (declencheur && document.contains(declencheur)) positionner();
      });
    }
    window.addEventListener("scroll", suivre, { passive: true });
    el._detacherSuivi = function () {
      window.removeEventListener("scroll", suivre);
    };
    void el.offsetWidth; // reflow avant la classe pour jouer la transition
    el.classList.add("def-carte--ouverte");
    carteOuverte = { declencheur: declencheur };
    const fermerBtn = el.querySelector("[data-def-fermer]");
    if (fermerBtn && fermerBtn.focus) fermerBtn.focus();
  }

  function fermerCarte() {
    const el = carte();
    if (!el || !carteOuverte) return;
    const declencheur = carteOuverte.declencheur;
    carteOuverte = null;
    if (el._detacherSuivi) {
      el._detacherSuivi();
      el._detacherSuivi = null;
    }
    el.classList.remove("def-carte--ouverte");
    el.hidden = true;
    // Restitue le focus au terme cliqué (accessibilité), s'il est toujours là.
    if (declencheur && document.contains(declencheur) && declencheur.focus) {
      declencheur.focus();
    }
  }

  // ── Branchement ─────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", function () {
    const main = document.querySelector("main") || document.body;

    linkifierConteneur(main);

    // Ré-application après chaque re-rendu client (cascade.js recrée les
    // radios, question_couvert_flow.js avance le parcours,
    // question_reformat.js écrase les innerHTML). Debounce rAF : les rendus
    // arrivent en rafales. Le verrou ignore nos propres mutations.
    let rafPrevu = false;
    const observer = new MutationObserver(function () {
      if (verrou || rafPrevu) return;
      rafPrevu = true;
      requestAnimationFrame(function () {
        rafPrevu = false;
        linkifierConteneur(main);
      });
    });
    observer.observe(main, { childList: true, subtree: true });

    // Clic sur un terme -> carte (un seul handler, délégation : couvre les
    // liens serveur ET client, y compris créés après coup).
    document.addEventListener("click", function (e) {
      const terme = e.target.closest && e.target.closest("[data-def-cle]");
      if (terme) {
        e.preventDefault();
        ouvrirCarte(terme.dataset.defCle, terme);
        return;
      }
      if (e.target.closest && e.target.closest("[data-def-fermer]")) {
        fermerCarte();
      }
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") fermerCarte();
    });
  });
})();
