/* Block Tune Editor.js « Indentation » (carte #136).
 *
 * Ajoute à CHAQUE bloc un réglage d'indentation (menu engrenage du bloc) :
 * « Indenter » / « Désindenter ». Le niveau est stocké dans les tunes du bloc
 * et appliqué visuellement via une marge gauche sur le wrapper du bloc.
 *
 * Round-trip : la glue (contenu_rich_editor.js) lit/écrit ce niveau dans
 * data.indent côté DSFR (cf. editorBlocToDsfr / dsfrBlocToEditor).
 *
 * Expose window.IndentTune. À enregistrer comme tune et activé via
 * `tunes: ['indent']` sur les blocs voulus.
 */
(function () {
  "use strict";

  var MAX = 6;
  var STEP_REM = 1.5;

  function IndentTune(opts) {
    opts = opts || {};
    this.api = opts.api;
    this.data = opts.data || {};
    this.block = opts.block;
    this.level = Number(this.data.level || 0) || 0;
    this.wrapper = null;
  }

  // Tune (pas un bloc) : signalé à Editor.js via getter statique (l'API lit
  // `static get isTune()`).
  Object.defineProperty(IndentTune, "isTune", { get: function () { return true; } });

  // Applique la marge au wrapper du bloc.
  IndentTune.prototype._appliquer = function () {
    if (!this.wrapper) return;
    var m = Math.max(0, Math.min(MAX, this.level)) * STEP_REM;
    this.wrapper.style.marginLeft = m + "rem";
  };

  // wrap() : Editor.js passe le contenu du bloc, on l'enveloppe pour porter
  // la marge. Le wrapper est ré-utilisé à chaque rendu du bloc.
  IndentTune.prototype.wrap = function (blockContent) {
    this.wrapper = document.createElement("div");
    this.wrapper.classList.add("cr-indent");
    this.wrapper.appendChild(blockContent);
    this._appliquer();
    return this.wrapper;
  };

  // render() : items du menu réglages du bloc.
  IndentTune.prototype.render = function () {
    var self = this;

    function bouton(label, delta, svg) {
      var el = document.createElement("div");
      el.classList.add("ce-popover-item");
      el.innerHTML =
        '<div class="ce-popover-item__icon">' +
        svg +
        '</div><div class="ce-popover-item__title">' +
        label +
        "</div>";
      el.addEventListener("click", function () {
        self.level = Math.max(0, Math.min(MAX, self.level + delta));
        self._appliquer();
        // referme le menu après action
        if (self.api && self.api.tooltip) self.api.tooltip.hide();
      });
      return el;
    }

    var wrap = document.createElement("div");
    var iconIn =
      '<svg width="16" height="16" viewBox="0 0 24 24"><path d="M3 5h18M3 12h11M3 19h18M16 9l4 3-4 3" ' +
      'stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    var iconOut =
      '<svg width="16" height="16" viewBox="0 0 24 24"><path d="M3 5h18M9 12h11M3 19h18M8 9l-4 3 4 3" ' +
      'stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    wrap.appendChild(bouton("Indenter", +1, iconIn));
    wrap.appendChild(bouton("Désindenter", -1, iconOut));
    return wrap;
  };

  // save() : persiste le niveau dans les tunes du bloc.
  IndentTune.prototype.save = function () {
    return { level: this.level };
  };

  window.IndentTune = IndentTune;
})();
