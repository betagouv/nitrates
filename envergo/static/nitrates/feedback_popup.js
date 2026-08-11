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
    var timerInactivite = null;

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
      detacherDeclencheurs();
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
