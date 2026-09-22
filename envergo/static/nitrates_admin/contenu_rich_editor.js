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
 *   tableau           <-> table (@editorjs/table, carte #110)
 */
(function () {
  "use strict";

  // Outils communs à l'éditeur racine ET aux nested editors des foldables.
  // (le foldable lui-même n'est PAS proposé dans un nested -> pas de foldable
  //  dans foldable, cf. spec §3 MVP.)
  function outilsDeBase() {
    return {
      header: { class: window.Header, inlineToolbar: true, tunes: ["indent"] },
      list: {
        class: window.List,
        inlineToolbar: true,
        // « add > Liste » crée une liste À PUCES par défaut (#136). L'utilisateur
        // peut basculer en numérotée via les réglages du bloc (icône engrenage).
        config: { defaultStyle: "unordered" },
        tunes: ["indent"],
      },
      quote: { class: window.Quote, inlineToolbar: true, tunes: ["indent"] },
      // Tableau (carte #110). withHeadings par défaut : nos tableaux métier
      // (types de fertilisants) ont toujours une ligne d'entêtes.
      table: {
        class: window.Table,
        inlineToolbar: true,
        config: { withHeadings: true },
      },
      // Tune d'indentation (carte #136), partagé par les blocs ci-dessus.
      indent: { class: window.IndentTune },
    };
  }

  // ── Inline : segments {texte,gras,lien,lien_ref} <-> HTML Editor.js ─────
  // Editor.js stocke le gras dans le `text` sous forme de <b>…</b> et le lien
  // sous forme de <a href="…"> (outil inline natif). Côté DSFR on stocke des
  // segments structurés (jamais de HTML). Ces deux helpers font la conversion
  // (carte #136 pour le gras, #467 pour le lien).
  // Lien syndiqué (#467) : un segment {lien_ref: "cle"} s'affiche dans
  // l'éditeur comme href "ref:cle" et repart tel quel à la sauvegarde — la
  // référence survit aux éditions juriste, l'URL réelle est résolue au rendu
  // public via la table LienReference. Poser href "ref:ma-cle" dans l'outil
  // lien crée donc un lien syndiqué depuis l'admin.

  // segments OU string -> HTML inline (pour charger dans Editor.js).
  function texteToHtml(valeur) {
    if (typeof valeur === "string") return escapeHtml(valeur);
    if (Array.isArray(valeur)) {
      return valeur
        .map(function (seg) {
          if (typeof seg === "string") return escapeHtml(seg);
          const t = escapeHtml(seg.texte || "");
          let out = seg.gras ? "<b>" + t + "</b>" : t;
          const href = seg.lien_ref ? "ref:" + seg.lien_ref : seg.lien;
          if (href) {
            out = '<a href="' + escapeAttr(href) + '">' + out + "</a>";
          }
          return out;
        })
        .join("");
    }
    return "";
  }

  // HTML inline d'Editor.js -> segments {texte,gras,lien} (à la sauvegarde).
  // On parse le HTML, on aplatit en segments en suivant la présence d'un
  // ancêtre b/strong (gras) et a[href] (lien). Si aucun style -> on renvoie
  // une simple string (compact).
  function htmlToTexte(html) {
    const tpl = document.createElement("template");
    tpl.innerHTML = html || "";
    const segments = [];
    function walk(node, gras, lien) {
      node.childNodes.forEach(function (n) {
        if (n.nodeType === 3) {
          // texte
          if (n.nodeValue)
            segments.push({ texte: n.nodeValue, gras: gras, lien: lien });
        } else if (n.nodeType === 1) {
          const estGras =
            gras || n.tagName === "B" || n.tagName === "STRONG";
          const estLien =
            n.tagName === "A" ? n.getAttribute("href") || lien : lien;
          walk(n, estGras, estLien);
        }
      });
    }
    walk(tpl.content, false, "");
    // Fusionner segments adjacents de même style.
    const fusion = [];
    segments.forEach(function (s) {
      const prev = fusion[fusion.length - 1];
      if (prev && !!prev.gras === !!s.gras && (prev.lien || "") === (s.lien || ""))
        prev.texte += s.texte;
      else fusion.push({ texte: s.texte, gras: !!s.gras, lien: s.lien || "" });
    });
    if (fusion.length === 0) return "";
    // Aucun gras ni lien -> string plate (rétrocompat / JSON compact).
    if (fusion.every(function (s) {
      return !s.gras && !s.lien;
    })) {
      return fusion.map(function (s) {
        return s.texte;
      }).join("");
    }
    // Clés compactes : on n'émet gras/lien que quand ils portent une valeur.
    // href "ref:cle" -> segment {lien_ref: "cle"} (lien syndiqué).
    return fusion.map(function (s) {
      const seg = { texte: s.texte };
      if (s.gras) seg.gras = true;
      if (s.lien) {
        if (s.lien.indexOf("ref:") === 0) seg.lien_ref = s.lien.slice(4);
        else seg.lien = s.lien;
      }
      return seg;
    });
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function escapeAttr(s) {
    return escapeHtml(s).replace(/"/g, "&quot;");
  }

  // ── Indentation (tune) : data.indent DSFR <-> block.tunes.indent.level ──
  function tunesDepuisIndent(d) {
    const niveau = Number((d && d.indent) || 0) || 0;
    return niveau > 0 ? { indent: { level: niveau } } : undefined;
  }

  function indentDepuisTunes(b) {
    const lvl = b && b.tunes && b.tunes.indent && b.tunes.indent.level;
    return Number(lvl) > 0 ? Number(lvl) : 0;
  }

  // ── DSFR -> Editor.js (au chargement) ───────────────────────────────────
  function dsfrToEditor(blocs) {
    return (blocs || []).map(dsfrBlocToEditor).filter(Boolean);
  }

  function dsfrBlocToEditor(b) {
    if (!b || !b.type) return null;
    const d = b.data || {};
    const eb = dsfrBlocToEditorBase(b, d);
    if (eb) {
      const t = tunesDepuisIndent(d);
      if (t) eb.tunes = t;
    }
    return eb;
  }

  function dsfrBlocToEditorBase(b, d) {
    switch (b.type) {
      case "titre_principal":
        // H3 (demande Coralie #136) : titre fort de la PC.
        return { type: "header", data: { text: d.texte || "", level: 3 } };
      case "titre_paragraphe":
        // H6 (demande Coralie #136) : sous-titre de section.
        return { type: "header", data: { text: d.texte || "", level: 6 } };
      case "paragraphe":
        return { type: "paragraph", data: { text: texteToHtml(d.texte) } };
      case "liste":
        return {
          type: "list",
          data: {
            style: "unordered",
            items: (d.items || []).map((it) =>
              texteToHtml(typeof it === "string" ? it : it.texte || "")
            ),
          },
        };
      case "citation":
        return {
          type: "quote",
          data: { text: texteToHtml(d.texte), caption: "" },
        };
      case "foldable":
        return {
          type: "foldable",
          data: {
            titre: d.titre || "",
            blocks: dsfrToEditor(d.blocs || []),
          },
        };
      case "tableau":
        // Cellules = texte riche DSFR (string ou segments) -> HTML inline
        // pour Editor.js, via texteToHtml (échappement conservé).
        return {
          type: "table",
          data: {
            withHeadings: d.avec_entetes !== false,
            content: (d.lignes || []).map(function (ligne) {
              return (ligne || []).map(texteToHtml);
            }),
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
    const dsfr = editorBlocToDsfrBase(b);
    if (dsfr) {
      const indent = indentDepuisTunes(b);
      if (indent > 0) dsfr.data.indent = indent;
    }
    return dsfr;
  }

  function editorBlocToDsfrBase(b) {
    const d = b.data || {};
    switch (b.type) {
      case "header":
        if (Number(d.level) <= 3) {
          return { type: "titre_principal", data: { texte: d.text || "" } };
        }
        return { type: "titre_paragraphe", data: { texte: d.text || "" } };
      case "paragraph":
        return { type: "paragraphe", data: { texte: htmlToTexte(d.text) } };
      case "list":
        return {
          type: "liste",
          data: {
            items: (d.items || []).map((it) => ({
              texte: htmlToTexte(typeof it === "string" ? it : it.content || ""),
            })),
          },
        };
      case "quote":
        return { type: "citation", data: { texte: htmlToTexte(d.text) } };
      case "foldable":
        return {
          type: "foldable",
          data: {
            titre: d.titre || "",
            blocs: editorToDsfr(d.blocks || []),
          },
        };
      case "table":
        // HTML inline des cellules -> texte riche structuré (htmlToTexte),
        // JAMAIS de HTML brut stocké en DB (invariant sécurité du compilateur).
        return {
          type: "tableau",
          data: {
            avec_entetes: d.withHeadings !== false,
            lignes: (d.content || []).map(function (ligne) {
              return (ligne || []).map(htmlToTexte);
            }),
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
      // Tunes GLOBAUX : Editor.js n'appelle wrap() du tune que si celui-ci est
      // déclaré ici (la clé `tunes` racine), pas seulement par-bloc. C'est ce
      // qui active l'indentation visuelle live (#136).
      tunes: ["indent"],
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
