/* Plugin Editor.js "Section dépliable" (foldable DSFR) — carte #131.
 *
 * Un vrai bloc dans la toolbox : titre éditable inline + un Editor.js IMBRIQUÉ
 * pour le contenu de la section (paragraphes, listes, citations). Le juriste
 * édite directement, le rendu DSFR (fr-accordion) est recompilé côté serveur.
 *
 * Données du bloc (format Editor.js) :
 *   { titre: "Cours d'eau", blocks: [ {type, data}, ... ] }
 * où `blocks` est la sortie native du nested editor (convertie en blocs DSFR
 * par la glue contenu_rich_editor.js au save du form).
 *
 * Expose window.FoldableTool. La liste d'outils à donner au nested editor est
 * passée via config.tools (mêmes outils que l'éditeur racine, header/list/quote).
 */
(function () {
  "use strict";

  function FoldableTool(opts) {
    opts = opts || {};
    this.api = opts.api;
    this.readOnly = !!opts.readOnly;
    this.data = opts.data || {};
    this.config = opts.config || {};
    this.nested = null;
    this.wrapper = null;
    this.titreEl = null;
  }

  // Editor.js lit `static get toolbox()` pour peupler le menu "+".
  Object.defineProperty(FoldableTool, "toolbox", {
    get: function () {
      return {
        title: "Section dépliable",
        icon:
          '<svg width="17" height="15" viewBox="0 0 17 15"><path d="M1 4h15M1 8h15M1 12h9" ' +
          'stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/></svg>',
      };
    },
  });

  FoldableTool.prototype.render = function () {
    const wrapper = document.createElement("div");
    wrapper.className = "cr-foldable";

    // Titre éditable (inline).
    const titre = document.createElement("div");
    titre.className = "cr-foldable__titre";
    titre.contentEditable = this.readOnly ? "false" : "true";
    titre.dataset.placeholder = "Titre de la section…";
    titre.textContent = this.data.titre || "";

    // Holder du contenu (nested editor).
    const corps = document.createElement("div");
    corps.className = "cr-foldable__corps";

    wrapper.appendChild(titre);
    wrapper.appendChild(corps);
    this.wrapper = wrapper;
    this.titreEl = titre;

    // Le holder doit être dans le DOM avant d'instancier le nested editor.
    // Editor.js appelle render() puis insère le retour ; on diffère donc
    // l'init du nested au prochain tick (le wrapper est alors attaché).
    const self = this;
    setTimeout(function () {
      self._initNested(corps);
    }, 0);

    return wrapper;
  };

  FoldableTool.prototype._initNested = function (holder) {
    const tools = (this.config && this.config.tools) || {};
    const blocks = this.data.blocks || [];
    // eslint-disable-next-line no-undef
    this.nested = new EditorJS({
      holder: holder,
      tools: tools,
      readOnly: this.readOnly,
      minHeight: 40,
      data: { blocks: blocks },
      // Pas de placeholder bruyant dans une section.
      placeholder: "Contenu de la section…",
    });
  };

  FoldableTool.prototype.save = function () {
    const titre = this.titreEl ? this.titreEl.textContent.trim() : "";
    if (!this.nested) {
      return { titre: titre, blocks: this.data.blocks || [] };
    }
    // save() du nested est async -> on renvoie une promesse, Editor.js await.
    return this.nested.save().then(function (out) {
      return { titre: titre, blocks: (out && out.blocks) || [] };
    });
  };

  FoldableTool.prototype.destroy = function () {
    if (this.nested && this.nested.destroy) {
      try {
        this.nested.destroy();
      } catch (e) {
        /* nested déjà détruit */
      }
    }
  };

  window.FoldableTool = FoldableTool;
})();
