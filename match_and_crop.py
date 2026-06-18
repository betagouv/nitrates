#!/usr/bin/env python3
import json
import os
import re
import subprocess
from difflib import SequenceMatcher

BASE = "/Users/max/Data/betagouv/dev/nitrates-140-capture/envergo/nitrates/specs/snapshot_miro/arbre_complet/2026-06-17"
BOARD = os.path.join(BASE, "board.svg")
OUT = os.path.join(BASE, "crops_named")
CROP = "/Users/max/Data/betagouv/dev/nitrates-140-capture/crop_svg_viewbox.mjs"
os.makedirs(OUT, exist_ok=True)

ws = json.load(open(os.path.join(BASE, "widgets.json")))
feuilles = json.load(open(os.path.join(BASE, "feuilles_couvert_textes.json")))

# Already validated crops -> do not overwrite
VALIDATED = {
    "r_cine_apres_0101_type_0_icpe_a",
    "r_cine_apres_0101_type_0_icpe_icpe_ed_q6_true",
    "r_cine_apres_0101_type_0_icpe_icpe_ed_q6_false",
    "r_cine_apres_0101_type_0_autre",
}

# ---- Type-label anchors per section (from widgets.json inspection) ----
# section -> {type_key: anchor_y}
ANCHORS = {
    "apres_0101": {  # x~5083 column, header "détruit ou exporté après 01/01"
        "type_0": 6240,
        "type_Ia": 7107,
        "type_Ib": 8457,
        "type_II": 10715,
        "type_III": 12265,
    },
    "avant_3112": {  # x~5467-5837, header "CINE détruit avant 31/12"
        "type_0": 12917,
        "type_Ia": 13820,
        "type_Ib": 14671,
        "type_II": 16394,
        "type_III": 17314,
    },
    "courte": {  # compressed block x~5499
        "type_0": 17403,
        "type_Ia": 17492,
        "type_Ib": 17581,
        "type_II": 17670,
        "type_III": 17760,
    },
}
# half-window (vertical) to scan around anchor, per section
BAND = {"apres_0101": 760, "avant_3112": 700, "courte": 60}

DATE_RE = re.compile(r"\d{2}/\d{2}")


def section_of(sc):
    if "apres_0101" in sc:
        return "apres_0101"
    if "avant_3112" in sc:
        return "avant_3112"
    if "courte" in sc:
        return "courte"
    return None


def type_key(tf):
    # normalize type_ia/type_Ia
    m = {
        "type_0": "type_0",
        "type_ia": "type_Ia",
        "type_Ia": "type_Ia",
        "type_ib": "type_Ib",
        "type_Ib": "type_Ib",
        "type_ii": "type_II",
        "type_II": "type_II",
        "type_iii": "type_III",
        "type_III": "type_III",
    }
    return m.get(tf, tf)


def norm(t):
    return re.sub(r"\s+", " ", (t or "")).strip().lower()


def dates_in(t):
    return DATE_RE.findall(t or "")


def regime_word(t):
    t = norm(t)
    if "interdiction" in t or "interdit" in t:
        interdit = True
    else:
        interdit = False
    if "autoris" in t:
        autorise = True
    else:
        autorise = False
    return autorise, interdit


def is_result_widget(t):
    t = t or ""
    return DATE_RE.search(t) and re.search(r"autoris|interdi", t, re.I)


def expected_signature(f):
    """Return (set_of_dates, autorise, interdit, raw_text)."""
    txt = (f.get("texte") or "").strip()
    if txt:
        ds = dates_in(txt)
        a, i = regime_word(txt)
        return set(ds), a, i, txt
    # derive from periodes
    ds = set()
    a = False
    i = False
    for p in f.get("periodes", []):
        for k in ("du", "au"):
            v = p.get(k, "")
            if DATE_RE.fullmatch(str(v) or ""):
                ds.add(v)
        reg = p.get("regime", "")
        if "autoris" in reg:
            a = True
        if "interdiction" in reg or "interdit" in reg:
            i = True
    raw = " | ".join(
        f"{p.get('regime','')} {p.get('du','')}->{p.get('au','')}"  # noqa: E231
        for p in f.get("periodes", [])
    )
    return ds, a, i, raw


def score(f_sig, w_text):
    ds_f, a_f, i_f, raw = f_sig
    ds_w = set(dates_in(w_text))
    a_w, i_w = regime_word(w_text)
    s = 0.0
    # date overlap is strongest
    if ds_f:
        inter = len(ds_f & ds_w)
        s += inter * 3.0
        # penalty for board having dates not in feuille only mildly
        if inter == 0:
            s -= 1.0
    # regime agreement
    if a_f == a_w:
        s += 0.6
    if i_f == i_w:
        s += 0.6
    # textual similarity on the visible result text
    if raw:
        s += SequenceMatcher(None, norm(raw)[:120], norm(w_text)[:120]).ratio() * 1.5
    return s


# index result widgets
results = [w for w in ws if is_result_widget(w.get("texte") or "")]


# branch label widgets (the plan_epandage branch text), used to disambiguate
def branch_labels():
    out = []
    for w in ws:
        t = norm(w.get("texte") or "")
        if t in ("à autorisation", "à enregistrement ou déclaration", "non concerné"):
            out.append(w)
    return out


BRANCHES = branch_labels()


def branch_kind(plan):
    p = (plan or "").lower()
    if p == "icpe_a":
        return "à autorisation"
    if p in ("icpe_ed", "icpe_d", "enregistrement"):
        return "à enregistrement ou déclaration"
    if p in ("non_concerne", "non"):
        return "non concerné"
    return None


def nearest_branch_y(anchor, half, kind):
    """y of branch label of given kind within band, else None."""
    cands = [
        w
        for w in BRANCHES
        if abs(w["y"] - anchor) <= half and norm(w["texte"]) == norm(kind)
    ]
    if not cands:
        return None
    cands.sort(key=lambda w: abs(w["y"] - anchor))
    return cands[0]["y"]


# PC code widgets
def pcs_near(yr, x_from, x_to):
    out = []
    for w in ws:
        t = (w.get("texte") or "").strip()
        if (
            t.startswith("PC")
            and abs(w["y"] - yr) < 90
            and x_from - 30 <= w["x"] <= x_to + 1600
        ):
            out.append(w)
    return out


report = []
ndone = 0
conf_counts = {"haute": 0, "moyenne": 0, "basse": 0}
# regle_id -> {widget_id, resultat, code_pc, confiance} pour l'ingestion DB
# (deeplink moveToWidget + bloc texte résultat + notes PC). Cf. carte #140.
enrich = {}


def collect_pc(yr, x_from, x_to):
    """Codes PC voisins du widget-résultat (texte des notes PC), de gauche à
    droite, concaténés. Sert à remplir `code_pc_miro`."""
    pcs = [
        w
        for w in ws
        if (w.get("texte") or "").strip().startswith(("PC", "PR", "PG"))
        and abs(w["y"] - yr) < 80
        and x_from <= w["x"] <= x_to
    ]
    pcs.sort(key=lambda w: w["x"])
    seen, out = set(), []
    for w in pcs:
        t = (w.get("texte") or "").strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return " · ".join(out)


for f in feuilles:
    rid = f["regle_id"]
    ctx = f["contexte"]
    sc = ctx.get("sous_culture", "")
    tf = type_key(ctx.get("type_fertilisant", ""))
    sec = section_of(sc)
    sig = expected_signature(f)
    ds_f, a_f, i_f, raw = sig

    if rid in VALIDATED:
        report.append((rid, "VALIDÉ (préexistant)", None, "haute"))
        conf_counts["haute"] += 1
        continue

    # ---- special handling: courte section (bottom block) ----
    if sec == "courte":
        best = None
        if sc == "cie_courte":
            if tf == "type_III":
                # Calculatrice / Apports interdits sauf ... PC15, y~18197
                best = next(
                    (
                        w
                        for w in ws
                        if abs(w["y"] - 18197) < 40
                        and "sauf entre le semis" in (w.get("texte") or "")
                    ),
                    None,
                )
                if best is None:
                    best = next(
                        (
                            w
                            for w in ws
                            if abs(w["y"] - 18019) < 30
                            and norm(w.get("texte") or "") == "apport interdit"
                        ),
                        None,
                    )
            else:
                best = next(
                    (
                        w
                        for w in ws
                        if abs(w["y"] - 17929) < 30
                        and norm(w.get("texte") or "") == "apport autorisé"
                    ),
                    None,
                )
        else:  # cine_courte
            if tf == "type_III":
                best = next(
                    (
                        w
                        for w in ws
                        if abs(w["y"] - 17760) < 30
                        and "01/07" in (w.get("texte") or "")
                    ),
                    None,
                )
            else:
                best = next(
                    (
                        w
                        for w in ws
                        if abs(w["y"] - 17403) < 30
                        and "go to CINE" in (w.get("texte") or "")
                    ),
                    None,
                )
        if best is None:
            report.append((rid, "COURTE: cible introuvable", None, "basse"))
            continue
        yr = best["y"]
        xr = best["x"]
        wr = best["w"] or 400
        # crop the whole courte block context: x from 4450 (headers) to PC right
        pcw = [
            w
            for w in ws
            if (w.get("texte") or "").strip().startswith("PC")
            and abs(w["y"] - yr) < 60
            and w["x"] > xr
        ]
        x_right = max([xr + wr] + [p["x"] + (p["w"] or 350) for p in pcw]) + 450
        X = 4450
        W = x_right - X
        H = 420
        Y = yr - 160
        enrich[rid] = {
            "widget_id": best["id"],
            "resultat": (best.get("texte") or "").strip(),
            "code_pc": collect_pc(yr, xr, x_right),
            "confiance": "moyenne",
        }
        out_png = os.path.join(OUT, f"{rid}.png")
        r = subprocess.run(
            [
                "node",
                CROP,
                BOARD,
                out_png,
                f"{X:.0f}",
                f"{Y:.0f}",
                f"{W:.0f}",
                f"{H:.0f}",
                "0.8",
            ],
            capture_output=True,
            text=True,
        )
        ok = r.returncode == 0 and os.path.exists(out_png)
        conf = "moyenne"
        note = f"COURTE y={yr:.0f} x={xr:.0f} | {(best.get('texte') or '')[:50]}"
        if not ok:
            note += " CROP FAIL " + r.stderr[-150:]
            conf = "basse"
        report.append((rid, note, (X, Y, W, H), conf))
        conf_counts[conf] += 1
        if ok:
            ndone += 1
        print(f"[{conf}] {rid} -> {note}")
        continue

    if sec is None or tf not in ANCHORS.get(sec, {}):
        report.append((rid, f"PAS DE BANDE (sec={sec}, tf={tf})", None, "basse"))
        continue
    anchor = ANCHORS[sec][tf]
    half = BAND[sec]
    # candidate result widgets in band, x>5200 (right of type col), x<13000
    cands = [
        w for w in results if abs(w["y"] - anchor) <= half and 5200 <= w["x"] <= 13500
    ]
    if not cands:
        report.append((rid, f"AUCUN CANDIDAT band y={anchor}±{half}", None, "basse"))
        continue
    # branch-y disambiguation: bias toward result widgets near the matching branch label
    bkind = branch_kind(ctx.get("plan_epandage"))
    by = nearest_branch_y(anchor, half, bkind) if bkind else None

    def total_score(w):
        s = score(sig, w.get("texte") or "")
        if by is not None:
            dy = abs(w["y"] - by)
            # strong bonus if within ~120px of branch row (same horizontal line), decaying
            s += max(0.0, 2.5 - dy / 120.0)
        return s

    scored = sorted(((total_score(w), w) for w in cands), key=lambda p: -p[0])
    best_s, best = scored[0]
    second_s = scored[1][0] if len(scored) > 1 else -99
    # confidence
    if best_s >= 5.5 and (best_s - second_s) >= 1.0:
        conf = "haute"
    elif best_s >= 3.5:
        conf = "moyenne"
    else:
        conf = "basse"

    yr = best["y"]
    xr = best["x"]
    wr = best["w"] if best["w"] else 700  # rich text default width
    # find PC codes to the right
    pcw = pcs_near(yr, xr + wr * 0.3, xr + wr)
    x_right = xr + wr
    if pcw:
        x_right = max(x_right, max(p["x"] + (p["w"] or 350) for p in pcw))
    x_right += 450  # margin for trailing icon/PC
    enrich[rid] = {
        "widget_id": best["id"],
        "resultat": (best.get("texte") or "").strip(),
        "code_pc": collect_pc(yr, xr, x_right),
        "confiance": conf,
    }
    # Left edge: include the Type/Q2 context at x=5040 when the result is not
    # too far right; otherwise (deep Type II branches) start nearer the result
    # so the crop stays readable instead of spanning the whole row.
    if xr > 7500:
        x_left = max(5040, xr - 2700)
    else:
        x_left = 5040
    W = x_right - x_left
    # vertical: center on band of the branch; rich boxes can be tall
    hr = best["h"] if best["h"] else 200
    cy = yr + hr / 2
    H = max(360, hr + 160)
    Y = cy - H / 2
    X = x_left
    ppu = 0.7
    # cap width so file not huge
    if W > 7000:
        W = 7000
    out_png = os.path.join(OUT, f"{rid}.png")
    cmd = [
        "node",
        CROP,
        BOARD,
        out_png,
        f"{X:.0f}",
        f"{Y:.0f}",
        f"{W:.0f}",
        f"{H:.0f}",
        str(ppu),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = r.returncode == 0 and os.path.exists(out_png)
    note = f"y={yr:.0f} x={xr:.0f} score={best_s:.2f}(2nd {second_s:.2f}) | {(best.get('texte') or '')[:55]}"
    if not ok:
        note += " | CROP FAIL: " + r.stderr[-200:]
        conf = "basse"
    report.append((rid, note, (X, Y, W, H), conf))
    conf_counts[conf] += 1
    if ok:
        ndone += 1
    print(f"[{conf}] {rid} -> {note}")

# write report
with open(os.path.join(OUT, "_RAPPORT.md"), "w") as fh:
    fh.write("# Rapport crops nommés — feuilles couvert/interculture\n\n")
    fh.write(f"Crops générés cette passe: {ndone} (hors 4 validés préexistants)\n\n")
    fh.write(
        f"Confiance: haute={conf_counts['haute']} moyenne={conf_counts['moyenne']} basse={conf_counts['basse']}\n\n"
    )
    fh.write("| regle_id | confiance | widget-résultat retenu | crop (X,Y,W,H) |\n")
    fh.write("|---|---|---|---|\n")
    for rid, note, box, conf in report:
        boxs = f"{box[0]:.0f},{box[1]:.0f},{box[2]:.0f},{box[3]:.0f}" if box else "—"
        note_clean = note.replace("|", "/")
        fh.write(f"| {rid} | {conf} | {note_clean} | {boxs} |\n")

# write enrichment mapping (regle_id -> widget_id / resultat / code_pc) pour
# l'ingestion DB du deeplink moveToWidget + texte résultat + notes PC.
with open(os.path.join(BASE, "mapping_widget_ids.json"), "w") as fh:
    json.dump(enrich, fh, ensure_ascii=False, indent=2)

print("\nDONE", ndone, conf_counts, "| enrich:", len(enrich))
