/**
 * Aller-retour de l'éditeur admin (contenu_rich_editor.js) : DSFR -> Editor.js
 * -> DSFR doit rendre le contenu à l'identique. C'est ce que fait une juriste
 * qui ouvre une PC et clique « Enregistrer » sans rien toucher ; l'ancien outil
 * de liste supprimait alors les sous-puces (incident du 14/10/2026).
 *
 *   node --test envergo/static/nitrates_admin/contenu_rich_editor.test.js
 *
 * Le module lit le HTML inline via <template> : on fournit ici un DOM minimal
 * (b/strong, a[href], texte, entités), suffisant pour ce que produit l'éditeur.
 */
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

// ── DOM minimal pour htmlToTexte ─────────────────────────────────────────────
function decoder(s) {
  return s
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&");
}

function parser(html) {
  const racine = { nodeType: 1, tagName: "ROOT", childNodes: [], attrs: {} };
  const pile = [racine];
  const re = /<(\/?)([a-zA-Z]+)([^>]*)>|([^<]+)/g;
  let m;
  while ((m = re.exec(html))) {
    const parent = pile[pile.length - 1];
    if (m[4] !== undefined) {
      parent.childNodes.push({ nodeType: 3, nodeValue: decoder(m[4]) });
    } else if (m[1]) {
      pile.pop();
    } else {
      const attrs = {};
      (m[3].match(/(\w+)="([^"]*)"/g) || []).forEach(function (a) {
        const [, k, v] = a.match(/(\w+)="([^"]*)"/);
        attrs[k] = decoder(v);
      });
      const el = {
        nodeType: 1,
        tagName: m[2].toUpperCase(),
        childNodes: [],
        getAttribute: (k) => (k in attrs ? attrs[k] : null),
      };
      parent.childNodes.push(el);
      if (!/^(br|img)$/i.test(m[2])) pile.push(el);
    }
  }
  return racine;
}

global.document = {
  createElement: function () {
    const tpl = { content: { childNodes: [] } };
    Object.defineProperty(tpl, "innerHTML", {
      set: function (html) {
        tpl.content = parser(html || "");
      },
    });
    return tpl;
  },
};

const { dsfrToEditor, editorToDsfr } = require("./contenu_rich_editor.js");

// Simule l'éditeur : chargement, puis sauvegarde sans modification. Le JSON
// fait l'aller-retour comme dans le navigateur (sortie de editor.save()).
function allerRetour(blocs) {
  return editorToDsfr(JSON.parse(JSON.stringify(dsfrToEditor(blocs))));
}

// Formes équivalentes d'un même texte riche (segments sans style = chaîne,
// segments adjacents de même style fusionnés, clés vides omises).
function normaliser(x, cle) {
  if (Array.isArray(x)) {
    if (cle === "texte") {
      const segs = [];
      x.forEach(function (s) {
        const seg = typeof s === "string" ? { texte: s } : Object.assign({}, s);
        ["gras", "lien", "lien_ref"].forEach((k) => {
          if (!seg[k]) delete seg[k];
        });
        const prec = segs[segs.length - 1];
        const style = (o) => JSON.stringify([!!o.gras, o.lien || "", o.lien_ref || ""]);
        if (prec && style(prec) === style(seg)) prec.texte += seg.texte;
        else segs.push(seg);
      });
      if (segs.every((s) => !s.gras && !s.lien && !s.lien_ref)) {
        return segs.map((s) => s.texte).join("");
      }
      return segs;
    }
    return x.map((v) => normaliser(v));
  }
  if (x && typeof x === "object") {
    const out = {};
    Object.keys(x)
      .sort()
      .forEach(function (k) {
        if (k === "enfants" && (!x[k] || !x[k].length)) return;
        out[k] = normaliser(x[k], k);
      });
    return out;
  }
  return x;
}

const PC4 = [
  { type: "titre_principal", data: { texte: "Conditions à respecter" } },
  {
    type: "liste",
    data: {
      items: [
        {
          texte: "les conditions définies par le programme d'actions régional sont respectées, notamment sur :",
          enfants: [
            { texte: "la durée et la période de présence du couvert" },
            {
              texte: "le plafonnement des apports à cette période",
              enfants: [{ texte: [{ texte: "troisième niveau", gras: true }] }],
            },
          ],
        },
        {
          texte: [
            { texte: "un dispositif de suivi (" },
            { texte: "consultez l'annexe 1 du PAR Hauts-de-France (PDF)", lien_ref: "par-hdf-annexe1-reliquats" },
            { texte: ")" },
          ],
        },
      ],
    },
  },
  {
    type: "foldable",
    data: {
      titre: "Précisions sur le suivi",
      blocs: [
        { type: "liste", data: { items: [{ texte: "dans un volet", enfants: [{ texte: "sous-puce dans un volet" }] }] } },
      ],
    },
  },
];

test("les sous-puces survivent à un enregistrement sans modification", () => {
  assert.deepStrictEqual(normaliser(allerRetour(PC4)), normaliser(PC4));
});

test("le style numéroté d'une liste est conservé", () => {
  const blocs = [{ type: "liste", data: { style: "ordered", items: [{ texte: "un" }, { texte: "deux" }] } }];
  assert.deepStrictEqual(allerRetour(blocs), blocs);
});

test("une liste à puces reste sans clé style", () => {
  const blocs = [{ type: "liste", data: { items: [{ texte: "un" }] } }];
  assert.deepStrictEqual(allerRetour(blocs), blocs);
});

test("les anciens items en chaîne sont acceptés", () => {
  const blocs = [{ type: "liste", data: { items: ["un", "deux"] } }];
  assert.deepStrictEqual(allerRetour(blocs), [
    { type: "liste", data: { items: [{ texte: "un" }, { texte: "deux" }] } },
  ]);
});

test("aller-retour sans perte sur tout le contenu de la fixture du repo", () => {
  const fixture = path.join(__dirname, "../../nitrates/fixtures/initial_referentiels.json");
  const objets = JSON.parse(fs.readFileSync(fixture, "utf8"));
  let n = 0;
  objets.forEach(function (o) {
    const b = o.fields && o.fields.blocs;
    const blocs = Array.isArray(b) ? b : (b && b.blocs) || [];
    if (!blocs.length) return;
    n += 1;
    assert.deepStrictEqual(
      normaliser(allerRetour(blocs)),
      normaliser(blocs),
      `${o.model} ${o.fields.identifiant || o.fields.cle}`
    );
  });
  assert.ok(n > 40, `seulement ${n} contenus testés`);
});
