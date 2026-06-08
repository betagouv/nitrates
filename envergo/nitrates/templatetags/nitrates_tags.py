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


@register.simple_tag
def periode_phrase(periode: dict) -> str:
    """Formate une periode en phrase humaine pour le panneau resultat.

    Bornes fixes JJ/MM : `du 15/07 au 15/02`.
    Borne phenologique en debut : `de « derniere_coupe_luzerne » au 31/12`.
    Borne phenologique en fin : `du 15/07 au « brunissement_des_soies »`.

    Les guillemets francais autour des slugs phenologiques signalent
    visuellement a l'utilisateur que ce n'est pas une vraie date
    (cf. #88, retour Emma).
    """
    du = periode.get("du", "")
    au = periode.get("au", "")
    du_fixe = _est_borne_fixe(du)
    au_fixe = _est_borne_fixe(au)
    du_str = du if du_fixe else f"« {du} »"
    au_str = au if au_fixe else f"« {au} »"
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


_JOURS_SEMAINE_FR = [
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
]
_MOIS_LONGS_FR = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]


def _periode_couvre_today(periode: dict, today: date) -> bool:
    """Indique si la date `today` tombe dans la periode `du -> au`.

    Gere le cas pivot d'annee (ex 15/12 -> 15/01 traverse le 31/12).
    Periodes non parsables (evenements phenologiques) -> False (on ne sait
    pas projeter).
    """
    du = _parse_jjmm(periode.get("du", ""))
    au = _parse_jjmm(periode.get("au", ""))
    if du is None or au is None:
        return False
    j_du = _day_of_year(*du)  # annee agricole 0-indexe
    j_au = _day_of_year(*au)
    j_today = _day_of_year(today.day, today.month)
    if j_du <= j_au:
        return j_du <= j_today <= j_au
    # Pivot annee : couvre [j_du, fin] U [debut, j_au]
    return j_today >= j_du or j_today <= j_au


def statut_aujourdhui(regle, today: date | None = None) -> dict:
    """Calcule le statut effectif d'epandage a la date `today`.

    Pour chaque periode de la regle, regarde si `today` tombe dedans.
    Si oui, retourne le `regime` de la periode (ou fallback sur
    `regle.type`). Si dans aucune periode, retourne 'libre' (vert,
    autorise par defaut hors periode d'interdiction).

    Helper testable independamment de la date courante : pour les tests
    unitaires, passer `today=date(2026, 5, 7)`. En production, le
    templatetag passe `today=date.today()`.
    """
    if today is None:
        today = date.today()
    if regle is None:
        return {
            "code": "libre",
            "couleur": "vert",
            "libelle": "Autorisé",
            "periode_active": None,
        }
    regle_type = getattr(regle, "type", None) or ""
    periodes = getattr(regle, "periodes", None) or []
    for p in periodes:
        if _periode_couvre_today(p, today):
            regime = p.get("regime") or regle_type
            return {
                "code": regime,
                "couleur": _COULEUR_BADGE.get(regime, "gris"),
                "libelle": _LIBELLE_BADGE.get(regime, regime),
                "periode_active": {"du": p.get("du"), "au": p.get("au")},
            }
    # Hors de toute periode : on est en autorise par defaut.
    # Sauf si la regle est un type "global" (libre / non_applicable / etc.)
    # auquel cas le statut reflete le type global.
    if regle_type in ("libre", "non_applicable", "calculatrice", "a_completer"):
        return {
            "code": regle_type,
            "couleur": _COULEUR_BADGE.get(regle_type, "gris"),
            "libelle": _LIBELLE_BADGE.get(regle_type, regle_type),
            "periode_active": None,
        }
    return {
        "code": "libre",
        "couleur": "vert",
        "libelle": "Autorisé",
        "periode_active": None,
    }


_COULEUR_BADGE = {
    "interdiction": "rouge",
    "autorisation_sous_condition": "orange",
    "plafonnement": "orange",
    "libre": "vert",
    "non_applicable": "gris",
    "calculatrice": "orange",
    "a_completer": "gris",
}
_LIBELLE_BADGE = {
    "interdiction": "Interdit",
    "autorisation_sous_condition": "Autorisé sous condition",
    "plafonnement": "Plafonnement",
    "libre": "Autorisé",
    "non_applicable": "Ne s'applique pas",
    "calculatrice": "Calcul nécessaire",
    "a_completer": "À compléter",
}


def _format_jjmm_long(jjmm: str) -> str:
    """Convertit '15/12' en '15 décembre' (et '01/07' en '1er juillet').
    Retourne la chaîne brute si non parsable."""
    parsed = _parse_jjmm(jjmm)
    if parsed is None:
        return jjmm
    jour, mois = parsed
    jour_fmt = "1er" if jour == 1 else str(jour)
    return f"{jour_fmt} {_MOIS_LONGS_FR[mois - 1]}"


def construire_phrase_explicative(regle, today: date | None = None) -> str:
    """Construit une phrase auto contextuelle "aujourd'hui" a partir des
    periodes + regimes.

    Cas safe (gere ici) :
    - Regle libre / non_applicable / pas de periode : phrase generique.
    - 1 ou 2 periodes du meme regime, toutes parsables (JJ/MM) : phrase
      contextuelle qui indique le statut effectif du jour ET ce qui arrive
      ensuite. Format en mois longs ("15 décembre") plus naturel que "15/12".

    Cas non-safe (fallback sur _construire_phrase_brute) :
    - Regimes mixtes dans la meme regle (ex maïs irrigue borne souple, a
      clarifier dans la grammaire en backlog 2026-05-11).
    - Periodes avec evenement phenologique (du/au non parsable JJ/MM).

    Le parametre `today` est injectable pour les tests (defaut date.today()).
    """
    if regle is None:
        return ""
    if today is None:
        today = date.today()
    regle_type = getattr(regle, "type", None) or ""
    periodes = getattr(regle, "periodes", None) or []

    # Cas trivial : aucune periode -> on s'appuie sur le type global.
    if not periodes:
        if regle_type == "libre":
            return "L'épandage est autorisé toute l'année."
        if regle_type == "non_applicable":
            return "La directive nitrates ne s'applique pas."
        return _LIBELLE_BADGE.get(regle_type, "")

    parsed = []
    has_phenologique = False
    for p in periodes:
        if _parse_jjmm(p.get("du", "")) and _parse_jjmm(p.get("au", "")):
            regime = p.get("regime") or regle_type
            parsed.append((regime, p["du"], p["au"]))
        else:
            has_phenologique = True

    # Fallback brut si phenologique ou regimes mixtes : a traiter avec la
    # grammaire des bornes souples (backlog 2026-05-11).
    regimes = {r for r, _, _ in parsed}
    if has_phenologique or len(regimes) > 1:
        return _construire_phrase_brute(regle)

    if not parsed:
        return _LIBELLE_BADGE.get(regle_type, "")

    regime = next(iter(regimes))
    today_in_periode = any(
        _periode_couvre_today({"du": du, "au": au, "regime": r}, today)
        for r, du, au in parsed
    )

    morceaux = [
        f"du {_format_jjmm_long(du)} au {_format_jjmm_long(au)}" for _, du, au in parsed
    ]
    liste = " et ".join(morceaux)

    if regime == "interdiction":
        if today_in_periode:
            return (
                f"Aujourd'hui, l'épandage est interdit. "
                f"Cette période d'interdiction court {liste}."
            )
        return f"Aujourd'hui, l'épandage est autorisé. " f"Il sera interdit {liste}."
    if regime == "autorisation_sous_condition":
        if today_in_periode:
            return (
                f"Aujourd'hui, l'épandage est autorisé sous condition. "
                f"Régime applicable {liste}."
            )
        return (
            f"Aujourd'hui, l'épandage est autorisé. "
            f"Il sera soumis à conditions {liste}."
        )
    if regime == "plafonnement":
        if today_in_periode:
            return (
                f"Aujourd'hui, l'épandage est plafonné. " f"Plafond applicable {liste}."
            )
        return f"Aujourd'hui, l'épandage est autorisé. " f"Il sera plafonné {liste}."

    # Cas libre ou autre : phrase neutre, on liste les periodes connues.
    return f"L'épandage est autorisé. Périodes connues {liste}."


def _construire_phrase_brute(regle) -> str:
    """Phrase auto sans contexte temporel "aujourd'hui" -- fallback pour les
    cas non-safe (regimes mixtes ou periodes phenologiques). A enrichir
    quand la grammaire des bornes souples sera implementee (backlog
    2026-05-11)."""
    if regle is None:
        return ""
    regle_type = getattr(regle, "type", None) or ""
    periodes = getattr(regle, "periodes", None) or []
    if not periodes:
        return _LIBELLE_BADGE.get(regle_type, "")

    parsed = []
    for p in periodes:
        if _parse_jjmm(p.get("du", "")) and _parse_jjmm(p.get("au", "")):
            regime = p.get("regime") or regle_type
            parsed.append((regime, p["du"], p["au"]))
    if not parsed:
        return _LIBELLE_BADGE.get(regle_type, "")

    regimes = {r for r, _, _ in parsed}
    if len(regimes) == 1:
        regime = next(iter(regimes))
        verbe = {
            "interdiction": "L'épandage est interdit",
            "autorisation_sous_condition": "L'épandage est autorisé sous condition",
            "plafonnement": "L'épandage est plafonné",
        }.get(regime, "L'épandage")
        morceaux = [f"du {du} au {au}" for _, du, au in parsed]
        if len(morceaux) == 1:
            return f"{verbe} {morceaux[0]}."
        return f"{verbe} {' et '.join(morceaux)}."

    parts = []
    for regime, du, au in parsed:
        v = {
            "interdiction": "interdit",
            "autorisation_sous_condition": "autorisé sous condition",
            "plafonnement": "plafonné",
            "libre": "autorisé",
        }.get(regime, regime)
        parts.append(f"{v} du {du} au {au}")
    return "L'épandage est " + ", puis ".join(parts) + "."


def _formatter_date_fr(d: date) -> str:
    """Format 'mercredi 6 mai 2026' (jour de la semaine + jour + mois long
    + annee). Locales independent : on construit a la main pour garantir
    le rendu fr."""
    weekday = _JOURS_SEMAINE_FR[d.weekday()]
    mois = _MOIS_LONGS_FR[d.month - 1]
    return f"{weekday} {d.day} {mois} {d.year}"


@register.inclusion_tag("nitrates/fragments/_epandage_header.html")
def epandage_header(regle):
    """Rend le header du panneau resultat avec :
    - badge dynamique (rouge / orange / vert) selon le statut effectif
      a la date du jour
    - "en date du <jour de la semaine> <jour> <mois> <annee>"
    - phrase explicative auto-generee
    - 3 variantes UX swappables (test interactif), choix utilisateur
      stocke en localStorage. Le bouton de switch est temporaire,
      a retirer apres validation design.

    Cf. issue #28.
    """
    today = date.today()
    statut = statut_aujourdhui(regle, today=today)
    return {
        "regle": regle,
        "statut": statut,
        "today": today,
        "today_fr": _formatter_date_fr(today),
        "phrase": construire_phrase_explicative(regle, today=today),
    }


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
