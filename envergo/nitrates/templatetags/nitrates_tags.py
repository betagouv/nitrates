"""Templatetags du simulateur nitrates.

Principalement le calendrier d'epandage : barre 12 mois colorisee selon
le type de la regle atteinte (interdiction rouge, libre vert, etc.) avec
overlay des periodes specifiques tirees du YAML.
"""

import os
import re
from datetime import date

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static

DATE_JJMM_RE = re.compile(r"^\d{2}/\d{2}$")

register = template.Library()


@register.simple_tag
def static_v(path: str) -> str:
    """Comme {% static %}, mais ajoute ?v=<mtime> en DEBUG pour casser le
    cache navigateur du `<script>`/`<link>` en dev. Indispensable pour les
    assets calendrier qu'on itere souvent : sans ca, le dev server + cache
    du navigateur servent une version perimee malgre un hard-refresh
    (cf. feedback_static_js_cache_dev). En prod, le ManifestStaticFilesStorage
    hashe deja les URLs -> ce tag retombe sur l'URL hashee, le ?v est inutile
    mais inoffensif (on ne l'ajoute qu'en DEBUG)."""
    url = static(path)
    if not settings.DEBUG:
        return url
    try:
        abs_path = finders.find(path)
        if abs_path and os.path.exists(abs_path):
            mtime = int(os.path.getmtime(abs_path))
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}v={mtime}"
    except Exception:
        pass
    return url


@register.filter
def get_item(d, key):
    """Filtre dict[key] pour le template (Django ne le supporte pas
    nativement quand la cle a des caracteres speciaux).

    Usage : {{ mon_dict|get_item:ma_cle }}
    Retourne None si la cle est absente. Tolere les QueryDict (request.GET).
    """
    if d is None:
        return None
    try:
        return d.get(key)
    except (AttributeError, TypeError):
        return None


def _est_borne_fixe(s: str) -> bool:
    """Une borne est fixe si elle a la forme JJ/MM. Sinon (slug type
    `brunissement_des_soies`, `derniere_coupe_luzerne`), c'est une
    borne phenologique flottante."""
    return isinstance(s, str) and len(s) == 5 and s[2] == "/"


def _libelle_phenologique(slug: str) -> str:
    """Resout un slug d'evenement phenologique vers son `libelle_public`
    (referentiels.yaml > evenements_phenologiques), ex
    `derniere_coupe_luzerne` -> "Dernière coupe de la luzerne".

    Fallback si le slug est absent du referentiel ou sans libelle_public :
    le slug rendu lisible (underscores -> espaces), jamais le snake_case brut
    (cf. #85)."""
    try:
        from envergo.nitrates.yaml_tree.loader import load_referentiels

        ev = (load_referentiels().get("evenements_phenologiques") or {}).get(slug)
        if ev and ev.get("libelle_public"):
            return ev["libelle_public"]
    except Exception:
        pass
    return str(slug).replace("_", " ")


def _minuscule_initiale(s: str) -> str:
    """Minuscule la 1ere lettre (le reste intact). Pour inserer un libelle
    capitalise au milieu d'une phrase sans casser les majuscules internes
    (ex "Brunissement des soies (maïs)" -> "brunissement des soies (maïs)")."""
    return s[:1].lower() + s[1:] if s else s


@register.simple_tag
def periode_phrase(periode: dict) -> str:
    """Formate une periode en phrase humaine pour le panneau resultat.

    Bornes fixes JJ/MM : `du 15/07 au 15/02`.
    Borne phenologique : on resout le slug vers son `libelle_public`
    lisible (cf. #85), ex `de la dernière coupe de la luzerne au 15/01`.
    Le prefixe passe de "du" a "de" quand la 1ere borne est phenologique.
    """
    du = periode.get("du", "")
    au = periode.get("au", "")
    du_fixe = _est_borne_fixe(du)
    au_fixe = _est_borne_fixe(au)
    # Le libelle phenologique est capitalise dans le referentiel (usage titre).
    # Insere en milieu de phrase ("de X au Y"), on minuscule sa 1ere lettre.
    du_str = du if du_fixe else _minuscule_initiale(_libelle_phenologique(du))
    au_str = au if au_fixe else _minuscule_initiale(_libelle_phenologique(au))
    prefixe = "du" if du_fixe else "de"
    return f"{prefixe} {du_str} au {au_str}"


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
    "mixte": "vert",  # fond vert, chaque periode rend son regime en overlay
}

# Couleur de la zone overlay selon le type / regime effectif.
# `libre` : pas d'overlay, c'est l'etat de fond. Les types `non_applicable`,
# `calculatrice`, `a_completer` ne devraient pas porter de periode (le fond
# represente le statut entier).
_COULEUR_ZONE_PAR_TYPE = {
    "interdiction": "rouge",
    "autorisation_sous_condition": "orange",
    "plafonnement": "orange",
}

_LABEL_PAR_TYPE = {
    "interdiction": "Calendrier d'épandage",
    "autorisation_sous_condition": "Calendrier d'épandage",
    "plafonnement": "Calendrier d'épandage",
    "libre": "Calendrier d'épandage",
    "non_applicable": "Ne s'applique pas",
    "calculatrice": "Calcul nécessaire",
    "a_completer": "À compléter",
    "mixte": "Calendrier d'épandage",
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
    """Parse 'JJ/MM' -> (jour, mois). Pour un evenement phenologique (ex:
    'brunissement_soies'), retombe sur la `date_calendrier` definie dans
    referentiels.yaml > evenements_phenologiques. Si rien ne matche, None.
    """
    if not s:
        return None
    try:
        jour, mois = s.split("/")
        return int(jour), int(mois)
    except (ValueError, AttributeError):
        pass
    # Fallback evenement phenologique -> date conventionnelle calendrier.
    try:
        from envergo.nitrates.yaml_tree.loader import load_referentiels

        ev = (load_referentiels().get("evenements_phenologiques") or {}).get(s)
        if ev and ev.get("date_calendrier"):
            jour, mois = ev["date_calendrier"].split("/")
            return int(jour), int(mois)
    except Exception:
        pass
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

    Chaque periode peut porter un champ `regime` optionnel : si
    present, c'est lui qui determine la couleur du segment (regime
    mixte) ; sinon on retombe sur le `type` global de la regle.
    """
    if regle is None:
        return {"vide": True, "mois": _MOIS_LABELS}

    regle_type = getattr(regle, "type", None) or ""
    periodes = getattr(regle, "periodes", None) or []

    fond = _FOND_PAR_TYPE.get(regle_type, "gris")
    label = _LABEL_PAR_TYPE.get(regle_type, regle_type or "—")

    # Construction des segments sur l'annee, chacun avec sa propre couleur.
    # Couleur par segment = couleur du `regime` de la periode si present,
    # sinon couleur du `type` global de la regle.
    segments = []
    periodes_phenologiques = []  # non parsables (ex: brunissement_soies)
    for p in periodes:
        regime_effectif = p.get("regime") or regle_type
        couleur = _COULEUR_ZONE_PAR_TYPE.get(regime_effectif)
        if not couleur:
            # `libre` (= pas d'overlay) ou type sans overlay : on n'affiche
            # rien pour cette periode (le fond suffit a porter le sens).
            continue
        seg = _segment_interdit(p)
        # is_flottant : au moins une borne est phenologique (date conventionnelle
        # arbitraire). On signale visuellement via un hachure dans le rendu pour
        # que l'utilisateur comprenne que la borne reelle depend du climat.
        is_flottant = bool(
            p.get("du") and not DATE_JJMM_RE.match(str(p["du"]))
        ) or bool(p.get("au") and not DATE_JJMM_RE.match(str(p["au"])))
        if seg:
            for start, width in seg:
                segments.append(
                    {
                        "start_pct": start,
                        "width_pct": width,
                        "couleur": couleur,
                        "is_flottant": is_flottant,
                    }
                )
        else:
            # Periode avec evenement phenologique -> on l'affiche en texte
            periodes_phenologiques.append(p)

    # Marqueur "aujourd'hui"
    today = date.today()
    today_pct = _day_of_year(today.day, today.month) / _TOTAL_DAYS * 100

    # Texte des dates limites a afficher sous la barre (ex: "15/12", "15/01").
    # Fusion des bornes pivot : si 2 periodes contiguës partagent une date
    # (ex 01/07->31/08 puis 31/08->31/01), on n'affiche qu'une fois "31/08".
    # Sans ca le rendu duplique le label avec une legere superposition.
    bornes_brutes = []
    for p in periodes:
        if _parse_jjmm(p.get("du", "")) and _parse_jjmm(p.get("au", "")):
            seg = _segment_interdit(p)
            bornes_brutes.append(
                {
                    "label": p["du"],
                    "pct": seg[0][0],
                    "is_phenologique": not DATE_JJMM_RE.match(str(p["du"])),
                }
            )
            if len(seg) == 1:
                end_pct = seg[0][0] + seg[0][1]
            else:
                # Cas pivot : la fin est sur le 2e segment
                end_pct = seg[1][0] + seg[1][1]
            bornes_brutes.append(
                {
                    "label": p["au"],
                    "pct": end_pct,
                    "is_phenologique": not DATE_JJMM_RE.match(str(p["au"])),
                }
            )

    # Deduplication par couple (label, pct~). 2 bornes a moins de 1% de
    # distance avec le meme label sont fusionnees en une seule.
    bornes = []
    for b in bornes_brutes:
        deja = next(
            (
                x
                for x in bornes
                if x["label"] == b["label"] and abs(x["pct"] - b["pct"]) < 1.0
            ),
            None,
        )
        if not deja:
            bornes.append(b)

    # Empilage deterministe : dates fixes (JJ/MM) toujours en row=0 (ligne du
    # haut, position canonique), dates phenologiques toujours en row=1 (ligne
    # du bas, avec trait diagonal qui pointe vers l'ancre). Garantit que le
    # rendu d'une date fixe est toujours au meme endroit, peu importe la
    # presence d'une date flottante a cote.
    for b in bornes:
        b["row"] = 1 if b.get("is_phenologique") else 0

    # Legende dynamique : on liste uniquement les categories presentes dans
    # le calendrier (interdit / autorise sous condition / plafonnement) et on
    # signale les segments a date flottante via une variante hachuree
    # "Autorise sous conditions" (cf. retour Louise 2026-05-13 : on retire
    # "phenologiques", vocabulaire trop technique pour un agriculteur).
    # Le "sinon interdit" est porte par le texte detaille ("Sinon, regle
    # de base —"), pas redondant dans la legende.
    legende = []
    couleurs_simples = set()
    couleurs_flottantes = set()
    for seg in segments:
        if seg.get("is_flottant"):
            couleurs_flottantes.add(seg["couleur"])
        else:
            couleurs_simples.add(seg["couleur"])
    libelle_legende = {
        "rouge": "Interdit",
        "orange": "Autorisé sous condition",
        "violet": "Plafond",
    }
    libelle_legende_flottant = {
        "orange": "Autorisé sous conditions",
        "rouge": "Interdit (dates flottantes)",
        "violet": "Plafond (dates flottantes)",
    }
    for couleur in ("rouge", "orange", "violet"):
        if couleur in couleurs_simples:
            legende.append(
                {
                    "couleur": couleur,
                    "label": libelle_legende.get(couleur, couleur),
                    "flottant": False,
                }
            )
        if couleur in couleurs_flottantes:
            legende.append(
                {
                    "couleur": couleur,
                    "label": libelle_legende_flottant.get(couleur, couleur),
                    "flottant": True,
                }
            )
    # Le fond "Autorise" (vert) est toujours present quand fond=vert.
    if fond == "vert":
        legende.append({"couleur": "vert", "label": "Autorisé", "flottant": False})

    return {
        "vide": False,
        "mois": _MOIS_LABELS,
        "fond": fond,
        "label": label,
        "segments": segments,
        "today_pct": today_pct,
        "bornes": bornes,
        "periodes_phenologiques": periodes_phenologiques,
        "regle_type": regle_type,
        "legende": legende,
    }
