/* #284 / #435 / #518 — Encart « Une suggestion, un avis ? ».
 *
 * L'encart (note + commentaire, puis proposition bêta-testeur) est présent sur
 * toutes les pages (fragment _retours.html) :
 *   - ouverture MANUELLE par le bouton flottant « Une suggestion, un avis ? »,
 *     à tout moment, autant de fois que voulu (on peut redonner son avis) ;
 *   - ouverture AUTOMATIQUE une seule fois par visiteur, à la fin de la
 *     première simulation (page résultat, marqueur [data-nitrates-fin-
 *     simulation]). S'il la ferme, on ne redemande plus (flag localStorage).
 *     Déclencheurs repris de #435 : intention de sortie au curseur (desktop),
 *     sinon inactivité prolongée (pas de clic), jamais onglet masqué.
 *   - la proposition « devenir bêta-testeur » n'est faite qu'une fois par
 *     session (sessionStorage), et plus du tout une fois l'email laissé.
 *
 * L'encart est NON MODAL (aria-live) : pas de vol de focus à l'ouverture auto.
 * Envoi : POST JSON /api/retour/ avec token CSRF (back-end inchangé).
 */
(function () {
  "use strict";

  var STORAGE_KEY = "nitrates_feedback_v1"; // presence = demande auto deja faite
  var BETA_SESSION_KEY = "nitrates_beta_propose"; // proposition faite cette session
  var BETA_INSCRIT_KEY = "nitrates_beta_inscrit"; // email laisse : plus de proposition
  var DELAI_INACTION_MS = 45000; // fallback : 45 s sans clic sur le resultat
  var DELAI_ARMEMENT_MS = 5000; // temps de lecture mini avant d'armer l'exit intent

  function lire(stockage, cle) {
    try {
      return window[stockage].getItem(cle);
    } catch (e) {
      return null; // stockage indispo : on tolere
    }
  }

  function ecrire(stockage, cle, valeur) {
    try {
      window[stockage].setItem(cle, valeur);
    } catch (e) {
      /* ignore */
    }
  }

  function dejaDemande() {
    return !!lire("localStorage", STORAGE_KEY);
  }

  // Le cookie `csrftoken` est HttpOnly (#265) : on lit le jeton dans le champ
  // cache rendu par {% csrf_token %} (fragment _retours.html).
  function getCsrfToken() {
    var input = document.querySelector("input[name=csrfmiddlewaretoken]");
    if (input && input.value) return input.value;
    var m = document.cookie.match("(^|;)\\s*csrftoken\\s*=\\s*([^;]+)");
    return m ? decodeURIComponent(m.pop()) : "";
  }

  function poster(payload) {
    return fetch("/api/retour/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify(payload),
    }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  function init() {
    var root = document.getElementById("nitrates-feedback");
    if (!root) return;
    var toggle = document.getElementById("nitrates-avis-toggle");
    var retours = document.getElementById("nitrates-retours");

    var voletNote = root.querySelector("[data-feedback-volet-note]");
    var voletEmail = root.querySelector("[data-feedback-volet-email]");
    var voletMerci = root.querySelector("[data-feedback-merci]");
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
    var retourId = null; // id de l'entree feedback creee au volet 1
    var ouvert = false;

    // ── Etoiles ────────────────────────────────────────────────────────────
    function allumerJusqua(idx) {
      stars.forEach(function (s, i) {
        s.classList.toggle("is-on", i <= idx);
      });
    }
    function refletSelection() {
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
        submitNote.disabled = false; // envoi possible des qu'une note est mise
      });
    });
    root
      .querySelector(".nitrates-feedback__stars")
      .addEventListener("mouseleave", refletSelection);

    // ── Etat ───────────────────────────────────────────────────────────────
    function reinitialiser() {
      noteChoisie = null;
      retourId = null;
      commentaire.value = "";
      email.value = "";
      consent.checked = false;
      stars.forEach(function (s) {
        s.setAttribute("aria-checked", "false");
      });
      refletSelection();
      submitNote.disabled = true;
      submitEmail.disabled = true;
      erreurNote.hidden = true;
      erreurEmail.hidden = true;
      voletNote.hidden = false;
      voletEmail.hidden = true;
      voletMerci.hidden = true;
    }

    function montrer() {
      ouvert = true;
      root.hidden = false;
      if (toggle) toggle.setAttribute("aria-expanded", "true");
    }

    function fermer() {
      if (!ouvert) return;
      // Une note saisie mais pas envoyee part quand meme (best-effort).
      if (noteChoisie !== null && retourId === null) {
        envoyerNote(true);
      }
      ouvert = false;
      root.hidden = true;
      root.classList.remove("nitrates-feedback--efface");
      if (toggle) toggle.setAttribute("aria-expanded", "false");
    }

    // Ouverture manuelle : formulaire vierge, focus sur la premiere etoile.
    function ouvrirManuel() {
      reinitialiser();
      montrer();
      // Avis donne : plus besoin de le demander automatiquement.
      ecrire("localStorage", STORAGE_KEY, "manuel");
      if (stars[0]) stars[0].focus();
    }

    if (toggle) {
      toggle.addEventListener("click", function () {
        if (ouvert) fermer();
        else ouvrirManuel();
      });
    }
    root.querySelectorAll("[data-feedback-dismiss]").forEach(function (el) {
      el.addEventListener("click", fermer);
    });
    root.querySelector("[data-feedback-email-non]").addEventListener("click", fermer);
    root.querySelector("[data-feedback-fermer]").addEventListener("click", fermer);
    document.addEventListener("keydown", function (e) {
      if (
        ouvert &&
        e.key === "Escape" &&
        !root.classList.contains("nitrates-feedback--efface")
      ) {
        fermer();
      }
    });

    // ── Volet 1 : note + commentaire (SANS email) ──────────────────────────
    function proposerBeta() {
      return (
        !lire("sessionStorage", BETA_SESSION_KEY) &&
        !lire("localStorage", BETA_INSCRIT_KEY)
      );
    }

    function envoyerNote(silencieux) {
      if (noteChoisie === null) return Promise.resolve();
      submitNote.disabled = true;
      erreurNote.hidden = true;
      return poster({
        type: "feedback",
        note: noteChoisie,
        commentaire: (commentaire.value || "").trim(),
        region_code: (retours && retours.getAttribute("data-region-code")) || "",
        contexte: { source: "encart_avis", page: window.location.pathname },
      })
        .then(function (data) {
          retourId = data.id;
          if (silencieux) return;
          voletNote.hidden = true;
          if (proposerBeta()) {
            ecrire("sessionStorage", BETA_SESSION_KEY, "1");
            voletEmail.hidden = false;
            email.focus();
          } else {
            voletMerci.hidden = false;
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

    // ── Volet 2 : email bêta-testeur, attache a l'entree du volet 1 ─────────
    function majBoutonEmail() {
      submitEmail.disabled = !((email.value || "").trim() && consent.checked);
    }
    email.addEventListener("input", majBoutonEmail);
    consent.addEventListener("change", majBoutonEmail);

    submitEmail.addEventListener("click", function () {
      var emailVal = (email.value || "").trim();
      if (!emailVal || !consent.checked || retourId === null) return;
      submitEmail.disabled = true;
      erreurEmail.hidden = true;
      poster({ retour_id: retourId, email: emailVal, consentement_email: true })
        .then(function () {
          ecrire("localStorage", BETA_INSCRIT_KEY, "1");
          voletEmail.hidden = true;
          voletMerci.hidden = false;
        })
        .catch(function () {
          erreurEmail.hidden = false;
          submitEmail.disabled = false;
        });
    });

    // ── Ouverture automatique : fin de la premiere simulation, une fois ─────
    if (!document.querySelector("[data-nitrates-fin-simulation]")) return;
    if (dejaDemande()) return;

    // Anti-collision (#435) : cartes de definition et drawer conditions
    // partagent le bord droit. On n'ouvre pas tant qu'ils sont affiches, et
    // s'ils s'ouvrent apres nous on s'efface le temps qu'ils se referment.
    function encombrementActif() {
      return (
        document.body.classList.contains("drawer-open") ||
        !!document.querySelector(".def-carte--ouverte")
      );
    }

    var autoFaite = false;
    var ouvertureEnAttente = false;

    function ouvrirAuto() {
      if (autoFaite || ouvert || dejaDemande()) return;
      if (encombrementActif()) {
        ouvertureEnAttente = true;
        return;
      }
      autoFaite = true;
      ecrire("localStorage", STORAGE_KEY, "auto"); // une fois et une seule
      reinitialiser();
      montrer(); // non modal : pas de vol de focus
    }

    window.setInterval(function () {
      if (ouvert) {
        root.classList.toggle("nitrates-feedback--efface", encombrementActif());
      } else if (ouvertureEnAttente && !encombrementActif()) {
        ouvertureEnAttente = false;
        ouvrirAuto();
      }
    }, 1000);

    // Declencheur 1 : intention de sortie au curseur (sortie par le haut du
    // viewport), arme apres un temps de lecture minimal.
    var armementExit = Date.now() + DELAI_ARMEMENT_MS;
    document.addEventListener("mouseout", function (e) {
      if (autoFaite || ouvert) return;
      if (Date.now() < armementExit) return;
      if (e.relatedTarget !== null) return;
      if (e.clientY > 0) return;
      ouvrirAuto();
    });

    // Declencheur 2 (fallback, mobile) : DELAI_INACTION_MS sans clic. Le
    // compteur tourne en temps reel ; onglet masque -> on attend le retour.
    var echeance = Date.now() + DELAI_INACTION_MS;
    document.addEventListener(
      "click",
      function () {
        if (autoFaite || ouvert) return;
        echeance = Date.now() + DELAI_INACTION_MS;
      },
      true
    );
    var pollTimer = window.setInterval(function () {
      if (autoFaite || dejaDemande()) {
        window.clearInterval(pollTimer);
        return;
      }
      if (Date.now() >= echeance && document.visibilityState === "visible") {
        window.clearInterval(pollTimer);
        ouvrirAuto();
      }
    }, 1000);
    document.addEventListener("visibilitychange", function () {
      if (
        document.visibilityState === "visible" &&
        !autoFaite &&
        !dejaDemande() &&
        Date.now() >= echeance
      ) {
        window.clearInterval(pollTimer);
        ouvrirAuto();
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
