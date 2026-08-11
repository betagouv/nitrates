/* #284 — Popup de feedback fin de simulation.
 *
 * Déclenchement « au moment le moins gênant » :
 *   - une seule fois par visiteur (flag localStorage : envoyé OU esquivé) ;
 *   - seulement sur la page résultat (le fragment #nitrates-feedback n'est rendu
 *     que là) et après un délai minimal (on laisse lire le résultat) ;
 *   - au bout de INACTIVITE_MS d'inactivité (pas de scroll / clic / clavier),
 *     OU quand l'utilisateur s'apprête à quitter (souris qui sort vers le haut,
 *     onglet qui passe en arrière-plan) — pour attraper avant la fermeture.
 *   - on NE pop PAS pendant que l'utilisateur scrolle/lit : tout scroll ou
 *     interaction réarme le timer d'inactivité.
 *
 * Envoi : POST JSON /api/retour/ avec token CSRF. Succès -> écran de
 * remerciement + animation « vers contents » (feedback_vers.js).
 */
(function () {
  "use strict";

  var STORAGE_KEY = "nitrates_feedback_v1"; // présence = déjà traité (envoyé/esquivé)
  var INACTIVITE_MS = 30000; // 30 s d'inactivité
  var DELAI_MIN_MS = 8000; // on laisse au moins 8 s pour lire avant tout pop

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

  function getCookie(name) {
    var m = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return m ? decodeURIComponent(m.pop()) : "";
  }

  function init() {
    var root = document.getElementById("nitrates-feedback");
    if (!root) return; // pas sur une page résultat
    if (dejaTraite()) return; // déjà envoyé ou esquivé une fois

    var dialogForm = root.querySelector("[data-feedback-form]");
    var dialogMerci = root.querySelector("[data-feedback-merci]");
    var reward = root.querySelector("[data-feedback-reward]");
    var erreur = root.querySelector("[data-feedback-erreur]");
    var submitBtn = root.querySelector("[data-feedback-submit]");
    var commentaire = root.querySelector("#nitrates-feedback-commentaire");
    var email = root.querySelector("#nitrates-feedback-email");
    var consent = root.querySelector("#nitrates-feedback-consent");
    var notesBtns = Array.prototype.slice.call(
      root.querySelectorAll("[data-feedback-note]")
    );

    var noteChoisie = null;
    var ouvert = false;
    var traite = false;
    var timerInactivite = null;

    // ── Sélection de la note ────────────────────────────────────────────────
    notesBtns.forEach(function (btn) {
      btn.addEventListener("click", function () {
        noteChoisie = parseInt(btn.getAttribute("data-feedback-note"), 10);
        notesBtns.forEach(function (b) {
          b.setAttribute("aria-checked", b === btn ? "true" : "false");
        });
        // Le bouton Envoyer s'active dès qu'une note est choisie (le reste est
        // facultatif). L'email est demandé quelle que soit la note.
        submitBtn.disabled = false;
      });
    });

    // ── Ouverture / fermeture ───────────────────────────────────────────────
    function ouvrir() {
      if (ouvert || traite || dejaTraite()) return;
      ouvert = true;
      root.hidden = false;
      // focus sur la 1re note pour l'accessibilité clavier
      if (notesBtns[0]) notesBtns[0].focus();
      detacherDeclencheurs();
    }

    function esquiver() {
      // Fermeture sans envoi = esquive -> on ne redemande plus jamais.
      if (traite) return;
      traite = true;
      marquerTraite("dismissed");
      root.hidden = true;
    }

    root.querySelectorAll("[data-feedback-dismiss]").forEach(function (el) {
      el.addEventListener("click", esquiver);
    });
    document.addEventListener("keydown", function (e) {
      if (ouvert && e.key === "Escape") esquiver();
    });

    // ── Envoi ───────────────────────────────────────────────────────────────
    submitBtn.addEventListener("click", function () {
      if (noteChoisie === null) return;
      submitBtn.disabled = true;
      erreur.hidden = true;

      var emailVal = (email.value || "").trim();
      var payload = {
        type: "feedback",
        note: noteChoisie,
        commentaire: (commentaire.value || "").trim(),
        region_code: root.getAttribute("data-region-code") || "",
        // Métadonnées ANONYMES uniquement (aucune donnée de localisation).
        contexte: { source: "popup_resultat" },
      };
      // Email seulement si consentement coché (le back re-vérifie de toute façon).
      if (emailVal && consent.checked) {
        payload.email = emailVal;
        payload.consentement_email = true;
      }

      fetch("/api/retour/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCookie("csrftoken"),
        },
        body: JSON.stringify(payload),
      })
        .then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then(function () {
          traite = true;
          marquerTraite("sent");
          // Écran de remerciement + animation reward.
          dialogForm.hidden = true;
          dialogMerci.hidden = false;
          if (window.nitratesVersReward && reward) {
            window.nitratesVersReward(reward, { nombre: 5 });
          }
          // Fermeture automatique après avoir laissé savourer l'animation.
          window.setTimeout(function () {
            root.hidden = true;
          }, 4000);
        })
        .catch(function () {
          erreur.hidden = false;
          submitBtn.disabled = false;
        });
    });

    // ── Déclencheurs d'ouverture ────────────────────────────────────────────
    // 1) inactivité : réarmé à chaque interaction (scroll/clic/clavier/souris).
    function armerInactivite() {
      if (timerInactivite) window.clearTimeout(timerInactivite);
      timerInactivite = window.setTimeout(ouvrir, INACTIVITE_MS);
    }
    var evtsActivite = ["scroll", "mousemove", "keydown", "click", "touchstart"];
    function onActivite() {
      armerInactivite();
    }

    // 2) intention de quitter : souris qui sort par le haut (vers les onglets),
    //    ou onglet masqué (l'utilisateur part) -> on tente le pop avant la sortie.
    function onSortieHaut(e) {
      if (e.clientY <= 0) ouvrir();
    }
    function onVisibilite() {
      if (document.visibilityState === "hidden") {
        // On ne peut pas ouvrir une modale sur un onglet masqué ; on la prépare
        // pour qu'elle soit visible au retour (si pas déjà traitée).
        ouvrir();
      }
    }

    function attacherDeclencheurs() {
      evtsActivite.forEach(function (ev) {
        window.addEventListener(ev, onActivite, { passive: true });
      });
      document.addEventListener("mouseout", onSortieHaut);
      document.addEventListener("visibilitychange", onVisibilite);
      armerInactivite();
    }
    function detacherDeclencheurs() {
      evtsActivite.forEach(function (ev) {
        window.removeEventListener(ev, onActivite);
      });
      document.removeEventListener("mouseout", onSortieHaut);
      document.removeEventListener("visibilitychange", onVisibilite);
      if (timerInactivite) window.clearTimeout(timerInactivite);
    }

    // On laisse un délai minimal (lecture du résultat) avant d'armer quoi que
    // ce soit, pour ne jamais pop pile au chargement.
    window.setTimeout(attacherDeclencheurs, DELAI_MIN_MS);
  }

  // Robuste au chargement `defer` : si le DOM est déjà prêt (DOMContentLoaded
  // passé), on initialise tout de suite ; sinon on attend l'event.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
