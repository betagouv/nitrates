// Auto-scroll progressif du formulaire simulateur (#83 / suite UX).
//
// Objectif : rendre le parcours fluide. A chaque reponse, l'etape suivante
// apparait (la cascade DSFR la "revele" en retirant l'attribut `hidden`) et on
// amene doucement l'utilisateur dessus, sans qu'il ait a chercher ou continuer.
//
//   clic carte -> parcelle resolue        => scroll vers "Culture"
//   choix categorie culture               => scroll vers "Precisez le type"
//   choix type de culture                 => scroll vers "Fertilisant"
//   choix categorie fertilisant           => scroll vers le sous-fertilisant
//   choix sous-fertilisant (fin cascade)  => scroll vers "Lancer la simulation"
//
// On NE touche PAS cascade.js / simulator.js : on observe le DOM. Un
// MutationObserver detecte quand un conteneur d'etape passe de `hidden` a
// visible, et on scrolle dessus. Le dernier pas (-> bouton submit) est gere par
// un listener sur le dernier champ, car le bouton est toujours visible (pas de
// transition `hidden` a observer).
//
// Le scroll des questions COMPLEMENTAIRES est gere ailleurs (scroll_resultat.js,
// #112) : ici on ne s'occupe que du formulaire principal.

(function () {
  "use strict";

  var form = document.getElementById("form-simulateur");
  if (!form) return;

  var reduceMotion =
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Anti-rebond : on ne scrolle qu'une fois par revelation, et on laisse un
  // court delai apres la mutation pour que le contenu (radios) soit rendu et
  // mesurable. Volontairement doux (pas instantane) pour ne pas brusquer.
  var dernierScroll = 0;
  function scrollVers(el) {
    if (!el) return;
    var maintenant = Date.now();
    // Throttle : evite les scrolls en rafale si plusieurs mutations groupees.
    if (maintenant - dernierScroll < 250) return;
    dernierScroll = maintenant;
    // rAF : position stable apres le reflow de la revelation.
    requestAnimationFrame(function () {
      el.scrollIntoView({
        behavior: reduceMotion ? "auto" : "smooth",
        block: "center",
      });
    });
  }

  // Cible de scroll prefere pour un conteneur revele : on remonte au titre de
  // section (.form-section) si l'element est dedans, pour donner le contexte
  // ("Culture", "Fertilisant") ; sinon l'element lui-meme.
  function cibleDepuis(el, prefererSection) {
    if (prefererSection) {
      var section = el.closest(".form-section");
      if (section) return section;
    }
    return el;
  }

  // Map : id de l'element qui se revele -> doit-on viser sa section parente ?
  // - sections entieres (#section-culture via #form-after-localisation,
  //   #categorie_fertilisant-wrapper dans #section-fertilisant) : oui, on
  //   cadre sur le titre de section.
  // - wrappers intermediaires (sous_culture_form, sous_fertilisant) : non, on
  //   cadre pile sur la nouvelle question.
  var ETAPES = [
    { id: "section-culture", section: false },
    { id: "sous_culture_form-wrapper", section: false },
    { id: "section-fertilisant", section: false },
    { id: "categorie_fertilisant-wrapper", section: false },
    { id: "sous_fertilisant-wrapper", section: false },
  ];

  function estVisible(el) {
    return el && !el.hidden && el.offsetParent !== null;
  }

  // Observe chaque etape : quand son `hidden` tombe (revelation), on scrolle.
  ETAPES.forEach(function (etape) {
    var el = document.getElementById(etape.id);
    if (!el) return;
    // Ne pas scroller pour les etapes deja visibles au chargement (cas d'un
    // parcours rejoue depuis l'URL : tout est deja la, pas de revelation).
    var dejaVisible = estVisible(el);
    var obs = new MutationObserver(function () {
      if (estVisible(el) && !dejaVisible) {
        scrollVers(cibleDepuis(el, etape.section));
        dejaVisible = true; // une seule fois
      } else if (!estVisible(el)) {
        // L'etape a ete re-cachee (l'user a change un choix en amont) : on
        // re-arme pour rescroller a la prochaine revelation.
        dejaVisible = false;
      }
    });
    obs.observe(el, { attributes: true, attributeFilter: ["hidden"] });
  });

  // Cas special "section-culture" : c'est #form-after-localisation qui change
  // de `hidden` (au clic carte), pas #section-culture directement. On observe
  // donc le conteneur et on scrolle vers la section Culture qu'il contient.
  var zoneApresLoc = document.getElementById("form-after-localisation");
  if (zoneApresLoc) {
    var dejaRevele = estVisible(zoneApresLoc);
    var obsLoc = new MutationObserver(function () {
      if (estVisible(zoneApresLoc) && !dejaRevele) {
        dejaRevele = true;
        scrollVers(
          document.getElementById("section-culture") || zoneApresLoc
        );
      }
    });
    obsLoc.observe(zoneApresLoc, {
      attributes: true,
      attributeFilter: ["hidden"],
    });
  }

  // Dernier pas : apres le choix du sous-fertilisant (fin de cascade), aucune
  // nouvelle etape ne se revele -> on amene au bouton de soumission. On ecoute
  // les `change` sur le champ sous_fertilisant (delegation, car ses radios sont
  // generes dynamiquement par cascade.js).
  form.addEventListener("change", function (e) {
    var t = e.target;
    if (t && t.name === "sous_fertilisant" && t.checked) {
      var submit = form.querySelector('button[type="submit"]');
      // Petit delai : laisse cascade.js resoudre les hidden inputs d'abord.
      setTimeout(function () {
        scrollVers(submit);
      }, 120);
    }
  });
})();
