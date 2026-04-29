"""Templatetags du simulateur nitrates.

Principalement le calendrier d'epandage : barre 12 mois colorisee selon
le type de la regle atteinte (interdiction rouge, libre vert, etc.) avec
overlay des periodes specifiques tirees du YAML.
"""

from datetime import date

from django import template

register = template.Library()


# Mapping regle.type -> couleur de fond de la barre.
# Pour les types qui ont une periode specifique (interdiction,
# plafonnement, autorisation_sous_condition), le fond reste vert (= autorise
# par defaut) et on overlay la periode interdite/conditionnelle. Pour les
# types globaux (libre / non_applicable / calculatrice), le fond entier
# represente le statut.
_FOND_PAR_TYPE = {
    "interdiction": "vert",  # vert par defaut, periode rouge en overlay
    "autorisation_sous_condition": "vert",  # idem, overlay orange
    "plafonnement": "vert",  # idem, overlay orange
    "libre": "vert",
    "non_applicable": "gris",
    "calculatrice": "orange",
    "a_completer": "gris",
}

# Couleur de la zone overlay selon le type.
_COULEUR_ZONE_PAR_TYPE = {
    "interdiction": "rouge",
    "autorisation_sous_condition": "orange",
    "plafonnement": "orange",
}

_LABEL_PAR_TYPE = {
    "interdiction": "Épandage interdit",
    "autorisation_sous_condition": "Sous conditions",
    "plafonnement": "Plafond",
    "libre": "Épandage autorisé",
    "non_applicable": "Ne s'applique pas",
    "calculatrice": "Calcul nécessaire",
    "a_completer": "À compléter",
}

# Annee agricole : on commence le 1er juillet pour que les periodes
# d'interdiction hivernales (typiquement 15/12 -> 15/01) tombent au
# centre de la barre. Cf. maquette designeuse.
_MOIS_LABELS = [
    "Juil",
    "Août",
    "Sep",
    "Oct",
    "Nov",
    "Déc",
    "Jan",
    "Fév",
    "Mar",
    "Avr",
    "Mai",
    "Juin",
]

# Annee non bissextile : 365 jours. Cumul des jours au debut de chaque mois,
# soit 0, 31, 59, 90, ... (utilise pour positionner les segments en pourcent).
_DAYS_PER_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
_TOTAL_DAYS = 365

# Decalage en jours du debut de l'annee agricole par rapport au 1er janvier.
# 1er juillet = jour 181 de l'annee civile (0-indexe).
_OFFSET_ANNEE_AGRICOLE = sum(_DAYS_PER_MONTH[:6])  # = 181


def _day_of_year(jour: int, mois: int) -> int:
    """Convertit (jour, mois) en jour de l'annee agricole (0-indexe).
    Jour 0 = 1er juillet ; jour 364 = 30 juin."""
    mois = max(1, min(12, mois))
    jour = max(1, min(_DAYS_PER_MONTH[mois - 1], jour))
    civil = sum(_DAYS_PER_MONTH[: mois - 1]) + (jour - 1)
    # Translate vers l'annee agricole
    return (civil - _OFFSET_ANNEE_AGRICOLE) % _TOTAL_DAYS


def _parse_jjmm(s: str) -> tuple[int, int] | None:
    """Parse 'JJ/MM' -> (jour, mois). Retourne None pour les valeurs non
    parsables (ex: 'brunissement_soies', evenement phenologique)."""
    try:
        jour, mois = s.split("/")
        return int(jour), int(mois)
    except (ValueError, AttributeError):
        return None


def _segment_interdit(periode: dict) -> list[tuple[float, float]]:
    """A partir d'une periode {du: 'JJ/MM', au: 'JJ/MM'}, retourne une liste
    de segments (start_pct, width_pct) sur l'annee.

    Cas normal (du < au) : 1 segment.
    Cas pivot d'annee (du > au, ex: 15/12 au 15/01) : 2 segments
    (15/12 au 31/12, puis 01/01 au 15/01).
    Cas non parsable (evenement phenologique) : pas de segment, on retourne
    une liste vide (le label texte sera affiche a part)."""
    du = _parse_jjmm(periode.get("du", ""))
    au = _parse_jjmm(periode.get("au", ""))
    if du is None or au is None:
        return []

    j_du = _day_of_year(*du)
    j_au = _day_of_year(*au)

    if j_du <= j_au:
        return [
            (
                j_du / _TOTAL_DAYS * 100,
                (j_au - j_du + 1) / _TOTAL_DAYS * 100,
            )
        ]
    # Pivot annee : 2 segments
    return [
        (j_du / _TOTAL_DAYS * 100, (_TOTAL_DAYS - j_du) / _TOTAL_DAYS * 100),
        (0.0, (j_au + 1) / _TOTAL_DAYS * 100),
    ]


@register.inclusion_tag("nitrates/fragments/_calendrier.html")
def calendrier_epandage(regle):
    """Rend un calendrier 12 mois colore avec les periodes interdites/
    conditionnelles overlays.

    `regle` : un dataclass `Resultat` ou un objet avec `type` et
    `periodes` (compatible).
    """
    if regle is None:
        return {"vide": True, "mois": _MOIS_LABELS}

    regle_type = getattr(regle, "type", None) or ""
    periodes = getattr(regle, "periodes", None) or []

    fond = _FOND_PAR_TYPE.get(regle_type, "gris")
    zone_couleur = _COULEUR_ZONE_PAR_TYPE.get(regle_type)
    label = _LABEL_PAR_TYPE.get(regle_type, regle_type or "—")

    # Construction des segments sur l'annee
    segments = []
    periodes_phenologiques = []  # pour celles non parsables (ex: brunissement_soies)
    for p in periodes:
        seg = _segment_interdit(p)
        if seg:
            for start, width in seg:
                segments.append({"start_pct": start, "width_pct": width})
        else:
            # Periode avec evenement phenologique -> on l'affiche en texte
            periodes_phenologiques.append(p)

    # Marqueur "aujourd'hui"
    today = date.today()
    today_pct = _day_of_year(today.day, today.month) / _TOTAL_DAYS * 100

    # Texte des dates limites a afficher sous la barre (ex: "15/12", "15/01")
    bornes = []
    for p in periodes:
        if _parse_jjmm(p.get("du", "")) and _parse_jjmm(p.get("au", "")):
            bornes.append({"label": p["du"], "pct": _segment_interdit(p)[0][0]})
            # Position de fin du dernier segment
            seg = _segment_interdit(p)
            if len(seg) == 1:
                end_pct = seg[0][0] + seg[0][1]
            else:
                # Cas pivot : la fin est sur le 2e segment
                end_pct = seg[1][0] + seg[1][1]
            bornes.append({"label": p["au"], "pct": end_pct})

    return {
        "vide": False,
        "mois": _MOIS_LABELS,
        "fond": fond,
        "zone_couleur": zone_couleur,
        "label": label,
        "segments": segments,
        "today_pct": today_pct,
        "bornes": bornes,
        "periodes_phenologiques": periodes_phenologiques,
        "regle_type": regle_type,
    }
