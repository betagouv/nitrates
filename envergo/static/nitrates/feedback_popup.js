/* #284 — Popup de feedback fin de simulation.
 *
 * Déclenchement (décision Max 2026-08-12) :
 *   - une seule fois par visiteur (flag localStorage : traité -> plus jamais) ;
 *   - seulement sur la page résultat (le fragment #nitrates-feedback n'y est
 *     rendu que là) ;
 *   - « inaction » = pas de CLIC (le scroll et les mouvements de souris ne
 *     comptent PAS : on peut lire/scroller, ça reste de l'inaction). Le compteur
 *     démarre à l'affichage du résultat et se remet à zéro UNIQUEMENT sur un
 *     clic. Après DELAI_INACTION_MS sans clic -> on ouvre la popup ;
 *   - le compteur tourne en temps réel : un changement d'onglet ne le remet pas
 *     à zéro. Si l'échéance tombe onglet masqué, on ouvre au retour (jamais dans
 *     le dos de l'utilisateur).
 *
 * Envoi : POST JSON /api/retour/ avec token CSRF. Succès -> écran de
 * remerciement + animation « vers contents » (feedback_vers.js).
 */
(function () {
  "use strict";

  var STORAGE_KEY = "nitrates_feedback_v1"; // présence = déjà traité
  var DELAI_INACTION_MS = 15000; // 15 s sans clic après l'affichage du résultat

  function dejaTraite() {
    try {
      return !!window.localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return false; // localStorage indispo -> on tolère (au pire on redemande)
    }
  }

  function marquerTraite(etat) {
    try {
      window.localStorage.setItem(STORAGE_KEY, etat || "done");
    } catch (e) {
      /* ignore */
    }
  }

  // Récupère le token CSRF. Le cookie `csrftoken` est posé en HttpOnly
  // (durcissement sécurité #265) -> JS ne peut PAS le lire via document.cookie.
  // On lit donc le token depuis le champ caché rendu par {% csrf_token %} dans
  // la page (méthode Django recommandée quand CSRF_COOKIE_HTTPONLY=True).
  // Fallback cookie au cas où (si un jour le HttpOnly saute).
  function getCsrfToken() {
    var input = document.querySelector("input[name=csrfmiddlewaretoken]");
    if (input && input.value) return input.value;
    var m = document.cookie.match("(^|;)\\s*csrftoken\\s*=\\s*([^;]+)");
    return m ? decodeURIComponent(m.pop()) : "";
  }

  function init() {
    var root = document.getElementById("nitrates-feedback");
    if (!root) return; // pas sur une page résultat
    if (dejaTraite()) return; // déjà envoyé ou esquivé une fois

    var voletNote = root.querySelector("[data-feedback-volet-note]");
    var voletEmail = root.querySelector("[data-feedback-volet-email]");
    var voletMerci = root.querySelector("[data-feedback-merci]");
    var reward = root.querySelector("[data-feedback-reward]");
    var erreurNote = root.querySelector("[data-feedback-erreur-note]");
    var erreurEmail = root.querySelector("[data-feedback-erreur-email]");
    var submitNote = root.querySelector("[data-feedback-submit-note]");
    var submitEmail = root.querySelector("[data-feedback-submit-email]");
    var commentaire = root.querySelector("#nitrates-feedback-commentaire");
    var email = root.querySelector("#nitrates-feedback-email");
    var consent = root.querySelector("#nitrates-feedback-consent");
    var stars = Array.prototype.slice.call(
      root.querySelectorAll("[data-feedback-note]")
    );

    var noteChoisie = null;
    var retourId = null; // id de l'entrée feedback créée au volet 1
    var ouvert = false;
    var traite = false;

    // ── Étoiles : allumer jusqu'à l'indice n (0-based) ──────────────────────
    function allumerJusqua(idx) {
      stars.forEach(function (s, i) {
        s.classList.toggle("is-on", i <= idx);
      });
    }
    function refletSelection() {
      // Réaffiche l'état sélectionné (après un mouseleave).
      allumerJusqua(noteChoisie === null ? -1 : noteChoisie - 1);
    }
    stars.forEach(function (star, i) {
      star.addEventListener("mouseenter", function () {
        allumerJusqua(i);
      });
      star.addEventListener("click", function () {
        noteChoisie = parseInt(star.getAttribute("data-feedback-note"), 10);
        stars.forEach(function (s, j) {
          s.setAttribute("aria-checked", j === i ? "true" : "false");
        });
        refletSelection();
        submitNote.disabled = false; // envoi possible dès qu'une note est mise
      });
    });
    root
      .querySelector(".nitrates-feedback__stars")
      .addEventListener("mouseleave", refletSelection);

    // ── Ouverture / fermeture ───────────────────────────────────────────────
    function ouvrir() {
      if (ouvert || traite || dejaTraite()) return;
      ouvert = true;
      root.hidden = false;
      if (stars[0]) stars[0].focus();
    }

    function terminer() {
      // Fin du parcours (email envoyé ou volets fermés) -> reward + fermeture.
      traite = true;
      marquerTraite("done");
      voletNote.hidden = true;
      voletEmail.hidden = true;
      voletMerci.hidden = false;
      if (window.nitratesVersReward && reward) {
        window.nitratesVersReward(reward, { nombre: 5 });
      }
      window.setTimeout(function () {
        root.hidden = true;
      }, 4000);
    }

    function esquiver() {
      // Fermeture -> on ne redemande plus jamais. Si une note a été saisie mais
      // pas encore envoyée, on l'envoie quand même (best-effort, sans bloquer).
      if (traite) return;
      traite = true;
      marquerTraite("dismissed");
      if (noteChoisie !== null && retourId === null) {
        envoyerNote(true); // fire-and-forget
      }
      root.hidden = true;
    }

    root.querySelectorAll("[data-feedback-dismiss]").forEach(function (el) {
      el.addEventListener("click", esquiver);
    });
    document.addEventListener("keydown", function (e) {
      if (ouvert && e.key === "Escape") esquiver();
    });

    // ── Volet 1 : envoi de la note + commentaire (SANS email) ───────────────
    function envoyerNote(silencieux) {
      if (noteChoisie === null) return Promise.resolve();
      submitNote.disabled = true;
      erreurNote.hidden = true;
      var payload = {
        type: "feedback",
        note: noteChoisie,
        commentaire: (commentaire.value || "").trim(),
        region_code: root.getAttribute("data-region-code") || "",
        contexte: { source: "popup_resultat" },
      };
      return fetch("/api/retour/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify(payload),
      })
        .then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then(function (data) {
          retourId = data.id;
          if (!silencieux) {
            // On révèle le volet email (facultatif). L'utilisateur peut fermer
            // sans le remplir : son avis est déjà enregistré.
            voletNote.hidden = true;
            voletEmail.hidden = false;
            email.focus();
          }
        })
        .catch(function () {
          if (!silencieux) {
            erreurNote.hidden = false;
            submitNote.disabled = false;
          }
        });
    }
    submitNote.addEventListener("click", function () {
      envoyerNote(false);
    });

    // ── Volet 2 : email optionnel, attaché à l'entrée du volet 1 ────────────
    function majBoutonEmail() {
      submitEmail.disabled = !(
        (email.value || "").trim() && consent.checked
      );
    }
    email.addEventListener("input", majBoutonEmail);
    consent.addEventListener("change", majBoutonEmail);

    submitEmail.addEventListener("click", function () {
      var emailVal = (email.value || "").trim();
      if (!emailVal || !consent.checked || retourId === null) return;
      submitEmail.disabled = true;
      erreurEmail.hidden = true;
      fetch("/api/retour/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify({
          retour_id: retourId,
          email: emailVal,
          consentement_email: true,
        }),
      })
        .then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then(function () {
          terminer();
        })
        .catch(function () {
          erreurEmail.hidden = false;
          submitEmail.disabled = false;
        });
    });

    // ── Déclenchement : échéance = dernier clic + DELAI_INACTION_MS ─────────
    // « Inaction » = pas de clic. Le scroll et les mouvements de souris ne
    // comptent PAS (on peut lire/scroller sans réarmer). Seul un CLIC recale
    // l'échéance. Le compteur tourne en temps réel (horloge) : un changement
    // d'onglet ne le remet pas à zéro. On poll chaque seconde ; dès l'échéance
    // atteinte ET onglet visible -> ouverture (sinon au retour sur l'onglet).
    var echeance = Date.now() + DELAI_INACTION_MS;
    var pollTimer = null;
    var nbClics = 0;

    // Tout clic RÉARME le compteur (sauf une fois la popup ouverte : les clics
    // dans la popup ne doivent pas repousser une échéance déjà consommée).
    document.addEventListener(
      "click",
      function () {
        if (traite || ouvert) return;
        nbClics += 1;
        echeance = Date.now() + DELAI_INACTION_MS;
      },
      true
    );

    function debug(restantMs, etat) {
      if (!DEBUG) return;
      majDebugPanel({
        restant: Math.max(0, Math.ceil(restantMs / 1000)),
        visible: document.visibilityState,
        clics: nbClics,
        traite: traite,
        etat: etat,
      });
    }

    function tick() {
      var restant = echeance - Date.now();
      if (traite || dejaTraite()) {
        debug(restant, "déjà traité — stop");
        window.clearInterval(pollTimer);
        return;
      }
      if (restant <= 0) {
        if (document.visibilityState === "visible") {
          debug(0, "échéance atteinte → OUVERTURE");
          window.clearInterval(pollTimer);
          ouvrir();
        } else {
          // échéance atteinte mais onglet masqué : on attend le retour.
          debug(0, "échéance atteinte, onglet masqué → attente retour");
        }
      } else {
        debug(restant, "inaction (compte à rebours)");
      }
    }

    // Au retour sur l'onglet, si l'échéance est déjà passée, on ouvre tout de
    // suite (le compteur a continué de tourner en arrière-plan).
    document.addEventListener("visibilitychange", function () {
      if (
        document.visibilityState === "visible" &&
        !traite &&
        !dejaTraite() &&
        Date.now() >= echeance
      ) {
        debug(0, "retour onglet, échéance passée → OUVERTURE");
        window.clearInterval(pollTimer);
        ouvrir();
      }
    });

    pollTimer = window.setInterval(tick, 1000);
    tick();
  }

  // ── Mini panneau de debug (TEMPORAIRE, retiré en fin de dev) ──────────────
  // Activé si DEBUG=true (constante ci-dessous). Affiche à droite, hors flux,
  // le compteur restant + l'état des triggers. À SUPPRIMER avec le reste.
  var DEBUG = true;
  var debugPanel = null;
  function majDebugPanel(info) {
    if (!debugPanel) {
      debugPanel = document.createElement("div");
      debugPanel.id = "nitrates-feedback-debug";
      debugPanel.style.cssText =
        "position:fixed;top:80px;right:8px;z-index:3000;" +
        "background:#161616;color:#0f0;font:12px/1.5 monospace;" +
        "padding:8px 10px;border-radius:6px;max-width:230px;" +
        "box-shadow:0 2px 8px rgba(0,0,0,.4);pointer-events:none;opacity:.92";
      document.body.appendChild(debugPanel);
    }
    debugPanel.innerHTML =
      "<b>DEBUG feedback #284</b><br>" +
      "règle : 15 s sans clic<br>" +
      "restant : <b>" +
      info.restant +
      " s</b><br>" +
      "clics (réarme) : " +
      info.clics +
      "<br>" +
      "onglet : " +
      info.visible +
      "<br>" +
      "traité : " +
      info.traite +
      "<br>" +
      "état : " +
      info.etat;
  }

  // Robuste au chargement `defer` : si le DOM est déjà prêt (DOMContentLoaded
  // passé), on initialise tout de suite ; sinon on attend l'event.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
