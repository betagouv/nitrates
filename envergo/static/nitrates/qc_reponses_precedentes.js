// Reprise des reponses aux questions complementaires (#273, retour Max).
//
// Apres un resultat, « Modifier » puis le changement d'un champ (ex. un autre
// fertilisant) : reset_form.js retire de l'URL les reponses QC en aval, le
// serveur repose donc ses questions. Si une meme question revient (meme
// champ), on pre-coche la reponse donnee juste avant, toujours modifiable.
//
// La memoire vit le temps de la page : une nouvelle simulation (page vierge,
// lien « Nouvelle simulation ») repart de zero ; un rechargement la
// reconstruit depuis les reponses affichees.
//
// Charge AVANT subsidiaires_cascade.js : sur nitrates:rendu-remplace on
// pre-coche d'abord, puis son init revele les QC enfants dont la parente est
// cochee (et decoche celles qui ne s'appliquent pas). Pas d'evenement change
// declenche ici : pas d'auto-scroll parasite vers le bouton.

(function () {
  "use strict";

  const _isNode =
    typeof module !== "undefined" &&
    module.exports &&
    typeof document === "undefined";

  // ─── Logique PURE (testable en Node) ────────────────────────────────────

  // Valeur a pre-cocher pour `champ` : la reponse retenue si elle fait partie
  // des choix proposes (comparaison sans casse, cf. True/true #408), sinon null.
  function valeurAReprendre(memoire, champ, valeursPossibles) {
    const retenue = memoire ? memoire[champ] : undefined;
    if (retenue === undefined || retenue === null || retenue === "") return null;
    const cible = String(retenue).toLowerCase();
    const trouvee = (valeursPossibles || []).find(
      (v) => String(v).toLowerCase() === cible
    );
    return trouvee === undefined ? null : trouvee;
  }

  if (_isNode) {
    module.exports = { valeurAReprendre };
    return;
  }

  const form = document.getElementById("form-simulateur");
  if (!form) return;

  const memoire = {};

  function groupesQc() {
    return Array.from(
      document.querySelectorAll("#qc-bloc .qc-question[data-qc-champ]")
    );
  }

  function memoriser(groupe) {
    const coche = groupe.querySelector('input[type="radio"]:checked');
    if (coche) memoire[groupe.dataset.qcChamp] = coche.value;
  }

  function signalerReprise(groupe) {
    if (groupe.querySelector(".qc-question__reprise")) return;
    const texte = groupe.querySelector(".form-question-text");
    if (!texte) return;
    const aide = document.createElement("p");
    aide.className = "fr-hint-text qc-question__reprise";
    aide.textContent = "Réponse reprise de votre simulation précédente.";
    texte.insertAdjacentElement("afterend", aide);
  }

  function reprendre() {
    groupesQc().forEach(function (groupe) {
      if (groupe.querySelector('input[type="radio"]:checked')) return;
      const radios = Array.from(groupe.querySelectorAll('input[type="radio"]'));
      const valeur = valeurAReprendre(
        memoire,
        groupe.dataset.qcChamp,
        radios.map((r) => r.value)
      );
      if (valeur === null) return;
      radios.find((r) => r.value === valeur).checked = true;
      signalerReprise(groupe);
    });
  }

  // Reponses affichees au chargement (recap des QC deja repondues).
  groupesQc().forEach(memoriser);

  // Chaque reponse donnee (ou modifiee) par l'utilisateur.
  form.addEventListener("change", function (e) {
    const groupe =
      e.target && e.target.closest && e.target.closest("#qc-bloc .qc-question");
    if (!groupe || e.target.type !== "radio") return;
    memoriser(groupe);
    if (e.isTrusted) {
      const aide = groupe.querySelector(".qc-question__reprise");
      if (aide) aide.remove();
    }
  });

  document.addEventListener("nitrates:rendu-remplace", reprendre);
})();
