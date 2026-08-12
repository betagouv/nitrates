/* #287 — Recueil d'email « prévenez-moi à l'ouverture de ma région ».
 *
 * Quand la parcelle cliquée est dans une région non ouverte, simulator.js
 * affiche #form-region-fermee (avec le data-region-code de la région tentée).
 * Ce script gère le mini-formulaire email : POST /api/retour/ en
 * type=interet_region (email + consentement + region_code), puis affiche un
 * remerciement. Réutilise le même endpoint que le feedback (#284).
 */
(function () {
  "use strict";

  function getCsrfToken() {
    var input = document.querySelector("input[name=csrfmiddlewaretoken]");
    if (input && input.value) return input.value;
    var m = document.cookie.match("(^|;)\\s*csrftoken\\s*=\\s*([^;]+)");
    return m ? decodeURIComponent(m.pop()) : "";
  }

  function init() {
    var fermee = document.getElementById("form-region-fermee");
    if (!fermee) return;

    var email = fermee.querySelector("#form-region-fermee-email");
    var consent = fermee.querySelector("#form-region-fermee-consent");
    var submit = fermee.querySelector("[data-region-alerte-submit]");
    var erreur = fermee.querySelector("[data-region-alerte-erreur]");
    var alerte = fermee.querySelector("[data-region-alerte]");
    var merci = fermee.querySelector("[data-region-alerte-merci]");
    if (!email || !consent || !submit) return;

    function maj() {
      submit.disabled = !((email.value || "").trim() && consent.checked);
    }
    email.addEventListener("input", maj);
    consent.addEventListener("change", maj);

    submit.addEventListener("click", function () {
      var emailVal = (email.value || "").trim();
      if (!emailVal || !consent.checked) return;
      submit.disabled = true;
      if (erreur) erreur.hidden = true;

      fetch("/api/retour/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify({
          type: "interet_region",
          email: emailVal,
          consentement_email: true,
          region_code: fermee.getAttribute("data-region-code") || "",
          contexte: { source: "region_fermee" },
        }),
      })
        .then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then(function () {
          // Remplace le mini-formulaire par le remerciement.
          if (alerte) alerte.hidden = true;
          if (merci) merci.hidden = false;
        })
        .catch(function () {
          if (erreur) erreur.hidden = false;
          submit.disabled = false;
        });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
