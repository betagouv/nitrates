/* #284 / #435 — Encart de feedback fin de simulation.
 *
 * Déclenchement (retour utilisateur #435 : le modal à 15 s arrivait trop tôt,
 * en pleine lecture du résultat) :
 *   - une seule fois par visiteur (flag localStorage : traité -> plus jamais) ;
 *   - seulement sur la page résultat (le fragment #nitrates-feedback n'y est
 *     rendu que là) ;
 *   - PRIORITÉ 1 : intention de sortie au curseur (desktop). Le curseur sort
 *     du viewport par le HAUT (direction barre d'onglets / croix) -> on ouvre
 *     juste avant le départ. Armé seulement après DELAI_ARMEMENT_MS pour
 *     éviter le faux positif du curseur encore en haut à l'arrivée sur la
 *     page. Nos utilisateurs ferment à la souris, les raccourcis clavier sont
 *     marginaux : cette détection couvre l'essentiel des cas ;
 *   - FALLBACK : inactivité prolongée (couvre le mobile, sans curseur).
 *     « Inaction » = pas de CLIC (le scroll et les mouvements de souris ne
 *     comptent PAS : on peut lire/scroller, ça reste de l'inaction). Seul un
 *     clic recale l'échéance. Le compteur tourne en temps réel : un changement
 *     d'onglet ne le remet pas à zéro ; si l'échéance tombe onglet masqué, on
 *     ouvre au retour (jamais dans le dos de l'utilisateur).
 *
 * L'encart est NON MODAL (aria-live sur le fragment) : pas de vol de focus à
 * l'ouverture, l'utilisateur peut continuer à lire/naviguer.
 *
 * Envoi : POST JSON /api/retour/ avec token CSRF. Succès -> écran de
 * remerciement + animation « vers contents » (feedback_vers.js).
 */
(function () {
  "use strict";

  var STORAGE_KEY = "nitrates_feedback_v1"; // présence = déjà traité
  var DELAI_INACTION_MS = 45000; // fallback : 45 s sans clic sur le résultat
  var DELAI_ARMEMENT_MS = 5000; // temps de lecture mini avant d'armer l'exit intent

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
    // ── Anti-collision (#435) : cartes de définition + drawer conditions ────
    // L'encart partage le bord droit avec la carte de définition (.def-carte)
    // et le drawer conditions (qui occupe la droite, tout l'écran en mobile).
    // Règles : on n'OUVRE pas l'encart tant que l'un des deux est affiché, et
    // s'ils s'ouvrent APRÈS lui, on l'efface temporairement (classe CSS) puis
    // on le réaffiche à leur fermeture. Surveillance par poll 1 s (même
    // mécanique que le déclenchement : pas d'API d'événement côté glossaire).
    function encombrementActif() {
      return (
        document.body.classList.contains("drawer-open") ||
        !!document.querySelector(".def-carte--ouverte")
      );
    }

    var ouvertureEnAttente = false;

    window.setInterval(function () {
      if (traite) return;
      if (ouvert) {
        root.classList.toggle("nitrates-feedback--efface", encombrementActif());
      } else if (ouvertureEnAttente && !encombrementActif()) {
        ouvertureEnAttente = false;
        ouvrir();
      }
    }, 1000);

    // Encart non modal : on ne déplace PAS le focus à l'ouverture (l'utilisateur
    // est peut-être en train de lire ; aria-live annonce l'encart aux lecteurs
    // d'écran).
    function ouvrir() {
      if (ouvert || traite || dejaTraite()) return;
      if (encombrementActif()) {
        // Définition ou drawer à l'écran : on attend leur fermeture.
        ouvertureEnAttente = true;
        return;
      }
      ouvert = true;
      root.hidden = false;
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
      // Pas d'esquive si l'encart est effacé (invisible derrière une carte de
      // définition ou le drawer) : l'Échap vise alors CES éléments, pas nous.
      if (
        ouvert &&
        e.key === "Escape" &&
        !root.classList.contains("nitrates-feedback--efface")
      ) {
        esquiver();
      }
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

    // ── Déclenchement 1 : intention de sortie au curseur (desktop) ──────────
    // `mouseout` sur document avec relatedTarget null = le curseur a quitté le
    // viewport ; clientY <= 0 = par le HAUT (barre d'onglets, croix, barre
    // d'URL). Armé après DELAI_ARMEMENT_MS pour laisser le temps d'entrer dans
    // la lecture (sinon faux positif : curseur encore en haut après le clic
    // de soumission du formulaire).
    var armementExit = Date.now() + DELAI_ARMEMENT_MS;
    document.addEventListener("mouseout", function (e) {
      if (traite || ouvert || dejaTraite()) return;
      if (Date.now() < armementExit) return;
      if (e.relatedTarget !== null) return; // simple passage entre éléments
      if (e.clientY > 0) return; // sortie par un bord latéral/bas : pas un départ
      ouvrir();
    });

    // ── Déclenchement 2 (fallback) : dernier clic + DELAI_INACTION_MS ───────
    // « Inaction » = pas de clic. Le scroll et les mouvements de souris ne
    // comptent PAS (on peut lire/scroller sans réarmer). Seul un CLIC recale
    // l'échéance. Le compteur tourne en temps réel (horloge) : un changement
    // d'onglet ne le remet pas à zéro. On poll chaque seconde ; dès l'échéance
    // atteinte ET onglet visible -> ouverture (sinon au retour sur l'onglet).
    var echeance = Date.now() + DELAI_INACTION_MS;
    var pollTimer = null;

    // Tout clic RÉARME le compteur (sauf une fois la popup ouverte : les clics
    // dans la popup ne doivent pas repousser une échéance déjà consommée).
    document.addEventListener(
      "click",
      function () {
        if (traite || ouvert) return;
        echeance = Date.now() + DELAI_INACTION_MS;
      },
      true
    );

    function tick() {
      var restant = echeance - Date.now();
      if (traite || dejaTraite()) {
        window.clearInterval(pollTimer);
        return;
      }
      // Échéance atteinte + onglet visible -> ouverture. Onglet masqué : on
      // attend le retour (cf. visibilitychange ci-dessous).
      if (restant <= 0 && document.visibilityState === "visible") {
        window.clearInterval(pollTimer);
        ouvrir();
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
        window.clearInterval(pollTimer);
        ouvrir();
      }
    });

    pollTimer = window.setInterval(tick, 1000);
    tick();
  }

  // Robuste au chargement `defer` : si le DOM est déjà prêt (DOMContentLoaded
  // passé), on initialise tout de suite ; sinon on attend l'event.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
