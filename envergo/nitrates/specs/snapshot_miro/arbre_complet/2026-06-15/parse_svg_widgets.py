"""Extrait les widgets du board Miro (export SVG) avec géométrie + texte.

Chaque box du board Miro porte un `data-widget-id` numérique : c'est
exactement la valeur attendue par l'URL de deeplink
`https://miro.com/app/board/<BOARD_ID>/?moveToWidget=<id>` (clic →
Miro recentre la vue sur la box). On exploite ça pour fabriquer des
liens cliquables par feuille de l'arbre, à la place des screenshots.

Le SVG donne aussi, par widget, sa position absolue
(`transform="translate(x, y) scale(s) ..."`) et ses dimensions
(`width`/`height` du `<g>` interne). On garde tout ça pour pouvoir
désambiguïser les feuilles-résultat dont le TEXTE est dupliqué (ex.
« Interdit du 15/12 au 15/01 » apparaît 8× sur le board) : la
désambiguïsation se fera par proximité spatiale dans une 2e passe.

Sortie : `widgets.json` = liste d'objets
    {id, x, y, w, h, scale, texte}
trié par (y, x) — soit l'ordre de lecture haut→bas, gauche→droite.

Usage :
    python parse_svg_widgets.py            # lit board.svg, écrit widgets.json
    python parse_svg_widgets.py board.svg out.json
"""

import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Découpe le SVG en groupes <g data-widget-id="..."> ... </g-fin-implicite>.
# Le split capture l'ouverture ET l'id ; le segment suivant est le corps
# jusqu'au prochain widget (suffisant pour récupérer texte + géométrie de
# CE widget, le board étant à plat — un niveau de widgets).
_SPLIT = re.compile(r'(<g data-widget-id="(\d+)">)')
_TRANSLATE = re.compile(r"translate\(([-\d.]+),\s*([-\d.]+)\)")
_SCALE = re.compile(r"scale\(([-\d.]+)")
_GW = re.compile(r'<g\b[^>]*\bwidth="(\d+)px"\s+height="(\d+)px"')
_TEXT = re.compile(r"<text[^>]*>(.*?)</text>", re.S)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_ZW = "​"  # zero-width space que Miro injecte dans les césures


def _clean(raw_text: str) -> str:
    txt = _TAG.sub(" ", raw_text)
    txt = html.unescape(txt)
    txt = txt.replace(_ZW, "")
    return _WS.sub(" ", txt).strip()


def parse(svg_path: Path) -> list[dict]:
    data = svg_path.read_text(encoding="utf-8")
    parts = _SPLIT.split(data)
    # parts = [pre, open1, id1, body1, open2, id2, body2, ...]
    widgets = []
    for i in range(1, len(parts) - 2, 3):
        wid = parts[i + 1]
        body = parts[i + 2]

        # Géométrie : 1er translate/scale du corps = transform du widget.
        m_t = _TRANSLATE.search(body)
        m_s = _SCALE.search(body)
        m_g = _GW.search(body)
        x = float(m_t.group(1)) if m_t else None
        y = float(m_t.group(2)) if m_t else None
        scale = float(m_s.group(1)) if m_s else 1.0
        w = int(m_g.group(1)) if m_g else None
        h = int(m_g.group(2)) if m_g else None

        # Texte : concatène tous les <text> du corps.
        chunks = [_clean(t) for t in _TEXT.findall(body)]
        texte = " ".join(c for c in chunks if c)

        widgets.append(
            {
                "id": wid,
                "x": x,
                "y": y,
                "w": (w * scale) if (w is not None) else None,
                "h": (h * scale) if (h is not None) else None,
                "scale": scale,
                "texte": texte,
            }
        )

    # Ordre de lecture board : haut→bas puis gauche→droite.
    widgets.sort(
        key=lambda d: (
            d["y"] if d["y"] is not None else 1e9,
            d["x"] if d["x"] is not None else 1e9,
        )
    )
    return widgets


def main():
    svg = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "board.svg"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "widgets.json"
    widgets = parse(svg)
    out.write_text(json.dumps(widgets, ensure_ascii=False, indent=1), encoding="utf-8")
    with_text = sum(1 for w in widgets if w["texte"])
    print(f"{len(widgets)} widgets ({with_text} avec texte) -> {out}")


if __name__ == "__main__":
    main()
