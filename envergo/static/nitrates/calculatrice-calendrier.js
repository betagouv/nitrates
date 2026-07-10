/**
 * Composant calendrier dynamique pour les feuilles type=calculatrice
 * avec composant=calendrier_dynamique_couvert.
 *
 * Cf. spec_rendu_simulateur_calculatrice.md.
 *
 * Pas de htmx ni de round-trip serveur : le composant lit le JSON
 * exposé via <script type="application/json" id="nitrates-calculatrice-data">,
 * rend le mini-formulaire avec les placeholder, et recalcule tout
 * localement à chaque change d'input.
 */
(function () {
  "use strict";

  // Hors navigateur (Node, pour les tests de logique pure : cf.
  // feedback_static_js_cache_dev — on valide la logique calendrier en Node
  // car le JS statique servi en dev peut etre perime). Dans ce mode il n'y a
  // pas de `document` : on n'execute pas le rendu, on expose seulement les
  // helpers purs testables via module.exports, puis on sort. En navigateur
  // cette branche est morte (document existe, module non).
  const _isNode =
    typeof module !== "undefined" &&
    module.exports &&
    typeof document === "undefined";

  const dataEl = _isNode
    ? null
    : document.getElementById("nitrates-calculatrice-data");
  const root = _isNode ? null : document.querySelector("[data-calc-cal-root]");
  if (!_isNode && (!dataEl || !root)) return;

  // En Node : `data` reste vide (injectable par les tests via l'API exportee).
  let data = _isNode ? {} : null;
  if (!_isNode) {
    try {
      data = JSON.parse(dataEl.textContent);
    } catch (e) {
      console.error("calculatrice-calendrier: JSON parse failed", e);
      return;
    }
    if (!data || data.type !== "calculatrice") return;
  }

  const mount = _isNode ? null : root.querySelector("[data-calc-cal-mount]");
  if (!_isNode && !mount) return;

  // ─── Constantes ────────────────────────────────────────────────────────
  // Année agricole = juillet → juin. Index 0 = juillet, 11 = juin.
  const MOIS_AGRICOLES = [
    "Juil", "Aoû", "Sept", "Oct", "Nov", "Déc",
    "Jan", "Fév", "Mar", "Avr", "Mai", "Jui",
  ];
  // Initiales, meme ordre agricole. Affichees a la place des labels 3 lettres
  // sur mobile (#177) via .calendrier-epandage__months[data-court] en CSS :
  // sur petit ecran les labels 3 lettres se chevauchaient.
  const MOIS_AGRICOLES_COURTS = [
    "J", "A", "S", "O", "N", "D",
    "J", "F", "M", "A", "M", "J",
  ];
  // Mois en toutes lettres, ordre agricole (juillet -> juin). Pour les dates
  // des periodes affichees sous le calendrier (#159 : "15 novembre", pas
  // "15 nov."). MOIS_AGRICOLES reste pour les 12 labels de colonnes de la barre.
  const MOIS_AGRICOLES_COMPLETS = [
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    "janvier", "février", "mars", "avril", "mai", "juin",
  ];
  const JOURS_PAR_MOIS_AGRICOLE = [31, 31, 30, 31, 30, 31, 31, 28, 31, 30, 31, 30];
  const TOTAL_JOURS = 365;

  // Mapping regime YAML -> couleur attendue par calendrier.css. On reuse
  // exactement la palette du templatetag standard `calendrier_epandage` :
  //   interdiction -> rouge
  //   autorisation_sous_condition / plafonnement -> orange
  //   libre / par defaut -> pas d'overlay (fond vert visible)
  //   non_applicable -> pas d'overlay (fond gris quand activable plus tard)
  const REGIME_COULEUR_ZONE = {
    interdiction: "rouge",
    autorisation_sous_condition: "orange",
    plafonnement: "orange",
  };

  // Verbes humains pour le récap et les annotations.
  const REGIME_VERBE = {
    interdiction: "interdit",
    autorisation_sous_condition: "autorisé sous condition",
    plafonnement: "soumis à plafonnement",
    libre: "autorisé",
    non_applicable: "ne s'applique pas",
  };

  // Titre de section du récap (#159, maquette : regroupement par régime, une
  // liste à puces par section). Ordre = du moins au plus restrictif, pour
  // s'aligner sur le récap des cultures principales (autorisation d'abord,
  // interdiction en dernier).
  const SECTIONS_RECAP = [
    { regime: "libre", titre: "Période d’autorisation" },
    {
      regime: "autorisation_sous_condition",
      titre: "Période d’autorisation sous condition",
    },
    { regime: "plafonnement", titre: "Période de plafonnement" },
    { regime: "interdiction", titre: "Période d’interdiction" },
  ];

  // Vocabulaire metier des references de couvert pour la justification (#159).
  // Le point de reference est exprime en clair, sans la date fixe redondante.
  // Defini AVANT l'export Node (sinon TDZ en test unitaire, cf. conditionToText).
  const REF_COUVERT = {
    date_semis_couvert: "l’implantation du couvert",
    date_destruction_couvert: "la destruction ou la récolte du couvert",
  };

  const UNITES_JOURS = { jours: 1, semaines: 7, mois: 30 };

  // ─── Helpers ───────────────────────────────────────────────────────────

  // Convertit "JJ/MM" en index de jour de l'année agricole (0 = 1er juillet).
  function jjmmToJourAgricole(jjmm) {
    const m = /^(\d{2})\/(\d{2})$/.exec(jjmm);
    if (!m) return null;
    const jour = parseInt(m[1], 10);
    const mois = parseInt(m[2], 10);
    if (mois < 1 || mois > 12 || jour < 1 || jour > 31) return null;
    // Mois 7=juillet → index 0, mois 8 → 1, ..., 12 → 5, 1 → 6, ..., 6 → 11.
    const moisAgr = (mois - 7 + 12) % 12;
    let total = 0;
    for (let i = 0; i < moisAgr; i++) total += JOURS_PAR_MOIS_AGRICOLE[i];
    return total + (jour - 1);
  }

  // ─── Bornage des inputs (#126) ─────────────────────────────────────────
  // Un input date peut porter `min` et/ou `max` (JJ/MM) : la saisie doit
  // rester dans [min, max] en ordre annee agricole (juil->juin). Sert a
  // empecher des dates incoherentes avec la variante deja choisie en cascade
  // (ex couvert recolte avant 31/12 -> destruction max=31/12).

  // True si `jjmm` (string) respecte les bornes de l'input. Tolerant : si
  // bornes absentes ou jjmm non parseable, considere dans les bornes.
  function dansBornes(inp, jjmm) {
    const j = jjmmToJourAgricole(jjmm);
    if (j === null) return true;
    if (inp.min) {
      const jmin = jjmmToJourAgricole(inp.min);
      if (jmin !== null && j < jmin) return false;
    }
    if (inp.max) {
      const jmax = jjmmToJourAgricole(inp.max);
      if (jmax !== null && j > jmax) return false;
    }
    return true;
  }

  // Phrase explicative quand une saisie sort des bornes, contextualisee sur
  // le sens metier (avant/apres). Retourne "" si dans les bornes.
  function messageHorsBornes(inp, jjmm) {
    if (dansBornes(inp, jjmm)) return "";
    const lc = deduireLabelCourt(inp);
    const d = (v) => jjmmLisible(v);
    if (inp.max && !inp.min) {
      return `La date de ${lc} doit être au plus tard le ${d(inp.max)} pour ce type de couvert.`;
    }
    if (inp.min && !inp.max) {
      return `La date de ${lc} doit être au plus tôt le ${d(inp.min)} pour ce type de couvert.`;
    }
    return `La date de ${lc} doit être comprise entre le ${d(inp.min)} et le ${d(inp.max)} pour ce type de couvert.`;
  }

  // Note explicative permanente affichee dans le date-picker quand l'input
  // est borne. Explique POURQUOI certaines dates sont grisees, en reliant a
  // la variante de couvert choisie en amont (#126). Retourne "" si pas de
  // borne.
  function messageBornePicker(inp) {
    if (!inp || (!inp.min && !inp.max)) return "";
    const lc = deduireLabelCourt(inp);
    const intro = `D'après le type de couvert sélectionné, la ${lc}`;
    // jjmmLisible retourne "31 décembre" (mois en toutes lettres, #159).
    const d = (jjmm) => jjmmLisible(jjmm);
    if (inp.max && !inp.min) {
      return `${intro} intervient nécessairement avant le ${d(inp.max)}.`;
    }
    if (inp.min && !inp.max) {
      return `${intro} intervient nécessairement à partir du ${d(inp.min)}.`;
    }
    return `${intro} doit être comprise entre le ${d(inp.min)} et le ${d(inp.max)}.`;
  }

  // "31/12" -> "31 déc." (via l'index agricole).
  function jjmmLisible(jjmm) {
    const j = jjmmToJourAgricole(jjmm);
    return j !== null ? jourAgricoleToLisible(j) : jjmm;
  }

  // Convertit un index de jour agricole en "JJ mois" lisible, mois en toutes
  // lettres (#159 : "15 novembre").
  function jourAgricoleToLisible(j) {
    if (j < 0 || j >= TOTAL_JOURS) return "";
    let idx = j;
    for (let i = 0; i < 12; i++) {
      if (idx < JOURS_PAR_MOIS_AGRICOLE[i]) {
        return `${idx + 1} ${MOIS_AGRICOLES_COMPLETS[i]}`;
      }
      idx -= JOURS_PAR_MOIS_AGRICOLE[i];
    }
    return "";
  }

  // Convertit un index de jour agricole en "JJ/MM" (mois civil).
  function jourAgricoleToJJMM(j) {
    if (j < 0 || j >= TOTAL_JOURS) return null;
    let idx = j;
    for (let i = 0; i < 12; i++) {
      if (idx < JOURS_PAR_MOIS_AGRICOLE[i]) {
        const moisCivil = ((i + 7 - 1) % 12) + 1;
        const jour = idx + 1;
        return `${String(jour).padStart(2, "0")}/${String(moisCivil).padStart(2, "0")}`;
      }
      idx -= JOURS_PAR_MOIS_AGRICOLE[i];
    }
    return null;
  }

  // Aujourd'hui en index agricole (en fonction de new Date()).
  function aujourdhuiAgricole() {
    const now = new Date();
    const jjmm = `${String(now.getDate()).padStart(2, "0")}/${String(now.getMonth() + 1).padStart(2, "0")}`;
    return jjmmToJourAgricole(jjmm);
  }

  // Heuristique label_court : prendre les mots après "de" dans le label,
  // sinon les 2 premiers mots du label.
  function deduireLabelCourt(input) {
    if (input.label_court) return input.label_court;
    if (!input.label) return input.id || "";
    const tokens = input.label.split(/\s+/);
    const idxDe = tokens.findIndex((t) => /^d[e']/i.test(t));
    if (idxDe >= 0 && tokens.length > idxDe + 1) {
      return tokens.slice(idxDe + 1, idxDe + 3).join(" ").toLowerCase();
    }
    return tokens.slice(0, 2).join(" ").toLowerCase();
  }

  // Parse une borne YAML (JJ/MM | event | event±Nunit) en index agricole.
  // Retourne {jour: int|null, jourRaw: int|null, isEvent, eventId, ...offset}.
  //
  // `jour`    = index agricole borne dans [0, TOTAL_JOURS) (modulo) -- sert au
  //             DESSIN sur la barre (toujours un index valide).
  // `jourRaw` = MÊME valeur mais NON repliee (sans le `% TOTAL_JOURS`) pour les
  //             bornes event±offset : un offset peut faire passer la borne juste
  //             avant le 1er juillet (valeur < 0) ou apres le 30 juin (>= 365).
  //             Le modulo masque ce franchissement et casse les COMPARAISONS de
  //             condition (ex `01/07 < semis-15jours` avec semis=14/07 : la
  //             borne semis-15j = 29/06, repliee a l'index 363, comparait
  //             faussement `0 < 363` = vrai alors que 29/06 precede le 1er
  //             juillet -> condition fausse). On garde donc le brut pour
  //             comparer dans un repere continu autour de l'event (cf.
  //             evalComparaison). Pour une date fixe ou un event nu, jourRaw ==
  //             jour (aucun repliement possible).
  const BORNE_RE = /^([a-z][a-z0-9_]*)(?:([+-])(\d+)(jours|semaines|mois))?$/;
  function parseBorne(val, valeursInputs) {
    if (!val) return { jour: null, jourRaw: null, isEvent: false };
    if (/^\d{2}\/\d{2}$/.test(val)) {
      const j = jjmmToJourAgricole(val);
      return { jour: j, jourRaw: j, isEvent: false };
    }
    const m = BORNE_RE.exec(val);
    if (!m) return { jour: null, jourRaw: null, isEvent: false };
    const eventId = m[1];
    const valEvent = valeursInputs[eventId];
    if (!valEvent) return { jour: null, jourRaw: null, isEvent: true, eventId };
    let jour = jjmmToJourAgricole(valEvent);
    if (jour === null) return { jour: null, jourRaw: null, isEvent: true, eventId };
    let jourRaw = jour;
    if (m[2]) {
      const sign = m[2] === "+" ? 1 : -1;
      const n = parseInt(m[3], 10);
      const unit = m[4];
      jourRaw = jour + sign * n * UNITES_JOURS[unit];
      jour = ((jourRaw % TOTAL_JOURS) + TOTAL_JOURS) % TOTAL_JOURS;
    }
    return {
      jour,
      jourRaw,
      isEvent: true,
      eventId,
      offsetSign: m[2] || null,
      offsetN: m[3] ? parseInt(m[3], 10) : null,
      offsetUnit: m[4] || null,
    };
  }

  // Evalue `condition` (mini-DSL "<terme> <op> <terme>") sur les valeurs
  // courantes du form. Un terme = JJ/MM | event | event±Nunit, EXACTEMENT
  // la grammaire des bornes du/au -> on le resout via parseBorne (synchro
  // avec le backend condition.py). La comparaison utilise l'ordre de
  // l'annee agricole (juillet=0 ... juin~365). Cf.
  // spec_extension_grammaire_condition.
  //
  // Retourne true si la condition est vraie ou absente, false sinon.
  // Mode "permissif" : si un terme reference un event non encore saisi
  // (ou non parseable), on retourne true -- la periode reste affichee sans
  // distorsion jusqu'a ce que l'utilisateur saisisse une valeur valide.
  //
  // Le terme = un sous-groupe (date | event | event±offset). On reutilise
  // le coeur de BORNE_RE pour les 2 cotes.
  const _TERME = "\\d{2}/\\d{2}|[a-z][a-z0-9_]*(?:[+-]\\d+(?:jours|semaines|mois))?";
  const CONDITION_RE = new RegExp(
    "^\\s*(" + _TERME + ")\\s*(<=|>=|==|!=|<|>)\\s*(" + _TERME + ")\\s*$"
  );
  // Ramene `f` (jour, possiblement franchissant l'annee) au representant
  // {f, f-365, f+365} le plus proche de l'ancre `a`. Sert a comparer deux
  // bornes dans un repere CONTINU : une condition compare des dates a quelques
  // jours/semaines l'une de l'autre dans le meme cycle agricole, donc on les
  // aligne autour d'une ancre commune plutot que sur l'origine fixe (1er juil).
  // Sans ca, une borne event±offset qui franchit le 1er juillet (ex 29/06,
  // index 363, juste AVANT l'origine 0) comparait a tort comme "tres apres"
  // (cf. bug calendrier overflow : 01/07 < semis-15jours faussement vrai).
  function _alignerSurAncre(f, a) {
    let best = f;
    let bestDist = Math.abs(f - a);
    for (const cand of [f - TOTAL_JOURS, f + TOTAL_JOURS]) {
      const d = Math.abs(cand - a);
      if (d < bestDist) {
        bestDist = d;
        best = cand;
      }
    }
    return best;
  }

  // Evalue UNE comparaison `terme op terme`. Retourne true si vraie OU si un
  // terme n'est pas resolvable (event non saisi / part mal formee) -> mode
  // permissif (la periode reste affichee sans distorsion ; le validator
  // backend a deja rejete les conditions reellement invalides a la saisie).
  //
  // Comparaison dans un repere CONTINU autour des deux bornes : on part de leur
  // valeur NON repliee (jourRaw) puis on aligne chaque cote sur l'autre via
  // _alignerSurAncre. Cela neutralise le repliement annuel d'une borne
  // event±offset qui franchit le 1er juillet (sinon `01/07 < semis-15jours`
  // avec un semis tres precoce comparait `0 < 363` = vrai a tort, et peignait
  // tout le calendrier en interdit). Les cas sans franchissement sont
  // inchanges (jourRaw == jour, alignement = identite).
  function evalComparaison(rawCmp, valeurs) {
    const m = CONDITION_RE.exec(rawCmp);
    if (!m) return true;
    const op = m[2];
    const pg = parseBorne(m[1], valeurs);
    const pd = parseBorne(m[3], valeurs);
    if (pg.jourRaw === null || pd.jourRaw === null) return true;
    const gauche = _alignerSurAncre(pg.jourRaw, pd.jourRaw);
    const droite = _alignerSurAncre(pd.jourRaw, pg.jourRaw);
    switch (op) {
      case "<": return gauche < droite;
      case "<=": return gauche <= droite;
      case ">": return gauche > droite;
      case ">=": return gauche >= droite;
      case "==": return gauche === droite;
      case "!=": return gauche !== droite;
    }
    return true;
  }
  // Une condition = 1+ comparaisons jointes par `&&` (conjonction / ET) : vraie
  // si TOUTES le sont. Pas de `||` ni de parentheses (cf. condition.py backend,
  // qui DOIT rester synchro). Condition absente => true.
  function evalCondition(rawCond, valeurs) {
    if (!rawCond) return true;
    return rawCond
      .split("&&")
      .every((cmp) => evalComparaison(cmp, valeurs));
  }

  // Detecte une fenetre DEGENEREE : un intervalle `du -> au` qui s'inverse
  // (au tombe AVANT du dans le sens avant) a cause d'une date saisie, ce qui
  // sans garde wrappe via `% 365` et peint quasi toute l'annee (bug calendrier).
  // Couvre les deux symptomes observes :
  //   - une borne event±offset qui franchit le 1er juillet (ex `du: 01/07,
  //     au: semis-15jours` avec un semis tres precoce) ;
  //   - une borne event (±offset) trop tardive/precoce qui passe de l'autre
  //     cote d'une borne fixe (ex `du: destruction-20j, au: 31/01` avec une
  //     destruction en mars -> du=23/02 > au=31/01).
  // Garde-fou ROBUSTE cote moteur (ne depend pas d'un `condition:` explicite
  // dans le YAML). On PRESERVE les wraps d'annee VOLONTAIRES entre deux dates
  // FIXES (ex `du: 15/10 au: 31/01`) : voir _fenetreDegeneree.
  function _fenetreDegeneree(p, valeurs) {
    const du = parseBorne(p.du, valeurs);
    const au = parseBorne(p.au, valeurs);
    if (du.jourRaw === null || au.jourRaw === null) return false;
    // Détection d'inversion (`au` tombe avant `du`), en deux régimes selon que
    // l'une des bornes FRANCHIT réellement l'année agricole (jourRaw hors
    // [0, 365) : un event±offset qui déborde du 1er juillet ou du 30 juin) :
    //
    //   - Aucun franchissement (les 2 jourRaw ∈ [0, 365)) : on compare les
    //     index agricoles NATIFS bornés. C'est le repère fidèle à la barre
    //     dessinée. `_alignerSurAncre` est PROSCRIT ici : il replierait une
    //     fenêtre longue mais parfaitement valide vers une pseudo-inversion —
    //     p.ex. `du: destruction-20j (12/10) au: 30/06` avec une destruction
    //     au 01/11 aligne 30/06 sur -1 et neutralise à tort l'interdit (bug
    //     signalé : l'interdit démarrait au 15/10 au lieu du 12/10).
    //   - Un franchissement d'année : là l'index natif MENT (le modulo replie
    //     la borne débordante du mauvais côté), on repasse par l'alignement
    //     continu autour de l'ancre pour retrouver l'ordre réel (ex `du: 01/07
    //     au: semis-15j` avec un semis précoce -> semis-15j = 29/06, jourRaw
    //     négatif, réellement AVANT le 01/07).
    const franchit = (b) => b.jourRaw < 0 || b.jourRaw >= TOTAL_JOURS;
    const inverse = franchit(du) || franchit(au)
      ? _alignerSurAncre(au.jourRaw, du.jourRaw) < du.jourRaw
      : au.jour < du.jour;
    if (!inverse) return false;
    // Une inversion est DÉGÉNÉRÉE (donnée incohérente -> on neutralise la
    // période, sinon elle wrappe et peint quasi toute l'année) quand au moins
    // une borne est un EVENT : sa position dépend d'une date saisie, et c'est
    // cette saisie « trop tardive/précoce » qui a provoqué l'inversion
    //   - ex `du: destruction-20j au: 31/01` avec une destruction en mars
    //     -> du=23/02 > au=31/01, intervalle inversé involontaire (bug signalé) ;
    //   - ex `du: date_semis au: date_destruction` avec semis après destruction.
    // En revanche, une inversion entre DEUX DATES FIXES (ex `du: 15/10 au:
    // 31/01`) est un wrap d'année VOLONTAIRE de l'auteur -> on la conserve.
    return du.isEvent || au.isEvent;
  }

  // Predicat unique « la periode s'applique pour ces valeurs » : condition vraie
  // (ou absente) ET fenetre non degeneree. Utilise partout ou l'on filtrait
  // auparavant sur la seule condition, pour que peinture, recap, bornes et
  // legende voient exactement le meme jeu de periodes actives.
  function _periodeActive(p, valeurs) {
    return evalCondition(p.condition, valeurs) && !_fenetreDegeneree(p, valeurs);
  }

  // Hierarchie de severite des regimes pour la linearisation visuelle
  // (cf. spec_extension_grammaire_condition §Linearisation). Plus la
  // valeur est haute, plus le regime est severe -> il "gagne" quand
  // 2 periodes principales se chevauchent au meme jour. Hors masque
  // uniquement : les masques ont leur propre passe et ne participent
  // pas a la hierarchie principale.
  const SEVERITE_REGIME = {
    libre: 0,
    plafonnement: 1,
    autorisation_sous_condition: 2,
    interdiction: 3,
    non_applicable: -1,
  };

  // Construit le tableau régime-par-jour en 2 passes (cf.
  // spec_grammaire_calculatrice §masque + spec_extension_grammaire_condition) :
  //
  //   Filtrage prealable — Periodes dont la `condition` est fausse sont
  //     retirees avant la 1re passe (idem que si elles n'existaient pas).
  //
  //   Passe 1 — Périodes PRINCIPALES (masque ≠ true). Sur chevauchement,
  //     le regime LE PLUS SEVERE gagne (linearisation visuelle).
  //
  //   Passe 2 — Périodes MASQUE (masque === true). Elles ne s'appliquent
  //     QUE sur l'intersection avec les jours déjà couverts par une
  //     période principale en passe 1. Hors intersection : silence
  //     (la période est sans effet, pas d'affichage). Sur la zone
  //     intersection :
  //       - vs la PRINCIPALE sous-jacente : le masque ecrase toujours
  //         (override : c'est le but du masque, ex 'interdit avant
  //         4 semaines apres semis' override l'autorise du cadre).
  //       - vs un AUTRE masque qui a deja peint le meme jour : hierarchie
  //         de severite, le plus restrictif gagne (interdiction >
  //         autorisation_sous_condition > libre). Sans ca, le dernier
  //         masque de la liste gagnait, et un masque ASC tardif pouvait
  //         cannibaliser un masque interdiction anterieur (bug observe :
  //         l'interdit '20j avant destruction' efface par l'ASC du semis).
  //
  // Le `libre` initial = pas de zone overlay (fond vert visible).
  function computeRegimePerDay(periodes, valeurs) {
    const result = new Array(TOTAL_JOURS).fill("libre");

    // Sentinel : qui a touché chaque jour en passe 1 ? Sert à savoir
    // si une période masque peut écrire à cet index ou non.
    const principalCovers = new Array(TOTAL_JOURS).fill(false);

    // Regime pose par un masque (passe 2) a chaque index, ou null si aucun
    // masque n'a encore touche ce jour. Sert a arbitrer DEUX masques qui se
    // chevauchent par severite (le 1er masque override la principale ; les
    // suivants ne gagnent que s'ils sont >= severes).
    const masqueRegime = new Array(TOTAL_JOURS).fill(null);

    // Compte le nombre de principales qui couvrent chaque jour. Sert a
    // distinguer un jour de CHEVAUCHEMENT reel (>=1 principale qui contient
    // le jour en son sein) d'un simple jour-frontiere ou deux principales
    // adjacentes se touchent (l'une finit, l'autre commence). cf. bug
    // masque : la principale "autorise 15j avant semis" finit AU semis et
    // le masque "interdit apres semis" commence AU semis -> le jour du
    // semis n'est PAS un vrai chevauchement, le masque ne doit pas peindre.
    const principalStarts = new Array(TOTAL_JOURS).fill(0);
    const principalEnds = new Array(TOTAL_JOURS).fill(0);

    const poserPrincipale = (p) => {
      const du = parseBorne(p.du, valeurs).jour;
      const au = parseBorne(p.au, valeurs).jour;
      const regime = p.regime || data.type || "interdiction";
      if (du === null || au === null) return;
      const apply = (i) => {
        // Hierarchie : on ecrit seulement si le nouveau regime est >=
        // celui deja en place (sur cet index). 'libre' a severite 0,
        // donc tout regime principal l'ecrase. Si 2 principales se
        // chevauchent, la plus severe gagne.
        const cur = result[i];
        if (
          !principalCovers[i] ||
          (SEVERITE_REGIME[regime] ?? 0) >= (SEVERITE_REGIME[cur] ?? 0)
        ) {
          result[i] = regime;
        }
        principalCovers[i] = true;
      };
      principalStarts[du] += 1;
      principalEnds[au] += 1;
      if (du <= au) {
        for (let i = du; i <= au; i++) apply(i);
      } else {
        for (let i = du; i < TOTAL_JOURS; i++) apply(i);
        for (let i = 0; i <= au; i++) apply(i);
      }
    };

    const poserMasque = (p) => {
      const du = parseBorne(p.du, valeurs).jour;
      const au = parseBorne(p.au, valeurs).jour;
      const regime = p.regime || data.type || "interdiction";
      if (du === null || au === null) return;
      const apply = (i) => {
        if (!principalCovers[i]) return;
        // Anti-artefact frontiere : si le PREMIER jour du masque (du) ne
        // fait que toucher la FIN d'une principale (principalEnds[i] > 0)
        // sans qu'aucune principale n'y (re)commence (principalStarts[i] ==
        // 0), ce n'est pas un vrai chevauchement -> le masque ne peint pas.
        // Ca evite le sliver d'interdiction d'1 jour au semis quand la
        // principale "autorise avant semis" finit pile au semis et le
        // masque "interdit apres semis" demarre au semis. Le vrai
        // chevauchement (avec la principale 15/10->31/01) commence plus loin.
        if (i === du && principalEnds[i] > 0 && principalStarts[i] === 0) {
          return;
        }
        // 1er masque sur ce jour : override la principale. Masque suivant :
        // ne gagne que s'il est >= severe que le masque deja en place (sinon
        // un ASC tardif ecraserait un interdit anterieur).
        if (
          masqueRegime[i] === null ||
          (SEVERITE_REGIME[regime] ?? 0) >= (SEVERITE_REGIME[masqueRegime[i]] ?? 0)
        ) {
          result[i] = regime;
          masqueRegime[i] = regime;
        }
      };
      if (du <= au) {
        for (let i = du; i <= au; i++) apply(i);
      } else {
        for (let i = du; i < TOTAL_JOURS; i++) apply(i);
        for (let i = 0; i <= au; i++) apply(i);
      }
    };

    // Filtrage : retire les periodes dont la condition est fausse pour
    // les valeurs courantes (cf. spec_extension_grammaire_condition) ET dont
    // la fenetre n'est pas degeneree (offset qui wrappe l'annee, cf.
    // _fenetreDegeneree -- bug calendrier overflow).
    const periodesActives = (periodes || []).filter((p) =>
      _periodeActive(p, valeurs)
    );

    // Passe 1 : principales avec hierarchie.
    for (const p of periodesActives) {
      if (p.masque) continue;
      poserPrincipale(p);
    }
    // Passe 2 : masques sur intersection seulement.
    for (const p of periodesActives) {
      if (!p.masque) continue;
      poserMasque(p);
    }
    return result;
  }

  // ─── Export Node (tests de logique pure) ───────────────────────────────
  // Toute la suite (État, rendu DOM) depend de document/window : on s'arrete
  // ici en Node et on n'expose que les fonctions pures du moteur de calcul.
  // `setData` permet aux tests d'injecter le `data` (type + periodes) lu en
  // navigateur depuis le <script type="application/json">.
  if (_isNode) {
    module.exports = {
      jjmmToJourAgricole,
      parseBorne,
      evalComparaison,
      evalCondition,
      computeRegimePerDay,
      _alignerSurAncre,
      jourAgricoleToJJMM,
      conditionToText,
      jourAgricoleToLisible,
      TOTAL_JOURS,
      setData: (d) => {
        data = d || {};
      },
    };
    return;
  }

  // ─── État ──────────────────────────────────────────────────────────────
  const inputs = (data.inputs_requis || []).filter(
    (inp) => inp && typeof inp === "object" && inp.id
  );
  // Ordre d'affichage du mini-form indépendant de l'ordre du YAML : le semis
  // précède toujours la destruction (logique agronomique : on sème AVANT de
  // détruire). Sans ce tri, une règle qui liste la destruction d'abord
  // affichait les champs inversés (destruction à gauche, semis à droite).
  // Tri stable (rang) : semis=0, destruction=2, autres=1 -> semis à gauche,
  // destruction à droite, le reste au milieu dans son ordre d'origine.
  const _rangInput = (inp) =>
    inp.id.includes("semis") ? 0 : inp.id.includes("destruction") ? 2 : 1;
  inputs.sort((a, b) => _rangInput(a) - _rangInput(b));
  if (inputs.length === 0) {
    mount.innerHTML =
      '<p class="fr-alert fr-alert--warning fr-alert--sm">Aucun input requis défini pour cette règle calculatrice.</p>';
    return;
  }

  // Texte d'intro adapté aux dates réellement demandées : on ne mentionne
  // « la date de semis » / « la date de destruction » que si l'input
  // correspondant est présent (détection par mot-clé dans l'id, robuste aux
  // variantes date_semis_couvert / date_semis_colza / date_destruction_*).
  const aSemis = inputs.some((i) => i.id.includes("semis"));
  const aDestruction = inputs.some((i) => i.id.includes("destruction"));
  const intro = root.querySelector(".calc-cal__intro");
  if (intro) {
    let dates;
    if (aSemis && aDestruction) {
      dates = "des dates de semis et de destruction du couvert";
    } else if (aDestruction) {
      dates = "de la date de destruction du couvert";
    } else if (aSemis) {
      dates = "de la date de semis du couvert";
    } else {
      dates = "des dates saisies";
    }
    intro.textContent =
      "Pour ce type d'interculture, la réglementation définit la période " +
      `d'épandage autorisée en fonction ${dates}. Saisissez ` +
      (inputs.length > 1 ? "ces dates" : "cette date") +
      " pour voir le calendrier.";
  }

  // Valeurs initiales : placeholder par defaut, MAIS si un query param porte
  // le meme id que l'input et contient un JJ/MM valide, il prend le dessus.
  // Permet des URLs integralement descriptives (ex ?date_semis_couvert=15/08
  // &date_destruction_couvert=15/12) — pratique pour partager un cas precis.
  // Les valeurs venues de l'URL sont marquees comme "saisies" (pas grisees).
  const params = new URLSearchParams(window.location.search);
  const valeurs = {};
  const valeursDepuisUrl = new Set();
  for (const inp of inputs) {
    const fromUrl = (params.get(inp.id) || "").trim();
    if (/^\d{2}\/\d{2}$/.test(fromUrl)) {
      valeurs[inp.id] = fromUrl;
      valeursDepuisUrl.add(inp.id);
    } else {
      valeurs[inp.id] = inp.placeholder || "";
    }
  }

  // ─── Rendu ─────────────────────────────────────────────────────────────
  // Tout le rendu reproduit la structure DOM du templatetag standard
  // `calendrier_epandage` (cf. _calendrier.html + calendrier.css), de sorte
  // que les 2 calendriers (statique / dynamique) aient le meme look. Les
  // classes utilisees sont `.calendrier-epandage*`.

  function renderMiniForm() {
    // 2 inputs cote a cote, label sur 1 ligne ferme (truncate si trop long)
    // pour eviter que les hauteurs des champs varient selon le label (le
    // user a explicitement reporte cet alignement casse).
    //
    // Pico calendrier SVG (DSFR icon calendar-line equivalent, inline pour
    // eviter un asset HTTP supplementaire). Le pictogramme ne sert qu'a
    // signaler que c'est un champ date, pas a ouvrir un date picker
    // (impossible JJ/MM sans annee en HTML natif -- MVP-2).
    const SVG_CAL =
      '<svg class="calc-cal__field-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">' +
      '<rect x="3.5" y="5" width="17" height="15" rx="2"/>' +
      '<line x1="3.5" y1="9.5" x2="20.5" y2="9.5"/>' +
      '<line x1="8" y1="3" x2="8" y2="6.5"/>' +
      '<line x1="16" y1="3" x2="16" y2="6.5"/>' +
      "</svg>";
    return `
      <div class="calc-cal__form">
        ${inputs
          .map((inp) => {
            const isDefault =
              !valeursDepuisUrl.has(inp.id) &&
              valeurs[inp.id] &&
              valeurs[inp.id] === (inp.placeholder || "");
            return `
          <label class="calc-cal__field">
            <span class="calc-cal__field-label">${escapeHtml(inp.label || inp.id)}</span>
            <input type="text"
                   class="fr-input"
                   data-input-id="${escapeHtml(inp.id)}"
                   value="${escapeHtml(valeurs[inp.id])}"
                   placeholder="JJ/MM"
                   pattern="^\\d{2}/\\d{2}$"
                   maxlength="5"
                   ${isDefault ? 'data-default="true"' : ""}>
            ${SVG_CAL}
          </label>
        `;
          })
          .join("")}
      </div>
    `;
  }

  // Segments contigus de meme regime, derives de regimeParJour. Source
  // unique de verite pour la barre, les bornes ET le recap (ce qui s'applique
  // REELLEMENT, masques resolus -- pas les periodes brutes).
  function computeSegments(regimeParJour) {
    const segments = [];
    let cur = { regime: regimeParJour[0], du: 0, au: 0 };
    for (let i = 1; i < TOTAL_JOURS; i++) {
      if (regimeParJour[i] === cur.regime) {
        cur.au = i;
      } else {
        segments.push(cur);
        cur = { regime: regimeParJour[i], du: i, au: i };
      }
    }
    segments.push(cur);
    return segments;
  }

  function renderCalendrier(regimeParJour, actives) {
    // On ne génère une zone overlay QUE pour rouge/orange : le vert est le
    // fond global de la barre.
    const segmentsRaw = computeSegments(regimeParJour);

    // Les zones n'ont plus de bordure verticale : chaque frontiere est
    // materialisee par un unique tic (cf. renderBornes / CSS --big-tick).
    // Une zone ne porte donc que son fond colore + son z-index.
    const zonesHtml = segmentsRaw
      .map((s) => {
        const couleur = REGIME_COULEUR_ZONE[s.regime];
        if (!couleur) return "";
        const w = ((s.au - s.du + 1) / TOTAL_JOURS) * 100;
        const left = (s.du / TOTAL_JOURS) * 100;
        const flottant = isPeriodeFlottante(s, actives);
        const classes = [
          "calendrier-epandage__zone",
          `calendrier-epandage__zone--${couleur}`,
        ];
        if (flottant) classes.push("calendrier-epandage__zone--flottant");
        // Tooltip : phrase humaine qui decrit la fenetre. On cherche la
        // periode YAML d'origine qui couvre ce segment (premier match)
        // pour reutiliser sa structure (du, au, regime) et generer une
        // annotation event+offset si applicable.
        const tooltip = buildTooltipForSegment(s, actives);
        return `<div class="${classes.join(" ")}"
                     style="left:${left.toFixed(3)}%; width:${w.toFixed(3)}%"
                     aria-label="${escapeHtml(tooltip)}"
                     data-tooltip="${escapeHtml(tooltip)}"></div>`;
      })
      .join("");

    // Marqueur "aujourd'hui" : point noir DANS la barre + label distinct ancre
    // sur la barre (cf. CSS `.calendrier-epandage__today` / `__today-label`).
    // Le label est un element a part (plus le ::after) pour etre borne par les
    // bords du calendrier et ne jamais etre croppe quand le point tombe pres
    // d'un bord (#134) ; meme structure que le templatetag statique.
    const aujourdhui = aujourdhuiAgricole();
    const aujLeft = aujourdhui != null ? (aujourdhui / TOTAL_JOURS) * 100 : null;
    const aujourdhuiHtml =
      aujLeft != null
        ? `<div class="calendrier-epandage__today" style="left:${aujLeft.toFixed(3)}%" aria-label="Aujourd'hui"></div>` +
          `<span class="calendrier-epandage__today-label" style="--today-pct:${aujLeft.toFixed(3)}%">Aujourd'hui</span>`
        : "";

    // Bornes textuelles sous la barre. Source unique = les segments
    // effectifs de la barre (regimeParJour) -> on ne marque que les vraies
    // frontieres de zone + les dates saisies (cf. renderBornes).
    const bornesHtml = renderBornes(regimeParJour, segmentsRaw);

    return `
      <div class="calendrier-epandage calendrier-epandage--vert">
        <div class="calendrier-epandage__months">
          ${MOIS_AGRICOLES.map((m, i) => `<span data-court="${MOIS_AGRICOLES_COURTS[i]}">${m}</span>`).join("")}
        </div>
        <div class="calendrier-epandage__bar" data-tooltip="Autorisé">
          ${zonesHtml}
          ${aujourdhuiHtml}
        </div>
        ${bornesHtml}
      </div>
    `;
  }

  // Construit le tooltip humain pour un segment de la barre. Cherche la
  // periode YAML qui couvre la zone (au sens jours) ; si elle est
  // event+offset, genere une phrase « jusqu'a N semaines apres semis ».
  function buildTooltipForSegment(segment, actives) {
    const inputById = Object.fromEntries(inputs.map((i) => [i.id, i]));
    for (const p of actives || []) {
      const partDu = parseBorne(p.du, valeurs);
      const partAu = parseBorne(p.au, valeurs);
      if (partDu.jour === null || partAu.jour === null) continue;
      // Match strict : meme bornes.
      if (partDu.jour !== segment.du || partAu.jour !== segment.au) continue;
      const regime = p.regime || segment.regime || "interdiction";
      const verbe = capitalize(REGIME_VERBE[regime] || regime);
      const annDu = annoterBorne(partDu, "du", inputById);
      const annAu = annoterBorne(partAu, "au", inputById);
      const annotations = [annDu, annAu].filter(Boolean);
      if (annotations.length > 0) {
        return `${verbe} ${annotations.join(", ")}`;
      }
      const duStr = jourAgricoleToLisible(partDu.jour);
      const auStr = jourAgricoleToLisible(partAu.jour);
      return `${verbe} du ${duStr} au ${auStr}`;
    }
    return REGIME_VERBE[segment.regime] || segment.regime;
  }

  // Genere « a partir de N jours apres semis » (mode=du) ou « jusqu'a
  // N jours apres semis » (mode=au), seulement pour les bornes event+offset.
  // Pour les bornes event nu (sans offset), pas d'annotation.
  function annoterBorne(part, mode, inputById) {
    if (!part.isEvent || !part.eventId || !part.offsetN) return null;
    const inp = inputById[part.eventId];
    const lc = inp ? deduireLabelCourt(inp) : part.eventId;
    const prep = part.offsetSign === "+" ? "après" : "avant";
    const direction =
      mode === "du"
        ? part.offsetSign === "+"
          ? "à partir de"
          : "jusqu'à"
        : part.offsetSign === "+"
          ? "jusqu'à"
          : "à partir de";
    return `${direction} ${part.offsetN} ${part.offsetUnit} ${prep} ${lc}`;
  }

  // Heuristique : un segment dont l'une des bornes YAML d'origine est un
  // event nu (sans date connue cote utilisateur) -> hachuré flottant.
  // Pour MVP, on considere qu'une periode est flottante uniquement si la
  // borne YAML est un event SANS placeholder et SANS valeur saisie.
  function isPeriodeFlottante(segment, periodes) {
    for (const p of periodes || []) {
      const du = parseBorne(p.du, valeurs);
      const au = parseBorne(p.au, valeurs);
      if (du.jour === segment.du && au.jour === segment.au) {
        return (du.isEvent && du.jour === null) || (au.isEvent && au.jour === null);
      }
    }
    return false;
  }

  // Ordre de priorite des couleurs de tick (cf. regle epuration user) :
  // un seul tick par jour, on garde la couleur de plus haut ordre.
  //   noir (semis/destruction) > rouge (interdit) > orange (s/c) > vert.
  const TICK_PRIORITE = { noir: 3, rouge: 2, orange: 1, vert: 0 };

  // Bornes sous la barre — REGLE D'EPURATION (cf. retours user) :
  //
  //   1. UN SEUL tick par jour. Si plusieurs bornes tombent le meme jour,
  //      on ne garde que la couleur de plus haut ordre (noir > rouge >
  //      orange > vert).
  //   2. On ne marque QUE les vraies frontieres de zone (jour ou la couleur
  //      EFFECTIVE de la barre change) + les dates SAISIES (semis,
  //      destruction). Plus de bornes YAML "theoriques" noyees au milieu
  //      d'une zone de meme couleur (ex : 15/10 cache dans le rouge alors
  //      que la zone rouge va de 13/10 a 31/10 -> on montre 13 et 31, pas 15).
  //   3. Collision input/frontiere le meme jour : le NOIR (date saisie)
  //      gagne, la frontiere coloree est absorbee.
  //
  // Source unique de verite = `segments` (issus de regimeParJour, le calcul
  // jour-par-jour effectif). On NE relit PAS les bornes YAML brutes.
  function renderBornes(regimeParJour, segments) {
    // ── 1. Frontieres de zone effectives ────────────────────────────────
    // Une frontiere = jour `j` ou regimeParJour[j] != regimeParJour[j-1].
    // Couleur du tick = regime le plus restrictif des 2 cotes (le tick
    // materialise le bord ; on prend la teinte la plus "forte" qui le
    // borde, pour que p.ex. le debut d'un rouge soit rouge).
    // On ignore les frontieres dont les 2 cotes sont sans couleur (vert/
    // vert ne produit pas de tick).
    // byDay clef = jour de POSITION du tick (pct). On distingue ce jour de
    // position du jour AFFICHE (label) : pour une frontiere de FIN de zone,
    // le tick se pose au bord droit geometrique (au+1) MAIS doit afficher le
    // DERNIER jour inclus dans la zone (au), sinon on lit "16 dec" alors que
    // l'interdit s'arrete le 15 (= destruction). cf. bug user.
    const byDay = new Map(); // jourPos -> {jourPos, jourLabel, couleur}
    const couleurDe = (regime) => REGIME_COULEUR_ZONE[regime] || "vert";
    const plusFort = (a, b) =>
      (TICK_PRIORITE[a] ?? -1) >= (TICK_PRIORITE[b] ?? -1) ? a : b;

    // Chaque frontiere porte la couleur de SA zone et le jour a afficher
    // (jourLabel) = le bord metier de cette zone : son 1er jour (debut) ou
    // son dernier jour inclus (fin). Quand 2 frontieres tombent le meme jour
    // de position (zone A finit -> zone B commence), on garde le label de la
    // zone la PLUS RESTRICTIVE (rouge > orange) : c'est sa borne qui fait
    // sens (ex : debut interdit = 25/11, fin interdit = 15/12), pas le bord
    // de la zone d'autorisation adjacente.
    // Une frontiere appartient a UNE zone (sa `zoneCouleur`) et affiche le
    // bord metier de CETTE zone : son 1er jour (debut) ou son dernier jour
    // inclus (fin). `couleur` = teinte d'affichage du tick (le plus
    // restrictif des 2 cotes). Quand 2 frontieres tombent le meme jour
    // (zone A finit -> zone B commence), le LABEL retenu est celui de la
    // zone la plus restrictive (rouge > orange) : sa borne est la date
    // metier pertinente (debut interdit 25/11, fin interdit 15/12), pas le
    // bord de la zone d'autorisation adjacente.
    const couleurRang = (c) => TICK_PRIORITE[c] ?? -1;
    const poserFrontiere = (jourPos, couleur, jourLabel, zoneCouleur) => {
      if (couleur === "vert") return; // pas de tick pour une frontiere verte
      const lbl = jourLabel === undefined ? jourPos : jourLabel;
      const prev = byDay.get(jourPos);
      if (!prev) {
        byDay.set(jourPos, {
          jourPos,
          jourLabel: lbl,
          couleur,
          zoneCouleur,
          kind: "frontiere",
        });
      } else if (prev.kind === "frontiere") {
        prev.couleur = plusFort(prev.couleur, couleur);
        // Le label suit la zone la plus restrictive parmi les frontieres
        // empilees sur ce jour.
        if (couleurRang(zoneCouleur) > couleurRang(prev.zoneCouleur)) {
          prev.jourLabel = lbl;
          prev.zoneCouleur = zoneCouleur;
        }
      }
    };

    for (const s of segments || []) {
      const cAvant =
        s.du > 0 ? couleurDe(regimeParJour[s.du - 1]) : "vert";
      const cIci = couleurDe(s.regime);
      // Debut de segment colore : tick si transition visible. La frontiere
      // appartient a CE segment (zoneCouleur = cIci), label = son 1er jour.
      if (cIci !== "vert" && s.du > 0 && cIci !== cAvant) {
        poserFrontiere(s.du, plusFort(cIci, cAvant), s.du, cIci);
      }
      // Fin de segment colore : position = bord droit geometrique (au+1)
      // pour coller a la fin de la couleur ; label = `au` = dernier jour
      // inclus (sinon "interdit jusqu'au 15/12" s'etiquette "16 dec").
      const cApres =
        s.au + 1 < TOTAL_JOURS ? couleurDe(regimeParJour[s.au + 1]) : "vert";
      if (cIci !== "vert" && cApres !== cIci) {
        const jourBordDroit = s.au + 1;
        if (jourBordDroit < TOTAL_JOURS) {
          poserFrontiere(jourBordDroit, plusFort(cIci, cApres), s.au, cIci);
        }
      }
    }

    // ── 2. Dates saisies (semis/destruction) : noir, prioritaires ───────
    // Elles ECRASENT toute frontiere coincidente (regle 3 : noir gagne).
    const inputByDay = new Map();
    for (const inp of inputs) {
      const j = jjmmToJourAgricole(valeurs[inp.id]);
      if (j === null) continue;
      inputByDay.set(j, {
        jour: j,
        couleur: "noir",
        kind: "input",
        label: deduireLabelCourt(inp),
        title: `${inp.label || inp.id} : ${valeurs[inp.id]}`,
      });
    }

    // Fusion (REGLE GENERALE) : une date saisie (semis/destruction) absorbe
    // toute frontiere de zone ADJACENTE -- c'est le tick noir qui materialise
    // cette transition, peu importe :
    //   - le sens   (debut ou fin de zone),
    //   - le regime (interdiction rouge ou autorisation orange),
    //   - le cote   (la zone finit AU jour saisi, ou la suivante commence
    //                le LENDEMAIN : deux faces de la meme transition).
    // "Adjacente" = jourLabel a +/-1 jour de la date saisie. On compare sur
    // jourLabel (jour metier affiche), pas sur la position du tick (qui peut
    // etre au bord geometrique au+1). Resultat : 1 seul tick (noir) par date
    // saisie, jamais de borne de zone redondante a cote.
    const inputDays = [...inputByDay.keys()];
    const adjacentInput = (jour) =>
      typeof jour === "number" &&
      inputDays.some((d) => Math.abs(d - jour) <= 1);
    for (const [pos, f] of [...byDay]) {
      if (adjacentInput(f.jourLabel)) byDay.delete(pos);
    }

    // ── 3. Assemblage des items ─────────────────────────────────────────
    const items = [];
    for (const f of byDay.values()) {
      items.push({
        jour: f.jourPos,
        pct: (f.jourPos / TOTAL_JOURS) * 100, // position = bord geometrique
        label: jourAgricoleToLisible(f.jourLabel), // affichage = dernier jour inclus
        couleur: f.couleur,
        kind: "frontiere",
        title: null,
        row: 0,
      });
    }
    for (const it of inputByDay.values()) {
      items.push({
        jour: it.jour,
        pct: (it.jour / TOTAL_JOURS) * 100,
        label: it.label,
        couleur: "noir",
        kind: "input",
        title: it.title,
        row: 0,
      });
    }
    if (items.length === 0) return "";

    // Tous emis en row0. L'anti-collision vertical se fait APRES rendu, par
    // mesure reelle du DOM (layoutBornesRows), seule methode fiable : les
    // largeurs de label ne sont pas connues avant le rendu. Tri par pct pour
    // que le layout post-rendu traite les ticks de gauche a droite.
    items.sort((a, b) => a.pct - b.pct);

    const inner = items
      .map((it) => {
        const cls = [
          "calendrier-epandage__period-date",
          "calendrier-epandage__period-date--phenologique",
        ];
        // Couleur du tick. 'noir' = pas de classe couleur (defaut noir via
        // --big-tick). rouge/orange via classes dediees. vert n'arrive pas
        // ici (filtre poserFrontiere).
        if (it.couleur && it.couleur !== "noir") {
          cls.push(`calendrier-epandage__period-date--${it.couleur}`);
        }
        // TOUS les ticks (frontieres de zone ET dates saisies) sont des
        // big-tick : un SEUL trait vertical qui traverse toute la barre puis
        // deborde de quelques px sous elle pour rejoindre le label. C'est ce
        // meme trait unique qui materialise la frontiere -- les zones n'ont
        // donc plus de border-left/right (cf. CSS). Garantit une ligne
        // continue, meme couleur, parfaitement alignee (un seul element par
        // frontiere au lieu de bordure-de-zone + leader separe).
        cls.push("calendrier-epandage__period-date--big-tick");
        const tip = it.title || it.label;
        // Le texte est dans un span INTERNE place sur une couche z-index
        // superieure aux tics (cf. CSS .period isolation) : ainsi aucune barre
        // verticale ne coupe le libelle quand deux dates sont proches. Le tic
        // (::before) reste sur la couche basse, derriere tous les textes.
        return `<span class="${cls.join(" ")}"
                       style="left:${it.pct.toFixed(3)}%"
                       data-tooltip="${escapeHtml(tip)}"><span class="calendrier-epandage__period-date-label">${escapeHtml(it.label)}</span></span>`;
      })
      .join("");
    return `<div class="calendrier-epandage__period">${inner}</div>`;
  }

  // Calcule la fenetre effective d'une periode :
  //   - principale (masque != true) : juste la fenetre YAML resolue.
  //   - masque (masque === true)    : intersection avec l'union des
  //     principales. On retourne le PREMIER segment connexe d'intersection
  //     (sans gerer le cas multi-segments rare ou un masque couvre 2
  //     principales disjointes).
  // Retourne `{du, au}` en index agricole, ou `null` si pas de fenetre.
  function effectivePeriodWindow(p) {
    const du = parseBorne(p.du, valeurs).jour;
    const au = parseBorne(p.au, valeurs).jour;
    if (du === null || au === null) return null;
    if (!p.masque) return { du, au };
    // Masque : intersecter [du..au] avec principalCovers.
    const covers = computePrincipalCovers();
    // Bornes des principales (debut/fin) pour ignorer les jours-frontiere :
    // un jour ou une principale FINIT sans qu'aucune ne (re)commence n'est
    // pas un vrai chevauchement -- meme regle que poserMasque (cf. bug
    // sliver d'interdiction au semis). Sans ca, la fenetre effective du
    // recap commencerait au semis alors que la barre demarre au 15/10.
    const liste = (data.periodes || []).filter((pp) =>
      _periodeActive(pp, valeurs)
    );
    const starts = new Array(TOTAL_JOURS).fill(0);
    const ends = new Array(TOTAL_JOURS).fill(0);
    for (const pp of liste) {
      if (pp.masque) continue;
      const d = parseBorne(pp.du, valeurs).jour;
      const a = parseBorne(pp.au, valeurs).jour;
      if (d === null || a === null) continue;
      starts[d] += 1;
      ends[a] += 1;
    }
    const inMaskRange = (i) => {
      if (du <= au) return i >= du && i <= au;
      return i >= du || i <= au;
    };
    // Premier jour de l'intersection
    let first = null;
    let last = null;
    const estChevauchementReel = (i) => {
      if (!covers[i]) return false;
      // Jour-frontiere pur (fin d'une principale, aucune qui commence) : on
      // ne le compte pas comme chevauchement tant qu'on n'a pas encore
      // demarre le segment (first === null).
      if (first === null && i === du && ends[i] > 0 && starts[i] === 0) {
        return false;
      }
      return true;
    };
    const range = (start, end) => {
      for (let i = start; i <= end; i++) {
        if (inMaskRange(i) && estChevauchementReel(i)) {
          if (first === null) first = i;
          last = i;
        } else if (first !== null) {
          // fin du 1er segment connexe
          return true;
        }
      }
      return false;
    };
    // Parcourir l'annee dans l'ordre [du..end][0..au] si wrap, sinon [du..au].
    if (du <= au) {
      range(du, au);
    } else {
      if (!range(du, TOTAL_JOURS - 1)) {
        range(0, au);
      }
    }
    if (first === null) return null;
    return { du: first, au: last };
  }

  // Retourne le Set des periodes "actives" pour les render-helpers :
  //   - les periodes dont la `condition` est vraie pour les valeurs
  //     courantes du form (cf. spec_extension_grammaire_condition) ;
  //   - parmi celles-la : toutes les principales (masque != true), meme
  //     si bornes non resolues -- elles seront ignorees plus loin via
  //     parseBorne null ;
  //   - et les masques dont l'intersection avec les principales est
  //     non vide.
  function activePeriodesSet() {
    const periodes = (data.periodes || []).filter((p) =>
      _periodeActive(p, valeurs)
    );
    const principalCovers = computePrincipalCovers(periodes);
    const result = new Set();
    for (const p of periodes) {
      if (!p.masque) {
        result.add(p);
        continue;
      }
      // Masque : verifier l'intersection avec principalCovers.
      const du = parseBorne(p.du, valeurs).jour;
      const au = parseBorne(p.au, valeurs).jour;
      if (du === null || au === null) continue;
      if (hasIntersection(principalCovers, du, au)) {
        result.add(p);
      }
    }
    return result;
  }

  function computePrincipalCovers(periodes) {
    // `periodes` peut etre fourni (deja filtre par condition) ou non
    // (fallback : on lit data.periodes et on filtre ici).
    const liste = periodes || (data.periodes || []).filter((p) =>
      _periodeActive(p, valeurs)
    );
    const covers = new Array(TOTAL_JOURS).fill(false);
    for (const p of liste) {
      if (p.masque) continue;
      const du = parseBorne(p.du, valeurs).jour;
      const au = parseBorne(p.au, valeurs).jour;
      if (du === null || au === null) continue;
      if (du <= au) {
        for (let i = du; i <= au; i++) covers[i] = true;
      } else {
        for (let i = du; i < TOTAL_JOURS; i++) covers[i] = true;
        for (let i = 0; i <= au; i++) covers[i] = true;
      }
    }
    return covers;
  }

  function hasIntersection(covers, du, au) {
    const test = (i) => covers[i];
    if (du <= au) {
      for (let i = du; i <= au; i++) if (test(i)) return true;
    } else {
      for (let i = du; i < TOTAL_JOURS; i++) if (test(i)) return true;
      for (let i = 0; i <= au; i++) if (test(i)) return true;
    }
    return false;
  }

  function renderLegende(regimeParJour) {
    // Legende dynamique : on ne liste que les couleurs presentes a l'ecran.
    const couleursPresentes = new Set();
    for (const r of regimeParJour) {
      const c = REGIME_COULEUR_ZONE[r];
      if (c) couleursPresentes.add(c);
    }
    // "vert" est toujours present (fond global), mais on ne l'ajoute que
    // s'il existe au moins un jour libre (sinon c'est trompeur).
    if (regimeParJour.some((r) => !REGIME_COULEUR_ZONE[r])) {
      couleursPresentes.add("vert");
    }
    const ordre = ["rouge", "orange", "vert"];
    const labels = {
      rouge: "Interdit",
      orange: "Autorisé sous conditions",
      vert: "Autorisé",
    };
    const items = ordre
      .filter((c) => couleursPresentes.has(c))
      .map(
        (c) => `
        <li>
          <span class="calendrier-epandage__legende-puce calendrier-epandage__legende-puce--${c}"></span>
          ${labels[c]}
        </li>
      `,
      )
      .join("");
    return `<ul class="calendrier-epandage__legende">${items}</ul>`;
  }

  // Phrase humaine d'un terme de condition (date | event | event±offset).
  //   15/12                         -> "le 15 déc."
  //   date_destruction_couvert      -> "la destruction"
  //   date_semis_couvert+4semaines  -> "4 semaines après le semis"
  function termeToText(raw, inputById) {
    const m = BORNE_RE.exec(raw);
    if (!m) {
      // date fixe ?
      if (/^\d{2}\/\d{2}$/.test(raw)) {
        const j = jjmmToJourAgricole(raw);
        return j != null ? `le ${jourAgricoleToLisible(j)}` : raw;
      }
      return raw;
    }
    const eventId = m[1];
    const inp = inputById[eventId];
    const nom = inp ? deduireLabelCourt(inp) : eventId;
    if (!m[2]) {
      // event nu
      return `la ${nom}`;
    }
    // event ± offset
    const n = m[3];
    const unit = m[4];
    const prep = m[2] === "+" ? "après" : "avant";
    return `${n} ${unit} ${prep} le ${nom}`;
  }

  // Terme "event ± offset" exprime en phrase metier couvert (#159), ex :
  //   date_semis_couvert+4semaines    -> "4 semaines après l’implantation du couvert"
  //   date_destruction_couvert-20jours-> "20 jours avant la destruction ou la récolte du couvert"
  //   date_semis_couvert (nu)         -> "l’implantation du couvert"
  // Retourne null si le terme n'est pas un event couvert connu.
  function termeCouvertToText(raw) {
    const m = BORNE_RE.exec(raw);
    if (!m) return null;
    const ref = REF_COUVERT[m[1]];
    if (!ref) return null;
    if (!m[2]) return ref; // event nu
    const prep = m[2] === "+" ? "après" : "avant";
    return `${m[3]} ${m[4]} ${prep} ${ref}`;
  }

  // Traduit une condition "<terme> <op> <terme>" en JUSTIFICATION metier (#159).
  // Pour les couverts, un des deux termes est un event couvert (semis /
  // destruction) et l'autre une date fixe (borne technique, redondante). On
  // produit "Car interdit jusqu’à / à partir de <point de reference>" :
  //   - "jusqu’à"      quand la periode est ANTERIEURE au point event ;
  //   - "à partir de"  quand elle est POSTERIEURE.
  // On ne touche PAS a la construction du terme event (le "avant/après" de
  // l'offset vient du signe ±). Ex :
  //   15/10 < date_semis_couvert+4semaines
  //     -> "Car interdit jusqu’à 4 semaines après l’implantation du couvert"
  //   15/10 < date_destruction_couvert-20jours
  //     -> "Car interdit jusqu’à 20 jours avant la destruction ou la récolte du couvert"
  // Fallback sur l'ancienne tournure "car <g> est <op> <d>" si aucun terme
  // n'est un event couvert connu (robustesse hors-couvert).
  function conditionToText(rawCond, inputById) {
    if (!rawCond) return null;
    const m = CONDITION_RE.exec(rawCond);
    if (!m) return null;
    const gaucheRaw = m[1];
    const op = m[2];
    const droiteRaw = m[3];

    // Cas couvert : un terme event couvert + une date fixe.
    const evGauche = termeCouvertToText(gaucheRaw);
    const evDroite = termeCouvertToText(droiteRaw);
    if (evDroite && !evGauche) {
      // <date fixe> op <event> : op "<" => periode avant l'event => "jusqu’à".
      const prop = op === "<" || op === "<=" ? "jusqu’à" : "à partir de";
      return `Car interdit ${prop} ${evDroite}`;
    }
    if (evGauche && !evDroite) {
      // <event> op <date fixe> : op "<" => l'event est avant la date fixe,
      // donc l'interdiction commence a l'event => "à partir de".
      const prop = op === "<" || op === "<=" ? "à partir de" : "jusqu’à";
      return `Car interdit ${prop} ${evGauche}`;
    }

    // Fallback (hors couvert / deux dates fixes) : ancienne tournure.
    const gauche = termeToText(gaucheRaw, inputById);
    const droite = termeToText(droiteRaw, inputById);
    const tournure = {
      "<": "avant",
      "<=": "au plus tard à",
      ">": "après",
      ">=": "au plus tôt à",
      "==": "égal à",
      "!=": "différent de",
    }[op];
    if (!tournure) return null;
    return `car ${gauche} est ${tournure} ${droite}`;
  }

  // Trouve la periode active dont la fenetre EFFECTIVE recouvre ce segment,
  // pour recuperer ses annotations (event+offset) et sa condition. On prefere
  // la periode du meme regime que le segment, et celle dont la fenetre
  // effective coincide le mieux avec le segment. Retourne null si aucune.
  function periodeSourcePourSegment(segment, actives) {
    let best = null;
    for (const p of actives || []) {
      const regime = p.regime || "interdiction";
      if (regime !== segment.regime) continue;
      const eff = effectivePeriodWindow(p);
      if (!eff) continue;
      // Le segment doit etre inclus dans la fenetre effective de la periode.
      const couvre = eff.du <= segment.du && eff.au >= segment.au;
      if (!couvre) continue;
      // Prefere la fenetre la plus serree autour du segment (source la plus
      // specifique : un masque colle au segment plutot qu'une large principale).
      const largeur = eff.au - eff.du;
      if (best === null || largeur < best.largeur) {
        best = { p, largeur };
      }
    }
    return best ? best.p : null;
  }

  function renderRecap(regimeParJour, actives) {
    // Le recap liste les SEGMENTS EFFECTIFS de la barre (ce qui s'applique
    // REELLEMENT, masques resolus), pas les periodes brutes. Ainsi :
    //   - une periode masque qui recouvre integralement une principale fait
    //     disparaitre la ligne de cette principale (elle n'existe nulle part) ;
    //   - les fenetres affichees == celles dessinees sur la barre.
    // Pour chaque segment colore, on retrouve la periode source (meme regime,
    // fenetre effective englobante) afin de garder l'annotation event+offset
    // et la mention conditionnelle.
    const inputById = Object.fromEntries(inputs.map((i) => [i.id, i]));
    const segments = computeSegments(regimeParJour);

    // Ordre de presentation (maquette #130) : interdiction d'abord, puis
    // autorisation sous condition (prio), puis l'autorisation pure (#85) en
    // dernier (prio 2). Tri stable -> ordre chronologique conserve au sein
    // d'un meme regime.
    // Puces regroupees PAR REGIME (#159). Chaque puce : "du X au Y (annotation)"
    // + un picto info ⓘ portant la JUSTIFICATION en tooltip (le "— car ..."
    // n'est plus affiche en clair, il passe dans le ⓘ). On ne change PAS la
    // construction de la phrase de justification (conditionToText), seulement
    // son emplacement d'affichage.
    const pucesParRegime = {}; // regime -> [html <li>...]
    for (const seg of segments) {
      const regime = seg.regime;
      if (!REGIME_COULEUR_ZONE[regime]) continue; // libre/vert : gere a part
      const duStr = jourAgricoleToLisible(seg.du);
      const auStr = jourAgricoleToLisible(seg.au);
      let ligne = `du ${duStr} au ${auStr}`;

      const src = periodeSourcePourSegment(seg, actives);
      if (src) {
        // #159 (retour Emma) : la justification metier remplace l'ENTIERETE de
        // l'ancien "(annotation) — car ..." (l'annotation event+offset entre
        // parentheses N'EST PLUS affichee separement). On ne garde qu'un picto
        // ⓘ dont le tooltip porte la phrase complete "(car interdit jusqu'a...)".
        const condTxt = conditionToText(src.condition, inputById);
        if (condTxt) {
          ligne += ` <span class="calc-cal__recap-info" tabindex="0" role="img" aria-label="${escapeHtml(condTxt)}" data-tooltip="${escapeHtml(condTxt)}">ⓘ</span>`;
        }
      }
      (pucesParRegime[regime] = pucesParRegime[regime] || []).push(
        `<li>${ligne}</li>`
      );
    }

    // Periode d'autorisation pure (vert, #85) = jours ni interdits ni sous
    // condition, fusionnee (dont le wrap juin->juillet) en UNE ligne.
    const ligneAutorisation = buildLigneAutorisation(segments);
    if (ligneAutorisation) {
      pucesParRegime.libre = [`<li>${ligneAutorisation}</li>`];
    }

    // Rendu : une section par regime present, dans l'ordre SECTIONS_RECAP,
    // titre + liste a puces (maquette #159).
    const sectionsHtml = SECTIONS_RECAP.filter(
      (s) => (pucesParRegime[s.regime] || []).length > 0
    ).map(
      (s) => `
        <div class="calc-cal__recap-section">
          <p class="calc-cal__recap-titre">${s.titre} :</p>
          <ul class="calc-cal__recap-list">${pucesParRegime[s.regime].join("")}</ul>
        </div>`
    );

    if (sectionsHtml.length === 0) return "";
    return `<div class="calc-cal__recap">${sectionsHtml.join("")}</div>`;
  }

  // Construit la ligne "Periode d'autorisation : du X au Y et du Z au W" a
  // partir des segments de regime "libre" (les jours purement autorises).
  // Fusionne le wrap d'annee (segment finissant au jour 364 + segment
  // commencant au jour 0 = une seule plage continue). "" si aucun jour libre.
  function buildLigneAutorisation(segments) {
    let libres = segments
      .filter((s) => !REGIME_COULEUR_ZONE[s.regime]) // libre/vert uniquement
      .map((s) => ({ du: s.du, au: s.au }));
    if (libres.length === 0) return "";
    // Fusion du wrap : derniere plage finit au dernier jour ET 1ere commence
    // au jour 0 -> elles n'en font qu'une, a cheval sur juillet.
    if (
      libres.length >= 2 &&
      libres[0].du === 0 &&
      libres[libres.length - 1].au === TOTAL_JOURS - 1
    ) {
      const premiere = libres.shift();
      const derniere = libres.pop();
      libres.push({ du: derniere.du, au: premiere.au });
    }
    const morceaux = libres.map(
      (p) => `du ${jourAgricoleToLisible(p.du)} au ${jourAgricoleToLisible(p.au)}`
    );
    let plages;
    if (morceaux.length === 1) {
      plages = morceaux[0];
    } else {
      plages = morceaux.slice(0, -1).join(", ") + " et " + morceaux[morceaux.length - 1];
    }
    // Le régime « Autorisé » est désormais porté par le titre de section
    // (#159) : la puce ne contient que les plages, sans le mot « Autorisé ».
    return plages;
  }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function capitalize(s) {
    return s && s[0].toUpperCase() + s.slice(1);
  }

  // ─── Render principal ──────────────────────────────────────────────────

  // Periodes a considerer pour le rendu courant : celles dont la condition
  // est vraie pour les valeurs courantes du form. Recalculee a chaque render
  // (cf. spec_extension_grammaire_condition §Recalcul a chaque change).
  function periodesActives() {
    return (data.periodes || []).filter((p) =>
      _periodeActive(p, valeurs)
    );
  }

  // Synchronise les valeurs saisies dans l'URL (query params) sans recharger
  // ni scroller la page (history.replaceState). Objectif : URL integralement
  // descriptive et partageable -- on colle l'URL, l'autre voit le meme cas.
  // On n'ecrit un param que pour une valeur JJ/MM reelle (pas le placeholder
  // par defaut non saisi), pour ne pas polluer l'URL avant toute saisie.
  function syncUrl() {
    try {
      const url = new URL(window.location.href);
      for (const inp of inputs) {
        const v = valeurs[inp.id];
        const estSaisi =
          valeursDepuisUrl.has(inp.id) || v !== (inp.placeholder || "");
        if (v && /^\d{2}\/\d{2}$/.test(v) && estSaisi) {
          url.searchParams.set(inp.id, v);
          valeursDepuisUrl.add(inp.id); // une fois saisi, reste dans l'URL
        }
      }
      window.history.replaceState(null, "", url);
    } catch (e) {
      // URL API indispo / contexte sandbox : on n'echoue pas le rendu pour ca.
    }
  }

  function render() {
    const actives = periodesActives();
    const regimeParJour = computeRegimePerDay(actives, valeurs);
    mount.innerHTML = `
      ${renderMiniForm()}
      ${renderCalendrier(regimeParJour, actives)}
      ${renderLegende(regimeParJour)}
      ${renderRecap(regimeParJour, actives)}
    `;
    layoutBornesRows();
    bindInputs();
    bindTooltips();
  }

  // Anti-collision vertical des labels de bornes, par MESURE REELLE du DOM
  // (largeurs de texte connues seulement apres rendu). Greedy gauche->droite :
  // chaque label est place sur la 1ere row ou il ne chevauche aucun label
  // deja place sur cette row (avec un petit jeu horizontal). Le trait ::before
  // s'allonge automatiquement selon la classe --rowN. La hauteur du conteneur
  // .period s'ajuste a la row max utilisee.
  const ROW_STEP_PX = 18; // doit matcher le pas vertical des classes --rowN (CSS)
  const ROW_GAP_PX = 6; // jeu horizontal mini entre 2 labels d'une meme row
  function layoutBornesRows() {
    const container = mount.querySelector(".calendrier-epandage__period");
    if (!container) return;
    const labels = [...container.querySelectorAll(".calendrier-epandage__period-date")];
    if (labels.length === 0) return;

    // Reset : tout en row0, on retire les classes --rowN existantes.
    labels.forEach((el) => {
      el.classList.remove(
        "calendrier-epandage__period-date--row2",
        "calendrier-epandage__period-date--row3",
        "calendrier-epandage__period-date--row4",
      );
    });

    // Mesure les boites apres reset (toutes en row0). On trie par centre x.
    const measured = labels
      .map((el) => {
        const r = el.getBoundingClientRect();
        return { el, left: r.left, right: r.right };
      })
      .sort((a, b) => a.left - b.left);

    // Greedy : pour chaque label, on cherche la row la plus basse (0 = au
    // plus pres de la barre) ou son intervalle [left,right] ne touche pas le
    // dernier intervalle deja pose sur cette row.
    const rowsLastRight = []; // rowsLastRight[row] = right du dernier label pose
    let maxRow = 0;
    for (const m of measured) {
      let row = 0;
      while (
        rowsLastRight[row] !== undefined &&
        m.left < rowsLastRight[row] + ROW_GAP_PX
      ) {
        row += 1;
      }
      rowsLastRight[row] = m.right;
      if (row > maxRow) maxRow = row;
      // row0 = pas de classe ; row>=1 -> classe --row{row+1} (le CSS nomme
      // les rows decalees row2/row3/row4 = +18/+36/+54px).
      if (row >= 1) {
        m.el.classList.add(`calendrier-epandage__period-date--row${row + 1}`);
      }
    }

    // Ajuste la hauteur du conteneur a la row la plus profonde utilisee
    // (label ~16px + maxRow*18px + petite marge) pour ne pas deborder sur
    // la legende, sans reserver d'espace vide quand peu de rows sont prises.
    container.style.height = `${20 + maxRow * ROW_STEP_PX + 8}px`;

    // ── Pixel-snap des traits verticaux (::before) ──────────────────────
    // Le trait fait 1px CSS mais sa position (left:% + translateX(-50%)) tombe
    // a une fraction de pixel physique variable selon le jour -> l'anti-alias
    // du navigateur le rend tantot net (1px), tantot etale (~2px), d'ou
    // l'impression d'epaisseur differente entre semis et destruction.
    // On corrige en nudgeant chaque label d'un sous-pixel pour que le CENTRE
    // de son trait retombe pile sur la grille de pixels physiques (DPR).
    const dpr = window.devicePixelRatio || 1;
    for (const el of labels) {
      el.style.marginLeft = "0px"; // reset avant mesure
    }
    // snapCss(x) : delta (px CSS) pour ramener le point physique x sur
    // l'entier physique le plus proche. Le bord du fond de zone est snappe
    // ainsi pour que le fond colore s'arrete pile sur un pixel entier ; le
    // tic (centre sur la date, peint [centre-0.5, centre+0.5]) snappe sur le
    // MEME entier -> son trait de 1px recouvre exactement la couture du fond.
    // Le tic etant le SEUL trait de frontiere (plus de border-left/right) et
    // dessine par-dessus le fond (couche .period au-dessus des zones), tout
    // ecart sous-pixel du fond passe sous le tic : la ligne reste nette et
    // continue de la barre au label.
    const snapCss = (xCss) => {
      const phys = xCss * dpr;
      return (Math.round(phys) - phys) / dpr; // delta a appliquer
    };

    // ── Pixel-snap du fond des zones ────────────────────────────────────
    // Aligne les bords gauche/droit du fond colore sur la grille de pixels
    // (sinon le fond bave d'1px et le tic ne tombe plus dessus).
    const bar = mount.querySelector(".calendrier-epandage__bar");
    if (bar) {
      const barRect = bar.getBoundingClientRect();
      const zonesEl = [...bar.querySelectorAll(".calendrier-epandage__zone")];
      for (const z of zonesEl) {
        // Sauve les positions % d'origine AVANT de figer en px : au resize on
        // les restaure instantanement pour que le fond suive la barre en direct
        // (le re-snap px crisp arrive juste apres, en debounce). Cf. #177.
        if (z.dataset.pctLeft === undefined) z.dataset.pctLeft = z.style.left;
        if (z.dataset.pctWidth === undefined) z.dataset.pctWidth = z.style.width;
        const r = z.getBoundingClientRect();
        const dLeft = snapCss(r.left);
        const dRight = snapCss(r.right);
        z.style.left = `${(r.left - barRect.left + dLeft).toFixed(3)}px`;
        z.style.width = `${(r.width - dLeft + dRight).toFixed(3)}px`;
      }
    }

    // ── Pixel-snap des TICS (traits verticaux ::before) ─────────────────
    // Chaque tic fait 1px CSS centre sur la date via translateX(-50%). On
    // nudge le label d'un sous-pixel pour que le CENTRE du trait retombe pile
    // sur un pixel physique entier -> trait net (pas d'anti-alias etale).
    for (const el of labels) {
      const r = el.getBoundingClientRect();
      const center = (r.left + r.right) / 2; // x physique du trait (px CSS)
      el.style.marginLeft = `${snapCss(center).toFixed(3)}px`;
    }
  }

  // ─── Tooltip JS instantane ─────────────────────────────────────────────
  // Remplace les `title=` natifs (delai 1.5s, customisation impossible)
  // par un `<div>` flottant qui apparait au mouseenter et suit la position
  // approximative de l'element. Tres simple : pas de logique d'overflow
  // boundary, juste positionne au-dessus de l'element.
  let tooltipEl = null;
  function ensureTooltip() {
    if (tooltipEl) return tooltipEl;
    tooltipEl = document.createElement("div");
    tooltipEl.className = "calc-cal__tooltip";
    document.body.appendChild(tooltipEl);
    return tooltipEl;
  }
  // Delegation events : on ecoute mouseover/mousemove/mouseout sur le
  // root (mount). Avantage vs mouseenter/leave par element : quand le
  // pointeur transite d'un overlay (zone rouge) vers la barre verte
  // parente, on reactive bien le tooltip "Autorisé" -- alors qu'avec
  // mouseenter/leave on aurait juste un mouseleave de la zone rouge
  // sans mouseenter de la barre (car on n'est jamais vraiment sorti
  // de la barre, juste de l'enfant zone).
  function bindTooltips() {
    let lastTarget = null;
    mount.addEventListener("mouseover", (e) => {
      const target = e.target.closest("[data-tooltip]");
      if (!target) return;
      const txt = target.getAttribute("data-tooltip");
      if (!txt) return;
      const tip = ensureTooltip();
      tip.textContent = txt;
      tip.style.opacity = "1";
      lastTarget = target;
      positionTooltip(e);
    });
    mount.addEventListener("mousemove", (e) => {
      const target = e.target.closest("[data-tooltip]");
      if (!target) {
        if (tooltipEl) tooltipEl.style.opacity = "0";
        lastTarget = null;
        return;
      }
      // Si on a change de target, refresh le texte.
      if (target !== lastTarget) {
        const txt = target.getAttribute("data-tooltip");
        if (txt) {
          const tip = ensureTooltip();
          tip.textContent = txt;
          tip.style.opacity = "1";
          lastTarget = target;
        }
      }
      positionTooltip(e);
    });
    mount.addEventListener("mouseleave", () => {
      if (tooltipEl) tooltipEl.style.opacity = "0";
      lastTarget = null;
    });
  }
  // Positionne le tooltip juste au-dessus du curseur (legerement decale
  // a droite pour ne pas masquer le pointeur). On suit la souris pour
  // que l'utilisateur sache quelle zone est decrite, surtout sur les
  // grandes zones (cas "Autorisé" qui occupe toute la barre verte).
  function positionTooltip(e) {
    if (!tooltipEl) return;
    const tipRect = tooltipEl.getBoundingClientRect();
    // Borne a droite : si le tooltip deborderait du viewport, on le decale a
    // gauche du curseur (#159 : tooltips longs pres du bord droit).
    const marge = 8;
    const maxLeft =
      window.scrollX + document.documentElement.clientWidth - tipRect.width - marge;
    let left = e.pageX + 12;
    if (left > maxLeft) left = Math.max(marge, e.pageX - tipRect.width - 12);
    const top = e.pageY - tipRect.height - 10;
    tooltipEl.style.left = `${Math.max(4, left)}px`;
    tooltipEl.style.top = `${Math.max(4, top)}px`;
  }

  // Affiche (ou retire si msg vide) un petit message d'erreur sous le champ
  // date, pour le bornage hors limites (#126). Cree le <p> a la demande.
  function afficherErreurInput(inputEl, msg) {
    const field = inputEl.closest(".calc-cal__field");
    if (!field) return;
    let err = field.querySelector(".calc-cal__field-error");
    if (!msg) {
      if (err) err.remove();
      inputEl.removeAttribute("aria-invalid");
      return;
    }
    if (!err) {
      err = document.createElement("p");
      err.className = "calc-cal__field-error";
      field.appendChild(err);
    }
    err.textContent = msg;
    inputEl.setAttribute("aria-invalid", "true");
  }

  function bindInputs() {
    mount.querySelectorAll("input[data-input-id]").forEach((el) => {
      // Des qu'on focus, la valeur n'est plus celle "par defaut" -- on
      // enleve le grisé pour signaler que l'utilisateur a la main.
      el.addEventListener("focus", () => {
        el.removeAttribute("data-default");
      });
      el.addEventListener("change", () => {
        const id = el.dataset.inputId;
        const inp = inputs.find((x) => x.id === id);
        const val = el.value.trim();
        // Validation minimale : si pas JJ/MM, on garde l'ancienne valeur.
        if (val && !/^\d{2}\/\d{2}$/.test(val)) {
          el.value = valeurs[id];
          afficherErreurInput(el, "");
          return;
        }
        // Bornage (#126) : saisie hors [min,max] refusee + phrase explicative.
        if (val && inp && !dansBornes(inp, val)) {
          afficherErreurInput(el, messageHorsBornes(inp, val));
          el.value = valeurs[id]; // revert a la derniere valeur valide
          return;
        }
        afficherErreurInput(el, "");
        if (val) valeurs[id] = val;
        syncUrl();
        render();
      });
      // Date picker JJ/MM custom (HTML natif ne supporte pas le picker
      // sans annee, cf. spec_rendu_simulateur_calculatrice). Click sur
      // l'input ou son picto -> popup avec 2 selects jour + mois.
      attachJjmmPicker(el);
    });
  }

  // ─── Date picker JJ/MM custom ──────────────────────────────────────────
  // Popup leger : 2 selects (jour, mois) + bouton "OK". Pas de bibliotheque
  // externe ; le composant doit rester self-contained. Le picker se ferme
  // au clic dehors ou au choix d'une date.
  const MOIS_LABELS = [
    ["01", "Janvier"], ["02", "Février"], ["03", "Mars"], ["04", "Avril"],
    ["05", "Mai"], ["06", "Juin"], ["07", "Juillet"], ["08", "Août"],
    ["09", "Septembre"], ["10", "Octobre"], ["11", "Novembre"], ["12", "Décembre"],
  ];
  const JOURS_PAR_MOIS = {
    "01": 31, "02": 29, "03": 31, "04": 30, "05": 31, "06": 30,
    "07": 31, "08": 31, "09": 30, "10": 31, "11": 30, "12": 31,
  };

  let openPicker = null;

  function attachJjmmPicker(inputEl) {
    const field = inputEl.closest(".calc-cal__field");
    if (!field) return;

    const open = () => {
      if (openPicker) openPicker.close();
      const popup = createPickerPopup(inputEl);
      field.appendChild(popup);
      openPicker = {
        el: popup,
        close: () => {
          popup.remove();
          openPicker = null;
          document.removeEventListener("mousedown", outsideHandler, true);
        },
      };
      const outsideHandler = (e) => {
        if (!popup.contains(e.target) && e.target !== inputEl) {
          openPicker.close();
        }
      };
      // Defer l'ajout du listener pour eviter de capturer le click qui
      // a ouvert le popup.
      setTimeout(() => {
        document.addEventListener("mousedown", outsideHandler, true);
      }, 0);
    };

    inputEl.addEventListener("click", open);
    // Picto calendrier (sibling de l'input dans le label) clickable aussi.
    const picto = field.querySelector(".calc-cal__field-icon");
    if (picto) {
      picto.style.pointerEvents = "auto";
      picto.style.cursor = "pointer";
      picto.addEventListener("click", (e) => {
        e.preventDefault();
        inputEl.focus();
        open();
      });
    }
  }

  // Date picker JJ/MM : grille calendrier d'un mois (jour cliquable) +
  // navigation mois precedent / suivant en haut. Pas d'annee : on n'affiche
  // qu'un libelle "Janvier" / "Fevrier" / ... Le mois courant a l'ouverture
  // est celui de l'input (ou janvier par defaut).
  function createPickerPopup(inputEl) {
    const current = parseJjmm(inputEl.value) || { jour: 15, mois: 1 };
    const state = { mois: current.mois, jour: current.jour };
    // Input courant pour le bornage (#126) : les jours hors [min,max] sont
    // desactives dans la grille.
    const inpBorne = inputs.find((x) => x.id === inputEl.dataset.inputId);

    const noteBorne = messageBornePicker(inpBorne);
    const popup = document.createElement("div");
    popup.className = "calc-cal__picker";
    popup.innerHTML = `
      <div class="calc-cal__picker-header">
        <button type="button" class="calc-cal__picker-nav" data-nav="prev" aria-label="Mois précédent">‹</button>
        <span class="calc-cal__picker-mois-label" data-mois-label></span>
        <button type="button" class="calc-cal__picker-nav" data-nav="next" aria-label="Mois suivant">›</button>
      </div>
      <div class="calc-cal__picker-weekdays">
        <span>L</span><span>M</span><span>M</span><span>J</span><span>V</span><span>S</span><span>D</span>
      </div>
      <div class="calc-cal__picker-grid" data-grid></div>
      ${noteBorne ? `<p class="calc-cal__picker-note">${escapeHtml(noteBorne)}</p>` : ""}
    `;

    const moisLabel = popup.querySelector("[data-mois-label]");
    const grid = popup.querySelector("[data-grid]");

    function render() {
      moisLabel.textContent = MOIS_LABELS[state.mois - 1][1];
      const maxJour = JOURS_PAR_MOIS[String(state.mois).padStart(2, "0")] || 31;
      // Pour avoir une grille lisible, on aligne sur le 1er jour de la semaine.
      // On choisit une annee "neutre" (2024, bissextile, 1er janv = lundi) ;
      // le rendu visuel est juste cosmetique, l'utilisateur clique un jour
      // qui s'enregistre en JJ/MM, l'annee ne sert qu'a la grille.
      const RYEAR = 2024;
      const firstDay = new Date(RYEAR, state.mois - 1, 1);
      // Mon-based weekday : 0=Lun, ..., 6=Dim (JS getDay : 0=Dim, ..., 6=Sam).
      const offset = (firstDay.getDay() + 6) % 7;
      const cells = [];
      for (let i = 0; i < offset; i++) {
        cells.push('<button type="button" class="calc-cal__picker-day calc-cal__picker-day--empty" disabled></button>');
      }
      for (let j = 1; j <= maxJour; j++) {
        const isSel = j === state.jour && state.mois === current.mois;
        const jjmm =
          String(j).padStart(2, "0") + "/" + String(state.mois).padStart(2, "0");
        const horsBorne = inpBorne ? !dansBornes(inpBorne, jjmm) : false;
        const cls =
          "calc-cal__picker-day" +
          (isSel ? " calc-cal__picker-day--selected" : "") +
          (horsBorne ? " calc-cal__picker-day--disabled" : "");
        cells.push(
          `<button type="button" class="${cls}" data-jour="${j}"${horsBorne ? " disabled" : ""}>${j}</button>`,
        );
      }
      grid.innerHTML = cells.join("");
      grid.querySelectorAll("[data-jour]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const jour = parseInt(btn.dataset.jour, 10);
          const jj = String(jour).padStart(2, "0");
          const mm = String(state.mois).padStart(2, "0");
          inputEl.value = `${jj}/${mm}`;
          inputEl.removeAttribute("data-default");
          inputEl.dispatchEvent(new Event("change", { bubbles: true }));
          if (openPicker) openPicker.close();
        });
      });
    }

    popup.querySelectorAll(".calc-cal__picker-nav").forEach((btn) => {
      btn.addEventListener("click", () => {
        const dir = btn.dataset.nav === "prev" ? -1 : 1;
        state.mois = ((state.mois - 1 + dir + 12) % 12) + 1;
        render();
      });
    });

    render();
    return popup;
  }

  function parseJjmm(s) {
    const m = /^(\d{2})\/(\d{2})$/.exec(s);
    if (!m) return null;
    return { jour: parseInt(m[1], 10), mois: parseInt(m[2], 10) };
  }

  render();

  // Re-rendu au redimensionnement de la fenetre (#177). Le calendrier fige les
  // zones (fond colore) en PIXELS ABSOLUS pour un pixel-snapping crisp, et cale
  // les traits de date (ticks, en %) dessus. Apres un resize, les zones px
  // restent a leur ancienne largeur pendant que la barre et les ticks (en %)
  // suivent -> fond et traits desalignes tant qu'on ne rafraichit pas.
  //
  // Deux temps pour un rendu qui "colle" sans thrasher le CPU :
  //   1. A CHAQUE event resize : on restaure instantanement les positions %
  //      d'origine des zones (stockees en data-pct*) -> le fond suit la barre
  //      en direct, aligne avec les ticks pendant tout le drag.
  //   2. En debounce (150ms apres l'arret) : re-render complet -> re-snap px
  //      crisp + re-layout des labels de bornes a la nouvelle largeur.
  function restaurerZonesPct() {
    if (!mount) return;
    const zones = mount.querySelectorAll(".calendrier-epandage__zone");
    for (const z of zones) {
      if (z.dataset.pctLeft !== undefined) z.style.left = z.dataset.pctLeft;
      if (z.dataset.pctWidth !== undefined) z.style.width = z.dataset.pctWidth;
    }
  }

  let resizeTimer = null;
  let lastWidth = window.innerWidth;
  window.addEventListener("resize", () => {
    // Ignore les resize purement verticaux (clavier mobile, barre d'URL qui
    // se retracte) : seule la largeur impacte la geometrie du calendrier.
    if (window.innerWidth === lastWidth) return;
    lastWidth = window.innerWidth;
    // 1. Suivi live : le fond repasse en % -> reste cale sur les ticks.
    restaurerZonesPct();
    // 2. Re-snap crisp une fois le drag termine.
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(render, 150);
  });
})();
