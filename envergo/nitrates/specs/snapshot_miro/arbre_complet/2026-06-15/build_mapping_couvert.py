#!/usr/bin/env python3
"""Régénère `mapping_couvert.json` : associe chaque feuille-résultat
« couvert d'interculture » du YAML au widget Miro qui affiche son résultat.

Le widget-id = la valeur du deeplink `?moveToWidget=<id>` du board juriste.
But : remplacer les screenshots par des liens cliquables vers le board.

ENTRÉES :
  - widgets.json (ce dossier) : tous les widgets du board {id,x,y,w,h,scale,texte}
  - couvert_leaves.json (ce dossier) : les 113 feuilles couvert exportées du
    YAML actif via Django (chemin_ids, regle_id, contexte, periodes, textes).
    Régénéré par `dump_leaves.sh` (cf. en-tête de ce fichier).
  - ../2026-05-30/couvert_reference_svg.json : ANCIEN rapprochement (indice
    seulement, board d'une version antérieure → phrasé différent).

MÉTHODE (cf. mapping_couvert_rapport.md) :
  Le board n'est PAS une simple cascade colonne-par-colonne : un même chemin
  YAML mène à plusieurs widgets-résultat (sous-conditions IAA, note 5, ICPE).
  On matche donc par SIGNATURE plutôt que par position pure :
    1. BAND (y) déduite de la sous_culture (apres_0101 / avant_3112 / courte).
    2. SIGNATURE DATE : la paire de dates fixes JJ/MM de la période headline
       du YAML (ex 15/11→15/01) recherchée dans le texte du widget.
    3. REGIME headline : "Interdit du …" vs "Autorisé sous condition …".
    4. Indices phénologiques (implantation/destruction) pour la band avant_3112.
  Désambiguïsation finale par l'ancien svg_proche/svg_attendu et par
  cohérence x croissant avec les voisins de même (sous_culture,type).

CONFIANCE :
  - haute  : signature date+régime unique dans la band, 1 seul widget candidat.
  - moyenne: plusieurs widgets de même signature → choisi par proximité/voisins.
  - basse  : pas de texte figé (calculatrice à bornes phénologiques sans date
             fixe distinctive) ou candidats multiples non départageables →
             miro_widget_id="" + note explicative.

CORRECTIONS MANUELLES : voir le dict OVERRIDES en bas. Documenté au cas par cas.

USAGE :
  python3 build_mapping_couvert.py        # écrit mapping_couvert.json
  python3 build_mapping_couvert.py --dump  # affiche un diagnostic détaillé

Pour régénérer couvert_leaves.json (nécessite le conteneur Django up) :
  docker exec envergo_django_maindev sh -c '...manage.py shell -c "..."'
  (cf. dump_leaves.sh dans ce dossier).
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
WIDGETS = HERE / "widgets.json"
LEAVES = HERE / "couvert_leaves.json"
OLD_REF = HERE.parent / "2026-05-30" / "couvert_reference_svg.json"
OUT = HERE / "mapping_couvert.json"

# Bandes y du board couvert (déduites des en-têtes de section).
# y < 5900 = culture principale (ignoré).
BANDS = {
    "apres_0101": (5900, 12200),  # CINE détruit / CIE exporté après 01/01
    "avant_3112": (12200, 16900),  # CINE détruit / CIE récolté avant 31/12
    "courte": (16900, 18300),  # couvert d'interculture courte
}
SOUS_CULTURE_BAND = {
    "cie_apres_0101": "apres_0101",
    "cine_apres_0101": "apres_0101",
    "cie_avant_3112": "avant_3112",
    "cine_avant_3112": "avant_3112",
    "cie_courte": "courte",
    "cine_courte": "courte",
}


def norm(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


DATE_RE = re.compile(r"\b\d{2}/\d{2}\b")


def fixed_dates(s):
    """Dates fixes JJ/MM présentes dans une chaîne, dédupliquées, ordonnées."""
    return DATE_RE.findall(s or "")


def leaf_headline(leaf):
    """Période headline du YAML (1re période non masquée) -> (du, au, regime).

    Pour les feuilles courte (periodes vides) on retombe sur le texte.
    """
    ps = leaf.get("regle_periodes") or []
    visibles = [p for p in ps if not p.get("masque")]
    if not visibles:
        return None
    p = visibles[0]
    return (p.get("du"), p.get("au"), p.get("regime"))


def leaf_fixed_date_pair(leaf):
    """Paire (du, au) si les deux sont des dates fixes JJ/MM, sinon None."""
    h = leaf_headline(leaf)
    if not h:
        return None
    du, au, _ = h
    if du and au and DATE_RE.fullmatch(du) and DATE_RE.fullmatch(au):
        return (du, au)
    return None


def leaf_all_fixed_dates(leaf):
    """Toutes les dates fixes apparaissant dans les périodes (pour matcher
    les widgets calculatrice qui combinent plusieurs bornes datées)."""
    ps = leaf.get("regle_periodes") or []
    out = []
    for p in ps:
        for k in ("du", "au"):
            v = p.get(k)
            if v and DATE_RE.fullmatch(v):
                out.append(v)
    return out


def leaf_is_calculatrice_phenologique(leaf):
    """Calculatrice dont la période HEADLINE (1re non masquée) dépend de
    date_semis/date_destruction → pas de paire de dates fixes exploitable
    pour un match texte fiable.

    NB : on ignore les périodes `masque: true` (sous-clauses qui détaillent
    le rendu calendrier). Une feuille dont le headline est « 15/11 → 15/01 »
    reste matchable par texte même si des sous-périodes sont phénologiques.
    """
    if leaf.get("regle_type") != "calculatrice":
        return False
    ps = [p for p in (leaf.get("regle_periodes") or []) if not p.get("masque")]
    for p in ps:
        for k in ("du", "au"):
            v = p.get(k) or ""
            if "date_" in v:
                return True
    return False


def leaf_regime_label(leaf):
    """'interdit' / 'autorise' selon le régime de la 1re période visible."""
    h = leaf_headline(leaf)
    if not h:
        return None
    regime = h[2]
    if regime == "interdiction":
        return "interdit"
    if regime in ("autorisation_sous_condition", "libre"):
        return "autorise"
    return None


_REGIME_FR = {
    "interdiction": "Interdit",
    "autorisation_sous_condition": "Autorisé sous condition",
    "libre": "Autorisé",
}


def leaf_result_text(leaf):
    """Meilleur texte-résultat YAML disponible (pour yaml_texte).

    Priorité au texte rédigé (`texte`/`texte_condition`/`message`). À défaut
    (règles calculatrice qui ne portent que des `periodes`), on dérive une
    phrase lisible des périodes visibles, pour ne pas laisser le champ vide.
    """
    for k in ("regle_texte", "regle_texte_condition", "regle_message"):
        v = leaf.get(k)
        if v:
            return v
    ps = [p for p in (leaf.get("regle_periodes") or []) if not p.get("masque")]
    if ps:
        morceaux = []
        for p in ps:
            reg = _REGIME_FR.get(p.get("regime"), p.get("regime") or "")
            du, au = p.get("du"), p.get("au")
            morceaux.append(f"{reg} du {du} au {au}".strip())
        return " ; ".join(morceaux) + " (dérivé des périodes ; règle calculatrice)"
    return ""


# --- Texte-résultat courte (periodes vides => routage par texte de règle) ---
COURTE_RESULT_KEYWORDS = {
    # regle_id substring -> mot-clé attendu dans le widget
    "types_0_I_II": "apport autorise",
    "type_III_cine": "apport interdit",  # cine_courte type III
}


def main(dump=False):
    widgets = json.loads(WIDGETS.read_text())
    leaves = json.loads(LEAVES.read_text())
    old_ref = {r["chemin_yaml"]: r for r in json.loads(OLD_REF.read_text())}

    # Widgets de la zone couvert, indexés par band.
    couvert_widgets = [
        w
        for w in widgets
        if w["x"] is not None and w["y"] is not None and w["y"] >= 5900 and w["texte"]
    ]

    def widgets_in_band(band):
        lo, hi = BANDS[band]
        return [w for w in couvert_widgets if lo <= w["y"] < hi]

    rows = []
    for leaf in leaves:
        chemin = "/".join(leaf["chemin_ids"])
        rid = leaf.get("regle_id") or ""
        sc = leaf["contexte"].get("sous_culture")
        band = SOUS_CULTURE_BAND.get(sc)
        old = old_ref.get(chemin, {})
        yaml_texte = leaf_result_text(leaf)

        row = {
            "chemin_yaml": chemin,
            "regle_id": rid,
            "miro_widget_id": "",
            "svg_texte": "",
            "yaml_texte": yaml_texte,
            "confiance": "basse",
            "note": "",
        }

        if band is None:
            row["note"] = f"sous_culture inconnue ({sc}), band non déterminée."
            rows.append(row)
            continue

        cands = widgets_in_band(band)
        chosen, conf, note = match_leaf(leaf, sc, band, cands, old)
        if chosen:
            row["miro_widget_id"] = chosen["id"]
            row["svg_texte"] = chosen["texte"]
        row["confiance"] = conf
        row["note"] = note
        rows.append(row)

    # Corrections manuelles (overrides) appliquées en dernier.
    apply_overrides(rows, widgets)

    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    counts = {"haute": 0, "moyenne": 0, "basse": 0}
    for r in rows:
        counts[r["confiance"]] += 1
    print(f"écrit {OUT} : {len(rows)} feuilles")
    print(
        f"  haute={counts['haute']} moyenne={counts['moyenne']} basse={counts['basse']}"
    )
    if dump:
        for r in rows:
            print(
                f"[{r['confiance']:7}] {r['regle_id']:45} -> {r['miro_widget_id'] or '(rien)':20} "
                f"| {r['svg_texte'][:50]!r}"
            )
    return rows


def match_leaf(leaf, sc, band, cands, old):
    """Retourne (widget|None, confiance, note)."""
    rid = leaf.get("regle_id") or ""
    is_cie = sc.startswith("cie")

    # --- Cas BAND COURTE : routage par texte de règle (Apport autorisé/interdit) ---
    if band == "courte":
        return match_courte(leaf, sc, rid, cands)

    # --- Calculatrice phénologique : pas de texte figé fiable → basse ---
    pheno = leaf_is_calculatrice_phenologique(leaf)
    pair = leaf_fixed_date_pair(leaf)
    all_dates = leaf_all_fixed_dates(leaf)
    regime = leaf_regime_label(leaf)

    # --- Type III "après 01/01" : pas de widget dédié dans la band A --------
    # Cas structurel : le board ne dessine pas de feuille-résultat type III
    # distincte pour "CINE détruit/CIE exporté après 01/01". Les widgets
    # "Interdit du 01/07 au 30/06" et "01/07 ... au jour de l'implantation"
    # vivent dans la band avant_3112 (haut, y~12169-12443) — potentiellement
    # partagés. On reste honnête : basse, candidats en note.
    type_fert = (leaf["contexte"].get("type_fertilisant") or "").lower()
    if band == "apres_0101" and type_fert == "type_iii":
        return (
            None,
            "basse",
            (
                "Type III « après 01/01 » : aucune feuille-résultat dédiée dans la "
                "band A du board (les widgets « Interdit du 01/07 au 30/06 » id "
                "3458764674736757828 et « 01/07 ... au jour de l'implantation » id "
                "3458764674736757837/3458764674736757836 sont rangés en haut de la "
                "band avant_3112, possiblement partagés). À trancher visuellement / "
                "juriste (divergence type III déjà signalée dans cross_validation)."
            ),
        )

    if pair:
        # Signature = paire de dates fixes + régime headline. On cherche les
        # widgets de la band dont le texte contient les deux dates et dont le
        # début ("Interdit du" / "Autorisé sous condition") matche le régime.
        du, au = pair
        sig_cands = []
        for w in cands:
            t = norm(w["texte"])
            if du in w["texte"] and au in w["texte"]:
                head_interdit = t.startswith("interdit") or t.startswith("interdiction")
                head_autorise = t.startswith("autorise")
                if regime == "interdit" and head_interdit:
                    sig_cands.append(w)
                elif regime == "autorise" and head_autorise:
                    sig_cands.append(w)
                elif regime is None:
                    sig_cands.append(w)
        # Filtrer CINE-style (clause "implantation" / "Pas d'apport avant")
        # selon CIE/CINE quand c'est discriminant.
        if len(sig_cands) > 1:
            sig_cands = disambiguate_cie_cine(sig_cands, is_cie)
        # Confiance : calculatrice phénologique = jamais "haute" (le texte du
        # widget est figé mais le rendu simulateur dépend des dates saisies,
        # à recouper visuellement) ; règle interdiction/autorisation à texte
        # figé = "haute" si widget unique.
        if len(sig_cands) == 1:
            conf = "moyenne" if pheno else "haute"
            return (
                sig_cands[0],
                conf,
                (
                    f"Signature date {du}-{au} + régime {regime}, widget unique dans "
                    f"la band {band}."
                    + (" Calculatrice : rendu à recouper." if pheno else "")
                ),
            )
        if len(sig_cands) > 1:
            best = pick_by_old_ref(sig_cands, old) or sig_cands[0]
            ids = ",".join(w["id"] for w in sig_cands)
            # Le RÉSULTAT (période + régime) est identifié avec certitude ; seule
            # l'INSTANCE de widget parmi les doublons ICPE/IAA/note5 reste
            # incertaine. -> moyenne (texte dupliqué désambiguïsé de façon
            # plausible), widget proposé = meilleur recoupement ancien ref.
            return (
                best,
                "moyenne",
                (
                    f"Résultat sûr (période {du}-{au}, régime {regime}) mais "
                    f"{len(sig_cands)} widgets de même libellé dans band {band} "
                    f"(ids {ids}) : les sous-conditions (ICPE/IAA/note5/effluent) ne "
                    f"sont pas distinguables par le texte seul. Widget proposé = "
                    f"meilleur recoupement ancien ref — à confirmer visuellement."
                ),
            )
        # Pas de candidat exact → tenter via ancien ref texte
        viaold = pick_by_old_ref(cands, old)
        if viaold:
            return (
                viaold,
                "basse",
                (
                    f"Pas de widget band {band} avec dates {du}-{au}+{regime} ; "
                    f"rapproché via l'ancien svg_proche (board version antérieure, "
                    f"phrasé différent). À confirmer visuellement."
                ),
            )
        return (
            None,
            "basse",
            (
                f"Aucun widget band {band} ne porte la signature {du}-{au}+{regime}. "
                f"Calculatrice={pheno}. À vérifier visuellement sur le board."
            ),
        )

    # Pas de paire fixe (headline phénologique) : matcher sur l'ensemble des
    # dates fixes présentes + clause implantation. Cas typique : avant_3112.
    # Ces feuilles sont calculatrice à bornes phénologiques → confiance basse
    # par principe (le board fige un libellé, mais le rendu calendrier dépend
    # des dates ; rapprochement à valider visuellement, cf. cross_validation).
    if all_dates:
        sig_cands = []
        for w in cands:
            if all(d in w["texte"] for d in set(all_dates)):
                sig_cands.append(w)
        if len(sig_cands) > 1:
            sig_cands = disambiguate_cie_cine(sig_cands, is_cie)
        if len(sig_cands) == 1:
            return (
                sig_cands[0],
                "moyenne",
                (
                    f"Calculatrice phénologique ; matché par les dates fixes "
                    f"{sorted(set(all_dates))} (widget unique band {band}). Rendu "
                    f"calendrier à recouper visuellement au board."
                ),
            )
        if len(sig_cands) > 1:
            best = pick_by_old_ref(sig_cands, old) or sig_cands[0]
            ids = ",".join(w["id"] for w in sig_cands)
            return (
                best,
                "basse",
                (
                    f"Calculatrice phénologique ; {len(sig_cands)} widgets portent les "
                    f"dates {sorted(set(all_dates))} (ids {ids}). Désambiguïsation "
                    f"incertaine (sous-conditions non distinguables) → vérifier visuellement."
                ),
            )

    return (
        None,
        "basse",
        (
            "Feuille calculatrice sans date fixe distinctive (bornes phénologiques "
            "semis/destruction). Pas de match texte fiable ; comparer le calendrier "
            "rendu au board visuellement."
        ),
    )


def match_courte(leaf, sc, rid, cands):
    """Band courte (y>=16900) : 4 feuilles-résultat figées, identifiées de
    façon CERTAINE par lecture directe du board + code de prescription PC :

      CINE courte (« Non Exporté », en-tête y~17971)
        Types 0/I/II → « Apport autorisé »  id 3458764674736757634 [PC13]
        Type III      → « Apport interdit »   id 3458764674736757620
      CIE courte (« Exporté », en-tête y~18150)
        Types 0/I/II → « Apport autorisé »  id 3458764674736757619 [PC15]
        Type III      → « Apports interdits sauf entre le semis et les 15 j »
                        id 3458764674736757652 [PC15]

    Le PC (PC13=CINE, PC15=CIE) lève l'ambiguïté entre les deux « Apport
    autorisé ». Mapping en dur car la zone est petite, fixe et vérifiée.
    """
    is_cie = sc.startswith("cie")
    by_id = {w["id"]: w for w in cands}

    table = {
        ("cine", "types_0_I_II"): (
            "3458764674736757634",
            "cine_courte types 0/I/II → « Apport autorisé » [PC13] (board vérifié).",
        ),
        ("cine", "type_III"): (
            "3458764674736757620",
            "cine_courte type III → « Apport interdit » (board vérifié).",
        ),
        ("cie", "types_0_I_II"): (
            "3458764674736757619",
            "cie_courte types 0/I/II → « Apport autorisé » [PC15] (board vérifié).",
        ),
        ("cie", "type_III"): (
            "3458764674736757652",
            "cie_courte type III → « Apports interdits sauf entre le semis et les "
            "15 j » [PC15] (board en négatif, YAML en positif ; même périmètre).",
        ),
    }

    cle_type = (
        "types_0_I_II"
        if "types_0_I_II" in rid
        else ("type_III" if "type_III" in rid else None)
    )
    cle_sc = "cie" if is_cie else "cine"
    entry = table.get((cle_sc, cle_type))
    if not entry:
        return None, "basse", f"Courte : règle {rid} non reconnue (sc={sc})."
    wid, note = entry
    w = by_id.get(wid)
    if w:
        return w, "haute", note
    return None, "basse", f"Courte : widget {wid} attendu introuvable dans la band."


def disambiguate_cie_cine(cands, is_cie):
    """Filtre les candidats selon la sémantique CIE vs CINE.

    Heuristique : les feuilles-résultat CINE mentionnent souvent l'implantation
    (« 15 jours avant l'implantation », « Pas d'apport avant »), absente côté
    CIE (récolté → pas de phase d'implantation à protéger de la même façon).
    On n'applique le filtre que s'il ne vide pas la liste.
    """

    def is_cine_style(w):
        t = norm(w["texte"])
        return "implantation" in t or "pas d'apport avant" in t

    if is_cie:
        filt = [w for w in cands if not is_cine_style(w)]
    else:
        filt = [w for w in cands if is_cine_style(w)]
    return filt if filt else cands


def pick_by_old_ref(cands, old):
    """Choisit le candidat dont le texte recoupe le mieux l'ancien
    svg_attendu/svg_proche (board version antérieure → match approximatif)."""
    target = norm(old.get("svg_attendu") or old.get("svg_proche") or "")
    if not target or not cands:
        return None
    tgt_dates = set(fixed_dates(target))
    best, best_score = None, -1
    for w in cands:
        wt = norm(w["texte"])
        wd = set(fixed_dates(wt))
        # score = recouvrement des dates + amorce commune
        score = len(tgt_dates & wd)
        if target[:25] and target[:25] in wt:
            score += 2
        if score > best_score:
            best, best_score = w, score
    return best if best_score > 0 else None


# ─── Corrections manuelles ────────────────────────────────────────────────
# Appliquées après le matching automatique. Chaque entrée documente pourquoi.
# Clé = regle_id OU chemin_yaml (on tente les deux). Valeur = dict des champs
# à forcer (miro_widget_id, confiance, note). Laisser vide si le matcher fait
# déjà bien le travail — à compléter au fil de la validation visuelle Max.
OVERRIDES = {
    # exemple : "r_xxx": {"miro_widget_id": "3458...", "confiance": "haute",
    #                      "note": "Corrigé manuellement après vérif board."},
}


def apply_overrides(rows, widgets):
    by_id = {w["id"]: w for w in widgets}
    for r in rows:
        ov = OVERRIDES.get(r["regle_id"]) or OVERRIDES.get(r["chemin_yaml"])
        if not ov:
            continue
        if "miro_widget_id" in ov:
            r["miro_widget_id"] = ov["miro_widget_id"]
            w = by_id.get(ov["miro_widget_id"])
            if w:
                r["svg_texte"] = w["texte"]
        if "confiance" in ov:
            r["confiance"] = ov["confiance"]
        if "note" in ov:
            r["note"] = "[OVERRIDE manuel] " + ov["note"]


if __name__ == "__main__":
    main(dump="--dump" in sys.argv)
