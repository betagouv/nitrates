/* Éditeur WYSIWYG des contenus riches DSFR (carte #131).
 *
 * Monte un Editor.js sur chaque champ `blocs` de l'admin ContenuRichDSFR. Le
 * juriste édite un rendu type Notion ; le JSON DSFR est produit sous le capot
 * et recopié dans le <textarea> caché (le vrai champ du form) au submit.
 *
 * Blocs DSFR <-> Editor.js (mapping 1:1, plus de convention implicite) :
 *   titre_principal   <-> header (level 2)   vrai titre
 *   titre_paragraphe  <-> header (level 4)   sous-titre
 *   paragraphe        <-> paragraph
 *   liste             <-> list (puces plates)
 *   citation          <-> quote
 *   foldable          <-> bloc custom `foldable` (FoldableTool, nested editor)
 */
(function () {
  "use strict";

  // Outils communs à l'éditeur racine ET aux nested editors des foldables.
  // (le foldable lui-même n'est PAS proposé dans un nested -> pas de foldable
  //  dans foldable, cf. spec §3 MVP.)
  function outilsDeBase() {
    return {
      header: { class: window.Header, inlineToolbar: true },
      list: { class: window.List, inlineToolbar: true },
      quote: { class: window.Quote, inlineToolbar: true },
    };
  }

  // ── DSFR -> Editor.js (au chargement) ───────────────────────────────────
  function dsfrToEditor(blocs) {
    return (blocs || []).map(dsfrBlocToEditor).filter(Boolean);
  }

  function dsfrBlocToEditor(b) {
    if (!b || !b.type) return null;
    const d = b.data || {};
    switch (b.type) {
      case "titre_principal":
        return { type: "header", data: { text: d.texte || "", level: 2 } };
      case "titre_paragraphe":
        return { type: "header", data: { text: d.texte || "", level: 4 } };
      case "paragraphe":
        return { type: "paragraph", data: { text: d.texte || "" } };
      case "liste":
        return {
          type: "list",
          data: {
            style: "unordered",
            items: (d.items || []).map((it) =>
              typeof it === "string" ? it : it.texte || ""
            ),
          },
        };
      case "citation":
        return { type: "quote", data: { text: d.texte || "", caption: "" } };
      case "foldable":
        return {
          type: "foldable",
          data: {
            titre: d.titre || "",
            blocks: dsfrToEditor(d.blocs || []),
          },
        };
      default:
        return null;
    }
  }

  // ── Editor.js -> DSFR (à la sauvegarde) ─────────────────────────────────
  function editorToDsfr(edBlocks) {
    return (edBlocks || []).map(editorBlocToDsfr).filter(Boolean);
  }

  function editorBlocToDsfr(b) {
    const d = b.data || {};
    switch (b.type) {
      case "header":
        if (Number(d.level) <= 3) {
          return { type: "titre_principal", data: { texte: d.text || "" } };
        }
        return { type: "titre_paragraphe", data: { texte: d.text || "" } };
      case "paragraph":
        return { type: "paragraphe", data: { texte: d.text || "" } };
      case "list":
        return {
          type: "liste",
          data: {
            items: (d.items || []).map((it) => ({
              texte: typeof it === "string" ? it : it.content || "",
            })),
          },
        };
      case "quote":
        return { type: "citation", data: { texte: d.text || "" } };
      case "foldable":
        return {
          type: "foldable",
          data: {
            titre: d.titre || "",
            blocs: editorToDsfr(d.blocks || []),
          },
        };
      default:
        return null;
    }
  }

  // ── Montage ─────────────────────────────────────────────────────────────
  function monter(textarea) {
    if (textarea.dataset.crMounted) return;
    textarea.dataset.crMounted = "1";

    let initial = { blocs: [] };
    try {
      const parsed = JSON.parse(textarea.value || "{}");
      initial = Array.isArray(parsed) ? { blocs: parsed } : parsed || {};
    } catch (e) {
      initial = { blocs: [] };
    }

    const holder = document.createElement("div");
    holder.className = "cr-editor-holder";
    textarea.style.display = "none";
    textarea.parentNode.insertBefore(holder, textarea.nextSibling);

    const tools = outilsDeBase();
    // Le foldable reçoit les outils de base pour son nested editor.
    tools.foldable = {
      class: window.FoldableTool,
      config: { tools: outilsDeBase() },
    };

    // eslint-disable-next-line no-undef
    const editor = new EditorJS({
      holder: holder,
      tools: tools,
      data: { blocks: dsfrToEditor(initial.blocs || []) },
      placeholder: "Rédigez le contenu…",
    });

    const form = textarea.closest("form");
    if (form) {
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        editor
          .save()
          .then(function (data) {
            textarea.value = JSON.stringify({
              schema: initial.schema || 1,
              blocs: editorToDsfr(data.blocks || []),
            });
            form.submit();
          })
          .catch(function () {
            form.submit();
          });
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    document
      .querySelectorAll("textarea[data-contenu-rich-editor]")
      .forEach(monter);
  });
})();
