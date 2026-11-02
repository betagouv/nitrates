// Reprise d'une question complementaire existante dans l'editeur (#620).
//
// A la frappe du texte d'une question complementaire, htmx remplit le volet
// [data-qc-volet] avec les questions existantes qui ressemblent (vue
// QcSuggestionsView). Ici, on gere le clic "Reprendre cette question" :
// texte, aide et champ sont recopies dans le formulaire, et les reponses
// (valeur + libelle) partent dans un champ cache [data-qc-branches] : le
// serveur les cree en branches a completer a l'enregistrement.
//
// Delegation au niveau document : les formulaires arrivent par swap htmx, et
// htmx n'execute pas les <script> inline des fragments.

(function () {
  "use strict";

  function champ(form, noms) {
    for (const nom of noms) {
      const el = form.querySelector(`[name="${nom}"]`);
      if (el) return el;
    }
    return null;
  }

  function fermerVolet(volet) {
    if (volet) volet.innerHTML = "";
  }

  function libelleReponses(branches) {
    return branches
      .map((b) => (b.libelle ? b.libelle : String(b.valeur)))
      .join(" / ");
  }

  function afficherReprise(form, donnees) {
    const zone = form.querySelector("[data-qc-reprise]");
    if (!zone) return;
    zone.textContent = "";
    const texte = document.createElement("span");
    texte.textContent =
      `Question existante reprise : champ ${donnees.champ}. ` +
      `Réponses créées à l'enregistrement : ${libelleReponses(donnees.branches)}.`;
    const annuler = document.createElement("button");
    annuler.type = "button";
    annuler.className = "yaml-admin__btn yaml-admin__btn--small";
    annuler.dataset.qcRepriseAnnuler = "";
    annuler.textContent = "Ne pas reprendre";
    zone.append(texte, " ", annuler);
    zone.hidden = false;
  }

  function reprendre(bouton) {
    const form = bouton.closest("form");
    if (!form) return;
    let donnees;
    try {
      donnees = JSON.parse(bouton.dataset.qcUtiliser);
    } catch (e) {
      return;
    }
    const texte = champ(form, ["c_texte", "texte"]);
    const aide = champ(form, ["c_aide", "aide"]);
    const champTech = champ(form, ["c_champ", "champ"]);
    const branches = form.querySelector("[data-qc-branches]");
    if (texte) {
      texte.value = donnees.texte;
      texte.dataset.touched = "1";
    }
    if (aide) aide.value = donnees.aide || "";
    if (champTech) {
      champTech.value = donnees.champ;
      champTech.dataset.touched = "1";
    }
    if (branches) branches.value = JSON.stringify(donnees.branches || []);
    afficherReprise(form, donnees);
    fermerVolet(bouton.closest("[data-qc-volet]"));
    if (texte) texte.focus();
  }

  function annulerReprise(bouton) {
    const form = bouton.closest("form");
    if (!form) return;
    const branches = form.querySelector("[data-qc-branches]");
    if (branches) branches.value = "";
    const zone = form.querySelector("[data-qc-reprise]");
    if (zone) {
      zone.hidden = true;
      zone.textContent = "";
    }
  }

  document.addEventListener("click", (evt) => {
    const cible = evt.target;
    if (!(cible instanceof Element)) return;
    const utiliser = cible.closest("[data-qc-utiliser]");
    if (utiliser) {
      evt.preventDefault();
      reprendre(utiliser);
      return;
    }
    if (cible.closest("[data-qc-volet-fermer]")) {
      evt.preventDefault();
      fermerVolet(cible.closest("[data-qc-volet]"));
      return;
    }
    const annuler = cible.closest("[data-qc-reprise-annuler]");
    if (annuler) {
      evt.preventDefault();
      annulerReprise(annuler);
      return;
    }
    // Le formulaire d'edition d'un noeud vit dans un <summary> : un clic sur
    // le texte du volet replierait le noeud. On l'en empeche.
    if (cible.closest("[data-qc-volet], [data-qc-reprise]")) {
      evt.preventDefault();
    }
  });

  document.addEventListener("keydown", (evt) => {
    if (evt.key !== "Escape") return;
    document.querySelectorAll("[data-qc-volet]").forEach((v) => {
      if (v.innerHTML.trim()) fermerVolet(v);
    });
  });

  // Formulaire re-rendu apres une erreur (422) : la reprise choisie est
  // conservee dans le champ cache, on la re-affiche.
  function resynchroniser(racine) {
    (racine || document).querySelectorAll("[data-qc-branches]").forEach((el) => {
      const form = el.closest("form");
      const champTech = form && champ(form, ["c_champ", "champ"]);
      if (!form || !el.value) return;
      try {
        afficherReprise(form, {
          champ: champTech ? champTech.value : "",
          branches: JSON.parse(el.value),
        });
      } catch (e) {
        el.value = "";
      }
    });
  }
  document.addEventListener("DOMContentLoaded", () => resynchroniser(document));
  document.body &&
    document.body.addEventListener("htmx:afterSettle", (evt) =>
      resynchroniser(evt.target)
    );
})();
