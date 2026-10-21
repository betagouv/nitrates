/* #285 / #518 — Signalement de bug (modale ouverte depuis le pied de page).
 *
 * Rôle :
 *   1. Dès le chargement, installer des capteurs LÉGERS qui gardent en mémoire
 *      (buffers circulaires bornés) les derniers logs console, les dernières
 *      requêtes réseau (fetch + XHR) et les erreurs JS non capturées. Objectif :
 *      qu'au moment où l'utilisateur signale un bug, on ait déjà le contexte
 *      technique pour reproduire.
 *   2. Gérer la modale (envoi du commentaire, remerciement).
 *   3. À l'envoi, POST JSON /api/retour/ (type "bug") avec, dans `contexte`, le
 *      dump technique + les infos page (URL, user-agent, écran).
 *
 * Aucune donnée de simulation ni parcellaire n'est jointe : uniquement le texte
 * de l'utilisateur et un contexte technique anonyme.
 *
 * NB : ce script est chargé en `defer` sur toutes les pages nitrates. Les
 * capteurs s'installent donc au parse du script (après le HTML), ce qui suffit
 * largement pour attraper les erreurs/logs de l'interaction utilisateur.
 */
(function () {
  "use strict";

  var MAX_CONSOLE = 100; // dernières entrées console gardées
  var MAX_NETWORK = 40; // dernières requêtes réseau gardées
  var MAX_MSG_LEN = 2000; // troncature d'un message console
  var MAX_URL_LEN = 500;

  // ── Buffers circulaires ───────────────────────────────────────────────────
  var consoleBuf = [];
  var networkBuf = [];

  function pushBounded(buf, entry, max) {
    buf.push(entry);
    if (buf.length > max) buf.shift();
  }

  function trunc(str, max) {
    str = String(str);
    return str.length > max ? str.slice(0, max) + "…[tronqué]" : str;
  }

  function argsToMessage(args) {
    try {
      return Array.prototype.map
        .call(args, function (a) {
          if (a instanceof Error) return a.stack || a.message || String(a);
          if (typeof a === "object") {
            try {
              return JSON.stringify(a);
            } catch (e) {
              return String(a);
            }
          }
          return String(a);
        })
        .join(" ");
    } catch (e) {
      return "[message illisible]";
    }
  }

  // ── Capteur console ───────────────────────────────────────────────────────
  function installConsoleCapture() {
    var levels = ["log", "info", "warn", "error", "debug"];
    levels.forEach(function (level) {
      var original = console[level];
      if (typeof original !== "function") return;
      console[level] = function () {
        try {
          pushBounded(
            consoleBuf,
            {
              level: level,
              message: trunc(argsToMessage(arguments), MAX_MSG_LEN),
              t: new Date().toISOString(),
            },
            MAX_CONSOLE
          );
        } catch (e) {
          /* ne jamais casser le vrai console */
        }
        return original.apply(console, arguments);
      };
    });
  }

  // ── Capteur erreurs non gérées ────────────────────────────────────────────
  function installErrorCapture() {
    window.addEventListener("error", function (e) {
      var msg = e.message || "erreur";
      if (e.filename) msg += " (" + e.filename + ":" + e.lineno + ")";
      pushBounded(
        consoleBuf,
        { level: "error", message: trunc(msg, MAX_MSG_LEN), t: new Date().toISOString() },
        MAX_CONSOLE
      );
    });
    window.addEventListener("unhandledrejection", function (e) {
      var reason = e && e.reason;
      var msg =
        reason instanceof Error ? reason.stack || reason.message : String(reason);
      pushBounded(
        consoleBuf,
        {
          level: "error",
          message: "Promesse rejetée : " + trunc(msg, MAX_MSG_LEN),
          t: new Date().toISOString(),
        },
        MAX_CONSOLE
      );
    });
  }

  // ── Capteur réseau (fetch + XHR) ──────────────────────────────────────────
  function logNetwork(method, url, status, extra) {
    pushBounded(
      networkBuf,
      {
        method: (method || "GET").toUpperCase(),
        url: trunc(url || "", MAX_URL_LEN),
        status: status,
        extra: extra || "",
        t: new Date().toISOString(),
      },
      MAX_NETWORK
    );
  }

  function installNetworkCapture() {
    // fetch
    if (typeof window.fetch === "function") {
      var origFetch = window.fetch;
      window.fetch = function (input, init) {
        var url = typeof input === "string" ? input : input && input.url;
        var method = (init && init.method) || (input && input.method) || "GET";
        return origFetch.apply(this, arguments).then(
          function (resp) {
            logNetwork(method, url, resp.status);
            return resp;
          },
          function (err) {
            logNetwork(method, url, "ERR", String(err));
            throw err;
          }
        );
      };
    }

    // XMLHttpRequest
    if (window.XMLHttpRequest) {
      var origOpen = XMLHttpRequest.prototype.open;
      var origSend = XMLHttpRequest.prototype.send;
      XMLHttpRequest.prototype.open = function (method, url) {
        this.__bugMethod = method;
        this.__bugUrl = url;
        return origOpen.apply(this, arguments);
      };
      XMLHttpRequest.prototype.send = function () {
        var xhr = this;
        xhr.addEventListener("loadend", function () {
          logNetwork(xhr.__bugMethod, xhr.__bugUrl, xhr.status || "ERR");
        });
        return origSend.apply(this, arguments);
      };
    }
  }

  // ── CSRF ──────────────────────────────────────────────────────────────────
  // Priorité à la variable globale exposée par multisite_base.html
  // (var CSRF_TOKEN = '{{ csrf_token }}'), disponible sur toutes les pages.
  // Fallback : champ caché {% csrf_token %} si présent (pages avec form).
  function getCsrfToken() {
    if (window.CSRF_TOKEN) return window.CSRF_TOKEN;
    var input = document.querySelector("input[name=csrfmiddlewaretoken]");
    return input && input.value ? input.value : "";
  }

  // ── Contexte technique joint au signalement ───────────────────────────────
  function collecterContexte() {
    return {
      url: trunc(window.location.href, MAX_URL_LEN),
      titre_page: trunc(document.title || "", 300),
      user_agent: trunc(navigator.userAgent || "", 500),
      viewport:
        window.innerWidth +
        "×" +
        window.innerHeight +
        " (dpr " +
        (window.devicePixelRatio || 1) +
        ")",
      referrer: trunc(document.referrer || "", MAX_URL_LEN),
      horodatage: new Date().toISOString(),
      console: consoleBuf.slice(),
      network: networkBuf.slice(),
    };
  }

  // ── Modale « Signaler un bug, une erreur » (#518) ─────────────────────────
  // Ouverture / fermeture / focus gérés par la modale DSFR (lien du pied de
  // page, boutons aria-controls). Ici : envoi et bascule vers le remerciement.
  function init() {
    var modale = document.getElementById("nitrates-bug-modal");
    if (!modale) return;
    var racine = document.getElementById("nitrates-retours");

    var commentaire = modale.querySelector("#nitrates-bug-commentaire");
    var submit = modale.querySelector("[data-bug-submit]");
    var erreur = modale.querySelector("[data-bug-erreur]");
    var voletsForm = modale.querySelectorAll("[data-bug-volet-form]");
    var voletsMerci = modale.querySelectorAll("[data-bug-volet-merci]");
    var envoiEnCours = false;

    function afficher(liste, visible) {
      Array.prototype.forEach.call(liste, function (el) {
        el.hidden = !visible;
      });
    }

    function majEtatSubmit() {
      submit.disabled = !commentaire.value.trim() || envoiEnCours;
    }

    // A chaque fermeture, on remet le formulaire pour un prochain signalement.
    modale.addEventListener("dsfr.conceal", function () {
      if (voletsMerci[0] && !voletsMerci[0].hidden) {
        commentaire.value = "";
        afficher(voletsMerci, false);
        afficher(voletsForm, true);
      }
      if (erreur) erreur.hidden = true;
      majEtatSubmit();
    });
    modale.addEventListener("dsfr.disclose", function () {
      window.setTimeout(function () {
        if (!commentaire.closest("[hidden]")) commentaire.focus();
      }, 50);
    });

    commentaire.addEventListener("input", majEtatSubmit);
    majEtatSubmit();

    submit.addEventListener("click", function () {
      if (envoiEnCours) return;
      var texte = commentaire.value.trim();
      if (!texte) return;

      envoiEnCours = true;
      majEtatSubmit();
      if (erreur) erreur.hidden = true;

      var contexte = collecterContexte();
      // Le type "bug" cote serveur couvre bug et suggestion : on garde le
      // sous-type pour le tri en admin. Les suggestions passent desormais par
      // l'encart d'avis (feedback), ce formulaire est donc toujours un bug.
      contexte.sous_type = "bug";

      fetch("/api/retour/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify({
          type: "bug",
          commentaire: texte,
          region_code: (racine && racine.getAttribute("data-region-code")) || "",
          contexte: contexte,
        }),
      })
        .then(function (resp) {
          if (!resp.ok) throw new Error("HTTP " + resp.status);
          return resp.json();
        })
        .then(function () {
          afficher(voletsForm, false);
          afficher(voletsMerci, true);
        })
        .catch(function () {
          if (erreur) erreur.hidden = false;
        })
        .finally(function () {
          envoiEnCours = false;
          majEtatSubmit();
        });
    });
  }

  // Capteurs installés immédiatement (au parse du script defer).
  installConsoleCapture();
  installErrorCapture();
  installNetworkCapture();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
