#!/usr/bin/env python3
"""Matcher Miro -> feuille pour la zone ZAR Grand Est du board PAR+ZAR.

Le board `par_zar_grand_est/2026-06-18/board.svg` contient l'arbre PAR ET
l'arbre ZAR. La zone ZAR occupe la bande y >= ~9900 (label « Arbre ZAR GE »
a x=445 y=10040). Ce script ne traite QUE la zone ZAR.

Pour chaque feuille ZAR (sortie de l'enumerateur, avec sa regle YAML), on
cherche le widget-resultat Miro le plus proche par :
  - section (sous_culture -> bande du board)
  - type_fertilisant (Type Ia/Ib/II)
  - signature calendrier (dates du/au + regime issus de la regle YAML
    comparees au texte du widget).

Plusieurs feuilles ZAR (variantes ICPE/IAA/digestats) partagent le meme
widget-resultat visuel : c'est attendu, le mapping est regle_id -> widget.

Entrees :
  - widgets.json  (genere par parse_svg_widgets.py)
  - /tmp/zar_feuilles.json  (feuilles + regle YAML, dumpe via manage.py shell)
Sorties :
  - mapping_widget_ids_zar.json  (regle_id -> {widget_id, resultat, code_pc, confiance})
  - crops_named_zar/<regle_id>.png
  - _RAPPORT_ZAR.md
"""

import json
import os
import re
import subprocess
import sys
from difflib import SequenceMatcher

HERE = os.path.dirname(os.path.abspath(__file__))
BOARD = os.path.join(HERE, "board.svg")
OUT = os.path.join(HERE, "crops_named_zar")
# crop_svg_viewbox.mjs vit dans le worktree #140 capture ; chemin passe en env.
CROP = os.environ.get(
    "CROP_MJS",
    "/Users/max/Data/betagouv/dev/nitrates-140-capture/crop_svg_viewbox.mjs",
)
FEUILLES_JSON = os.environ.get("ZAR_FEUILLES", "/tmp/zar_feuilles.json")

os.makedirs(OUT, exist_ok=True)
ws = json.load(open(os.path.join(HERE, "widgets.json")))
feuilles = json.load(open(FEUILLES_JSON))

DATE_RE = re.compile(r"\d{2}/\d{2}")
ZAR_YMIN, ZAR_YMAX = 9900, 14700


def norm(t):
    return re.sub(r"\s+", " ", (t or "")).strip().lower()


def dates_in(t):
    return set(DATE_RE.findall(t or ""))


def regime_flags(t):
    t = norm(t)
    return ("autoris" in t, "interdi" in t)


def is_result(w):
    t = w.get("texte") or ""
    y = w.get("y") or 0
    return (
        ZAR_YMIN <= y <= ZAR_YMAX
        and bool(DATE_RE.search(t))
        and bool(re.search(r"autoris|interdi", t, re.I))
    )


RESULTS = [w for w in ws if is_result(w)]


def type_key(tf):
    return {
        "type_ia": "type_Ia",
        "type_Ia": "type_Ia",
        "type_ib": "type_Ib",
        "type_Ib": "type_Ib",
        "type_ii": "type_II",
        "type_II": "type_II",
    }.get(tf, tf)


# Bandes de section ZAR (y des labels Type, derives de l'inspection du SVG).
# Chaque (section, type) -> y central approximatif de la ligne resultat.
# Le matcher affine ensuite par signature calendrier.
SECTION_OF = [
    ("cine_apres_0101", "apres_0101"),
    ("cie_apres_0101", "apres_0101"),
    ("cine_avant_3112", "avant_3112"),
    ("cie_avant_3112", "avant_3112"),
    ("culture_printemps", "cp"),
]
# bandes y par section (min,max) pour restreindre les candidats
BANDES = {
    "cp": (10100, 10500),
    "apres_0101": (10800, 12300),
    "avant_3112": (12350, 14100),
}


def section_for(ctx):
    sc = ctx.get("sous_culture", "")
    for key, sec in SECTION_OF:
        if sc == key:
            return sec
    return None


def expected_signature(regle):
    """(set dates, autorise, interdit, texte brut) depuis la regle YAML."""
    ds, a, i = set(), False, False
    raw = []
    for p in (regle or {}).get("periodes", []):
        for k in ("du", "au"):
            v = str(p.get(k, ""))
            if DATE_RE.fullmatch(v):
                ds.add(v)
        reg = p.get("regime", "")
        if "autoris" in reg:
            a = True
        if "interdi" in reg:
            i = True
        raw.append(f"{reg} {p.get('du','')}->{p.get('au','')}")
    return ds, a, i, " | ".join(raw)


def score(sig, w):
    ds_f, a_f, i_f, raw = sig
    t = w.get("texte") or ""
    ds_w = dates_in(t)
    a_w, i_w = regime_flags(t)
    s = 0.0
    if ds_f:
        inter = len(ds_f & ds_w)
        s += inter * 3.0
        if inter == 0:
            s -= 1.0
    if a_f == a_w:
        s += 0.6
    if i_f == i_w:
        s += 0.6
    if raw:
        s += SequenceMatcher(None, norm(raw)[:120], norm(t)[:120]).ratio() * 1.5
    return s


def collect_pc(yr, x_from, x_to):
    pcs = [
        w
        for w in ws
        if (w.get("texte") or "").strip().startswith(("PC", "PR", "PG"))
        and abs((w.get("y") or 0) - yr) < 90
        and x_from <= (w.get("x") or 0) <= x_to
    ]
    pcs.sort(key=lambda w: w.get("x") or 0)
    seen, out = set(), []
    for w in pcs:
        t = (w.get("texte") or "").strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return " · ".join(out)


report = []
enrich = {}
conf_counts = {"haute": 0, "moyenne": 0, "basse": 0}
ndone = 0

for f in feuilles:
    rid = f["regle_id"]
    if not rid:
        continue
    ctx = f["contexte"]
    sec = section_for(ctx)
    sig = expected_signature(f.get("regle"))

    # Candidats : resultats dans la bande de section (si connue), sinon tous.
    if sec in BANDES:
        ymin, ymax = BANDES[sec]
        cands = [w for w in RESULTS if ymin <= (w.get("y") or 0) <= ymax]
    else:
        cands = list(RESULTS)
    if not cands:
        report.append((rid, sec, "AUCUN CANDIDAT", None, "basse"))
        conf_counts["basse"] += 1
        continue

    scored = sorted(((score(sig, w), w) for w in cands), key=lambda p: -p[0])
    best_s, best = scored[0]
    second_s = scored[1][0] if len(scored) > 1 else -99
    if best_s >= 4.0 and (best_s - second_s) >= 0.8:
        conf = "haute"
    elif best_s >= 2.5:
        conf = "moyenne"
    else:
        conf = "basse"

    yr = best.get("y") or 0
    xr = best.get("x") or 0
    wr = best.get("w") or 700
    x_right = xr + wr + 1800  # marge pour PC a droite
    enrich[rid] = {
        "widget_id": best["id"],
        "resultat": (best.get("texte") or "").strip()[:500],
        "code_pc": collect_pc(yr, xr, x_right)[:300],
        "confiance": conf,
    }

    # Crop : contexte Type (x~4500) -> resultat -> PC.
    x_left = 4450
    W = min(x_right - x_left, 7000)
    hr = best.get("h") or 200
    H = max(360, hr + 180)
    Y = yr + hr / 2 - H / 2
    out_png = os.path.join(OUT, f"{rid}.png")
    r = subprocess.run(
        [
            "node",
            CROP,
            BOARD,
            out_png,
            f"{x_left:.0f}",
            f"{Y:.0f}",
            f"{W:.0f}",
            f"{H:.0f}",
            "0.8",
        ],
        capture_output=True,
        text=True,
    )
    ok = r.returncode == 0 and os.path.exists(out_png)
    note = f"y={yr:.0f} x={xr:.0f} score={best_s:.2f}(2nd {second_s:.2f}) | {(best.get('texte') or '')[:50]}"
    if not ok:
        note += " | CROP FAIL: " + r.stderr[-160:]
        conf = "basse"
    else:
        ndone += 1
    report.append((rid, sec, note, (x_left, Y, W, H), conf))
    conf_counts[conf] += 1
    print(f"[{conf}] {rid} -> {note}")

with open(os.path.join(HERE, "mapping_widget_ids_zar.json"), "w") as fh:
    json.dump(enrich, fh, ensure_ascii=False, indent=2)

with open(os.path.join(OUT, "_RAPPORT_ZAR.md"), "w") as fh:
    fh.write("# Rapport crops ZAR Grand Est\n\n")
    fh.write(f"Crops generes: {ndone} / {len(feuilles)} feuilles\n\n")
    fh.write(
        f"Confiance: haute={conf_counts['haute']} "
        f"moyenne={conf_counts['moyenne']} basse={conf_counts['basse']}\n\n"
    )
    fh.write(
        "| regle_id | section | confiance | note | crop |\n|---|---|---|---|---|\n"
    )
    for rid, sec, note, box, conf in report:
        boxs = f"{box[0]:.0f},{box[1]:.0f},{box[2]:.0f},{box[3]:.0f}" if box else "—"
        fh.write(f"| {rid} | {sec} | {conf} | {note.replace('|','/')} | {boxs} |\n")

print("\nDONE", ndone, conf_counts, "| enrich:", len(enrich))
sys.exit(0)
