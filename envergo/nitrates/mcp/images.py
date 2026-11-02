"""Images renvoyées aux assistants : calendrier d'épandage et carte de
localisation, en PNG (le type d'image que tous les clients MCP acceptent).

Le calendrier reprend la palette du calendrier du simulateur (calendrier.css)
pour que l'agriculteur retrouve le même code couleur que sur le site. La carte
pose les aires de captage numérotées sur le Plan IGN (tuiles WMTS publiques de
la Géoplateforme), pour qu'il puisse dire « je suis dans la zone 1 » sans
connaître ses coordonnées.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from io import BytesIO

import requests
from django.core.cache import cache
from PIL import Image, ImageDraw, ImageFont

# ─── Polices et couleurs ───────────────────────────────────────────────────

_POLICES = {
    False: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    True: "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
}


def _police(taille: int, gras: bool = False):
    try:
        return ImageFont.truetype(_POLICES[gras], taille)
    except OSError:
        # Poste sans DejaVu : police integree a Pillow (vectorielle depuis 10.1).
        return ImageFont.load_default(size=taille)


ENCRE = (22, 22, 22)
GRIS = (102, 102, 120)
TRAIT = (221, 221, 232)
BLEU = (0, 0, 145)
# Palette du calendrier du simulateur (--cal-*-fill / --cal-*-ink).
STYLE_REGIME = {
    "interdiction": {"fond": (253, 222, 222), "encre": (249, 90, 92)},
    "autorisation_sous_condition": {
        "fond": (253, 222, 222),
        "encre": (250, 122, 53),
        "hachures": True,
    },
    "plafonnement": {
        "fond": (253, 222, 222),
        "encre": (250, 122, 53),
        "hachures": True,
    },
    "libre": {"fond": (195, 250, 213), "encre": (75, 159, 108)},
    "non_applicable": {"fond": (238, 238, 238), "encre": (154, 154, 154)},
}
LEGENDE = [
    ("interdiction", "Épandage interdit"),
    ("autorisation_sous_condition", "Autorisé sous conditions"),
    ("libre", "Pas de période d'interdiction"),
]
MOIS = [
    "juil.",
    "août",
    "sept.",
    "oct.",
    "nov.",
    "déc.",
    "janv.",
    "févr.",
    "mars",
    "avr.",
    "mai",
    "juin",
]
DEBUT_ANNEE = date(2025, 7, 1)  # annee culturale non bissextile, 01/07 = jour 0
JOURS = 365


def _jour(jjmm: str) -> int:
    jour, mois = (int(x) for x in jjmm.split("/"))
    annee = 2025 if mois >= 7 else 2026
    return (date(annee, mois, jour) - DEBUT_ANNEE).days


def _png(image: Image.Image) -> bytes:
    sortie = BytesIO()
    image.save(sortie, format="PNG", optimize=True)
    return sortie.getvalue()


def _hachurer(draw, x0, y0, x1, y1, couleur, pas=7):
    """Hachures à 45° bornées au rectangle (pas de clip natif dans Pillow)."""
    x0, y0, x1, y1 = (round(v) for v in (x0, y0, x1, y1))
    for d in range(-(y1 - y0), x1 - x0, pas):
        xa, ya = x0 + max(d, 0), y0 + max(-d, 0)
        xb_, yb_ = x0 + min(d + (y1 - y0), x1 - x0), y0 + min(x1 - x0 - d, y1 - y0)
        draw.line([(xa, ya), (xb_, yb_)], fill=couleur, width=2)


# ─── Calendrier ────────────────────────────────────────────────────────────


def _couper(d, texte, police, largeur, lignes_max=2):
    """Découpe `texte` en au plus `lignes_max` lignes de `largeur` pixels."""
    lignes = [""]
    for mot in texte.split():
        essai = f"{lignes[-1]} {mot}".strip()
        if d.textlength(essai, font=police) <= largeur or not lignes[-1]:
            lignes[-1] = essai
        elif len(lignes) < lignes_max:
            lignes.append(mot)
        else:
            while d.textlength(lignes[-1] + "…", font=police) > largeur:
                lignes[-1] = lignes[-1][:-1]
            lignes[-1] = lignes[-1].rstrip(" ,") + "…"
            break
    return lignes


def calendrier_png(
    lignes: list[dict], date_marquee: str = "", titre: str = "", sous_titre: str = ""
) -> bytes:
    """Barres du calendrier sur l'année culturale (juillet -> juin).

    `lignes` : [{"libelle": str | None, "plages": [{du, au, regime}]}]. Une
    seule ligne : les dates de bascule sont écrites sous la barre."""
    largeur, droite = 1000, 30
    gauche = 330 if any(ligne.get("libelle") for ligne in lignes) else 30
    barre_l = largeur - gauche - droite
    mesure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    f_titre, f_sous = _police(20, True), _police(15)
    f_txt, f_petit, f_date = _police(14), _police(13), _police(13, True)
    lignes_titre = _couper(mesure, titre, f_titre, largeur - 60) if titre else []
    lignes_sous = (
        _couper(mesure, sous_titre, f_sous, largeur - 60) if sous_titre else []
    )
    haut_titre = 14 + 27 * len(lignes_titre) + 21 * len(lignes_sous) + 6
    # Bande reservee a l'etiquette de la date demandee, au-dessus des mois.
    bande_date = 22 if date_marquee else 0
    haut_ligne, ecart = 34, 12
    une_seule = len(lignes) == 1
    sous_barre = 30 if une_seule else 0
    hauteur = (
        haut_titre
        + bande_date
        + 28
        + len(lignes) * (haut_ligne + ecart)
        + sous_barre
        + 70
    )

    image = Image.new("RGB", (largeur, hauteur), "white")
    d = ImageDraw.Draw(image)
    y = 14
    for texte in lignes_titre:
        d.text((30, y), texte, font=f_titre, fill=ENCRE)
        y += 27
    for texte in lignes_sous:
        d.text((30, y), texte, font=f_sous, fill=GRIS)
        y += 21

    def x_de(jour):
        return gauche + round(jour / JOURS * barre_l)

    y = haut_mois = haut_titre + bande_date
    for i, nom in enumerate(MOIS):
        x = x_de(_jour(f"01/{(i + 6) % 12 + 1:02d}"))
        d.line(
            [(x, y + 22), (x, y + 28 + len(lignes) * (haut_ligne + ecart))],
            fill=TRAIT,
        )
        d.text((x + 4, y), nom, font=f_petit, fill=GRIS)
    y += 28

    for ligne in lignes:
        if ligne.get("libelle"):
            morceaux = _couper(d, ligne["libelle"], f_txt, gauche - 45)
            y_l = y + (9 if len(morceaux) == 1 else 0)
            for texte in morceaux:
                d.text((30, y_l), texte, font=f_txt, fill=ENCRE)
                y_l += 17
        if ligne.get("plages") is None:
            # Culture qui depend d'une precision : dessinee, jamais omise.
            gris = STYLE_REGIME["non_applicable"]
            d.rectangle([x_de(0), y, x_de(JOURS), y + haut_ligne], fill=gris["fond"])
            _hachurer(
                d, x_de(0), y, x_de(JOURS), y + haut_ligne, (225, 225, 225), pas=9
            )
            texte = "À préciser : " + (ligne.get("a_preciser") or "")
            texte = _couper(d, texte, f_petit, barre_l - 20, lignes_max=1)[0]
            d.text((x_de(0) + 10, y + 10), texte, font=f_petit, fill=ENCRE)
            y += haut_ligne + ecart
            continue
        for p in ligne["plages"]:
            style = STYLE_REGIME.get(p["regime"], STYLE_REGIME["non_applicable"])
            x0, x1 = x_de(_jour(p["du"])), x_de(_jour(p["au"]) + 1)
            d.rectangle([x0, y, x1, y + haut_ligne], fill=style["fond"])
            if style.get("hachures"):
                _hachurer(d, x0, y, x1, y + haut_ligne, style["encre"])
            d.line([(x0, y), (x1, y)], fill=style["encre"], width=3)
            d.line(
                [(x0, y + haut_ligne), (x1, y + haut_ligne)],
                fill=style["encre"],
                width=3,
            )
        if une_seule:
            for p in ligne["plages"][1:]:
                d.text(
                    (x_de(_jour(p["du"])) - 16, y + haut_ligne + 8),
                    p["du"],
                    font=f_petit,
                    fill=ENCRE,
                )
        y += haut_ligne + ecart
    bas_barres = y - ecart
    y += sous_barre

    if date_marquee:
        x = x_de(_jour(date_marquee) + 0.5)
        d.line([(x, haut_mois - 4), (x, bas_barres)], fill=BLEU, width=3)
        etiquette = f"Votre date : {date_marquee}"
        largeur_et = d.textlength(etiquette, font=f_date)
        xe = min(max(x - largeur_et / 2, gauche), largeur - droite - largeur_et)
        d.text((xe, haut_titre), etiquette, font=f_date, fill=BLEU)

    x = 30
    y += 14
    for regime, libelle in LEGENDE:
        style = STYLE_REGIME[regime]
        d.rectangle(
            [x, y, x + 28, y + 16], fill=style["fond"], outline=style["encre"], width=2
        )
        if style.get("hachures"):
            _hachurer(d, x, y, x + 28, y + 16, style["encre"], pas=6)
        d.text((x + 36, y), libelle, font=f_petit, fill=ENCRE)
        x += 36 + d.textlength(libelle, font=f_petit) + 28
    d.text(
        (30, y + 26),
        "Règles permanentes toute l'année : cours d'eau, pentes, sols gelés, "
        "enneigés ou détrempés.",
        font=f_petit,
        fill=GRIS,
    )
    return _png(image)


# ─── Carte ─────────────────────────────────────────────────────────────────

WMTS = (
    "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
    "&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&TILEMATRIXSET=PM"
    "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/png"
)
ORIGINE = 20037508.342789244
TUILE = 256
LARGEUR_MAX, HAUTEUR_MAX = 1000, 760
COULEURS_ZONES = [(206, 5, 0), (161, 0, 168), (224, 99, 0), (0, 120, 140)]


def _tuile(z, x, y):
    cle = f"nitrates-mcp-tuile:{z}:{x}:{y}"
    contenu = cache.get(cle)
    if contenu is None:
        try:
            r = requests.get(WMTS.format(z=z, x=x, y=y), timeout=5)
            r.raise_for_status()
            contenu = r.content
            cache.set(cle, contenu, 7 * 24 * 3600)
        except requests.RequestException:
            return None
    try:
        return Image.open(BytesIO(contenu)).convert("RGB")
    except OSError:
        return None


def _anneaux(geom):
    """Anneaux extérieurs d'un (Multi)Polygon GEOS, en coordonnées 3857."""
    polygones = [geom] if geom.geom_type == "Polygon" else list(geom)
    return [list(p.exterior_ring.coords) for p in polygones if p.geom_type == "Polygon"]


def carte_png(
    emprise, contour=None, zones=(), parcelle=None, point=None, titre: str = ""
) -> bytes:
    """Carte PNG sur fond Plan IGN.

    Toutes les géométries sont des GEOS en WGS84 (srid 4326) :
    `emprise` (zone à montrer), `contour` (commune), `zones` [(numero, geom)],
    `parcelle` (polygone cadastral), `point` (Point)."""
    e = emprise.transform(3857, clone=True).extent
    marge = 0.08 * max(e[2] - e[0], e[3] - e[1], 400)
    xmin, ymin, xmax, ymax = e[0] - marge, e[1] - marge, e[2] + marge, e[3] + marge
    # Le zoom le plus fort dont l'image tient dans le cadre maximal.
    z = 9
    for essai in range(17, 8, -1):
        r = 2 * ORIGINE / TUILE / 2**essai
        if (xmax - xmin) / r <= LARGEUR_MAX and (ymax - ymin) / r <= HAUTEUR_MAX:
            z = essai
            break
    res = 2 * ORIGINE / TUILE / 2**z
    # Les zones sont decoupees large autour de l'emprise : la coupe tombe hors
    # de l'image, on ne voit pas de bord rectiligne artificiel.
    cadre = emprise.envelope.buffer(
        0.6
        * max(
            emprise.extent[2] - emprise.extent[0],
            emprise.extent[3] - emprise.extent[1],
            0.01,
        )
    )
    zones = [(numero, geom.intersection(cadre)) for numero, geom in zones]

    def px(x, y):
        return (x + ORIGINE) / res, (ORIGINE - y) / res

    px0, py0 = px(xmin, ymax)
    px1, py1 = px(xmax, ymin)
    tx0, ty0, tx1, ty1 = (
        int(px0 // TUILE),
        int(py0 // TUILE),
        int(px1 // TUILE),
        int(py1 // TUILE),
    )
    fond = Image.new(
        "RGB", ((tx1 - tx0 + 1) * TUILE, (ty1 - ty0 + 1) * TUILE), (242, 242, 240)
    )
    coords = [(tx, ty) for tx in range(tx0, tx1 + 1) for ty in range(ty0, ty1 + 1)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for (tx, ty), tuile in zip(coords, pool.map(lambda c: _tuile(z, *c), coords)):
            if tuile is not None:
                fond.paste(tuile, ((tx - tx0) * TUILE, (ty - ty0) * TUILE))
    ox, oy = tx0 * TUILE, ty0 * TUILE
    image = fond.crop(
        (round(px0 - ox), round(py0 - oy), round(px1 - ox), round(py1 - oy))
    ).convert("RGBA")

    calque = Image.new("RGBA", image.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(calque)

    def a_lecran(x, y):
        """Coordonnées 3857 -> pixel de l'image recadrée."""
        u, v = px(x, y)
        return round(u - round(px0)), round(v - round(py0))

    def ecran(geom):
        g = geom.transform(3857, clone=True)
        return [[a_lecran(x, y) for x, y in anneau] for anneau in _anneaux(g)]

    f_num, f_leg = _police(22, True), _police(14)
    for i, (numero, geom) in enumerate(zones):
        couleur = COULEURS_ZONES[i % len(COULEURS_ZONES)]
        for anneau in ecran(geom):
            d.polygon(anneau, fill=couleur + (70,), outline=couleur + (255,), width=3)
    if contour is not None:
        for anneau in ecran(contour):
            d.line(anneau + [anneau[0]], fill=BLEU + (255,), width=4)
    if parcelle is not None:
        for anneau in ecran(parcelle):
            d.polygon(
                anneau, fill=(255, 210, 0, 110), outline=(20, 20, 20, 255), width=3
            )
    image = Image.alpha_composite(image, calque)
    d = ImageDraw.Draw(image)

    for i, (numero, geom) in enumerate(zones):
        couleur = COULEURS_ZONES[i % len(COULEURS_ZONES)]
        repere = geom.point_on_surface.transform(3857, clone=True)
        x, y = a_lecran(repere.x, repere.y)
        d.ellipse(
            [x - 17, y - 17, x + 17, y + 17], fill="white", outline=couleur, width=4
        )
        texte = str(numero)
        d.text(
            (x - d.textlength(texte, font=f_num) / 2, y - 14),
            texte,
            font=f_num,
            fill=couleur,
        )
    if point is not None:
        p = point.transform(3857, clone=True)
        x, y = a_lecran(p.x, p.y)
        d.ellipse(
            [x - 9, y - 9, x + 9, y + 9], fill=(20, 20, 20), outline="white", width=3
        )

    # Legende et attribution (licence ouverte : citer la source du fond).
    lignes = []
    if contour is not None:
        lignes.append((BLEU, "Limite de la commune", "trait"))
    for i, (numero, _) in enumerate(zones):
        lignes.append(
            (
                COULEURS_ZONES[i % len(COULEURS_ZONES)],
                f"Zone {numero} : aire de captage (règles renforcées)",
                "zone",
            )
        )
    if parcelle is not None:
        lignes.append(((20, 20, 20), "Votre parcelle", "zone"))
    if lignes or titre:
        h = 14 + 22 * len(lignes) + (26 if titre else 0)
        w = (
            30
            + max(
                [d.textlength(t, font=f_leg) for _, t, _ in lignes]
                + [d.textlength(titre, font=_police(15, True))]
            )
            + 20
        )
        d.rectangle([10, 10, 10 + w, 10 + h], fill=(255, 255, 255, 235), outline=TRAIT)
        y = 18
        if titre:
            d.text((20, y), titre, font=_police(15, True), fill=ENCRE)
            y += 26
        for couleur, texte, forme in lignes:
            if forme == "trait":
                d.line([(20, y + 8), (40, y + 8)], fill=couleur, width=4)
            else:
                d.rectangle([20, y + 1, 40, y + 15], fill=couleur, outline=couleur)
            d.text((48, y), texte, font=f_leg, fill=ENCRE)
            y += 22
    credit = "Fond : Plan IGN, Géoplateforme"
    lw, lh = image.size
    tw = d.textlength(credit, font=_police(12))
    d.rectangle([lw - tw - 14, lh - 22, lw, lh], fill=(255, 255, 255, 220))
    d.text((lw - tw - 7, lh - 19), credit, font=_police(12), fill=GRIS)
    return _png(image.convert("RGB"))
