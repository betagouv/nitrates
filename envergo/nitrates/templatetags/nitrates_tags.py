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


def _date_exemple_phenologique(slug: str) -> str | None:
    """Date conventionnelle (date_calendrier) d'un evenement phenologique,
    rendue lisible pour le sous-texte « Ici exemple au <date> » (#107).

    Ex `derniere_coupe_luzerne` -> "20 décembre" (le 1er du mois -> "1er ...").
    Retourne None si le slug n'a pas de date_calendrier resolue.
    """
    jjmm = _parse_jjmm(slug)
    if jjmm is None:
        return None
    # _date_lisible rend deja "1er" pour le 1er du mois (#159).
    return _date_lisible(*jjmm)


def _minuscule_initiale(s: str) -> str:
    """Minuscule la 1ere lettre (le reste intact). Pour inserer un libelle
    capitalise au milieu d'une phrase sans casser les majuscules internes
    (ex "Brunissement des soies (maïs)" -> "brunissement des soies (maïs)")."""
    return s[:1].lower() + s[1:] if s else s


@register.simple_tag
def periode_phrase(periode: dict) -> str:
    """Formate une periode en phrase humaine pour le panneau resultat.

    Bornes fixes : format date lisible unifie `du 15 juil. au 15 fév.`
    (#85, meme format que le calendrier dynamique).
    Borne phenologique : on resout le slug vers son `libelle_public`
    lisible (cf. #85), ex `de la dernière coupe de la luzerne au 15 jan.`.
    Le prefixe passe de "du" a "de" quand la 1ere borne est phenologique.
    """
    du = periode.get("du", "")
    au = periode.get("au", "")
    du_fixe = _est_borne_fixe(du)
    au_fixe = _est_borne_fixe(au)
    # Borne fixe -> date lisible "15 juil.". Borne phenologique -> libelle
    # public, minuscule car insere en milieu de phrase ("de X au Y").
    du_str = (
        _date_lisible(*_parse_jjmm(du))
        if du_fixe
        else _minuscule_initiale(_libelle_phenologique(du))
    )
    au_str = (
        _date_lisible(*_parse_jjmm(au))
        if au_fixe
        else _minuscule_initiale(_libelle_phenologique(au))
    )
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

# Verbe du tooltip de zone selon sa couleur (#134), aligne sur la legende.
_VERBE_ZONE = {
    "rouge": "Interdit",
    "orange": "Autorisé sous conditions",
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
# Labels alignes EXACTEMENT sur le calendrier dynamique (calculatrice-
# calendrier.js : MOIS_AGRICOLES) pour un rendu coherent entre les deux
# calendriers (#134) : abreviations courtes "Aoû / Sept / Jui" plutot que
# "Août / Sep / Juin".
_MOIS_LABELS = [
    "Juil",
    "Aoû",
    "Sept",
    "Oct",
    "Nov",
    "Déc",
    "Jan",
    "Fév",
    "Mar",
    "Avr",
    "Mai",
    "Jui",
]

# Initiales, meme ordre agricole. Affichees a la place des labels 3 lettres
# sur mobile (#177, cf. MOIS_AGRICOLES_COURTS cote JS) : sur petit ecran les
# abreviations se chevauchaient. Exposees via l'attribut data-court, le CSS
# bascule label <-> initiale selon la largeur.
_MOIS_COURTS = [m[0] for m in _MOIS_LABELS]

# Paires (label, initiale) pretes a boucler dans le template.
_MOIS_PAIRES = list(zip(_MOIS_LABELS, _MOIS_COURTS))

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


# Abreviations de mois alignees sur le calendrier dynamique (JS
# calculatrice-calendrier.js : MOIS_AGRICOLES). Format "15 juil.", "15 aoû.".
# Index = mois civil 1..12 -> abreviation. On unifie ce format partout (#85).
# Mois en toutes lettres (#159, maquette designeuse) : les dates de periode
# sous le calendrier sont ecrites en clair ("15 novembre"), pas en abrege.
_MOIS_COMPLET = {
    1: "janvier",
    2: "février",
    3: "mars",
    4: "avril",
    5: "mai",
    6: "juin",
    7: "juillet",
    8: "août",
    9: "septembre",
    10: "octobre",
    11: "novembre",
    12: "décembre",
}


def _date_lisible(jour: int, mois: int) -> str:
    """(jour, mois) civil -> "15 novembre" (jour + mois en toutes lettres, #159).
    Le 1er du mois est rendu "1er" (ex "1er février")."""
    jour_fmt = "1er" if jour == 1 else str(jour)
    return f"{jour_fmt} {_MOIS_COMPLET.get(mois, str(mois))}"


def _jour_agricole_to_date(j: int) -> tuple[int, int]:
    """Jour agricole 0-indexe (0 = 1er juillet) -> (jour, mois) civil."""
    civil = (j + _OFFSET_ANNEE_AGRICOLE) % _TOTAL_DAYS
    mois = 0
    while civil >= _DAYS_PER_MONTH[mois]:
        civil -= _DAYS_PER_MONTH[mois]
        mois += 1
    return civil + 1, mois + 1


def _plages_autorisation(periodes, regle_type: str) -> list[tuple[int, int]]:
    """Calcule les plages de jours PUREMENT autorises (le vert) = complement
    sur l'annee des periodes interdiction + autorisation_sous_condition.

    - Les bornes phenologiques sont projetees sur leur date_calendrier
      (via _parse_jjmm), comme les zones dessinees sur la barre.
    - Gere le wrap de l'annee agricole (juillet->juin) : une plage autorisee
      qui enjambe le 30 juin / 1er juillet est rendue continue.

    Retourne une liste de (jour_debut_agricole, jour_fin_agricole) inclusifs.
    """
    occupe = [False] * _TOTAL_DAYS
    for p in periodes or []:
        regime = (p.get("regime") or regle_type) or ""
        if regime not in ("interdiction", "autorisation_sous_condition"):
            continue
        du = _parse_jjmm(p.get("du", ""))
        au = _parse_jjmm(p.get("au", ""))
        if du is None or au is None:
            continue
        j_du = _day_of_year(*du)
        j_au = _day_of_year(*au)
        if j_du <= j_au:
            for i in range(j_du, j_au + 1):
                occupe[i] = True
        else:  # wrap d'annee
            for i in range(j_du, _TOTAL_DAYS):
                occupe[i] = True
            for i in range(0, j_au + 1):
                occupe[i] = True

    # Plages de jours libres (non occupes), en ordre agricole.
    plages = []
    i = 0
    while i < _TOTAL_DAYS:
        if occupe[i]:
            i += 1
            continue
        debut = i
        while i < _TOTAL_DAYS and not occupe[i]:
            i += 1
        plages.append((debut, i - 1))

    # Fusion du wrap : si la 1ere plage commence au jour 0 et la derniere
    # finit au jour 364, c'est une seule plage continue a cheval sur juillet.
    if len(plages) >= 2 and plages[0][0] == 0 and plages[-1][1] == _TOTAL_DAYS - 1:
        premiere = plages.pop(0)
        derniere = plages.pop(-1)
        plages.append((derniere[0], premiere[1]))

    return plages


def _joindre_plages_fr(plages: list[tuple[int, int]]) -> str:
    """Formate les plages [(j_debut, j_fin), ...] en une phrase francaise :
    1 plage  -> "du A au B"
    2 plages -> "du A au B et du C au D"
    3+       -> "du A au B, du C au D et du E au F"
    """
    morceaux = []
    for debut, fin in plages:
        d = _date_lisible(*_jour_agricole_to_date(debut))
        f = _date_lisible(*_jour_agricole_to_date(fin))
        morceaux.append(f"du {d} au {f}")
    if not morceaux:
        return ""
    if len(morceaux) == 1:
        return morceaux[0]
    return ", ".join(morceaux[:-1]) + " et " + morceaux[-1]


@register.simple_tag
def periode_autorisation_phrase(regle) -> str:
    """Phrase d'une seule ligne listant les plages d'autorisation pure (vert)
    d'une regle, ou "" si l'epandage n'est jamais purement autorise.

    Ex : "du 1er fév. au 14 oct." ; "du 16 jan. au 14 oct. et du 16 nov. au
    14 déc.". Utilise sous le calendrier statique (#85)."""
    if regle is None:
        return ""
    regle_type = getattr(regle, "type", None) or ""
    periodes = getattr(regle, "periodes", None) or []
    plages = _plages_autorisation(periodes, regle_type)
    return _joindre_plages_fr(plages)


# Libelle de puce par regime effectif (liste des periodes datees, #85).
_LABEL_PERIODE = {
    "autorisation_sous_condition": "Autorisé sous conditions",
    "interdiction": "Interdiction",
    "plafonnement": "Plafond",
}
# Ordre d'affichage des puces (du moins au plus restrictif, pour s'aligner sur
# le recap des cultures principales) : autorisation sous condition, plafond,
# interdiction. L'autorisation pure (vert) ouvre la liste, geree a part.
_ORDRE_REGIME = ["autorisation_sous_condition", "plafonnement", "interdiction"]


# Titre de section (#159, wording Emma : "Période d'interdiction", etc.).
_SECTION_TITRE = {
    "interdiction": "Période d’interdiction",
    "autorisation_sous_condition": "Période d’autorisation sous condition",
    "plafonnement": "Période de plafonnement",
}


# PC « plafond » (PC12 à PC16, abus de langage). CR 2026-08 (point juristes) :
# ces « codes » ne sont PAS de vraies prescriptions conditionnées. Le fait
# qu'une PC soit un plafond est désormais porté par un CHAMP `plafond` du
# référentiel CodePrescription (booléen, éditable en admin), et NON plus déduit
# de l'identifiant par regexp. Le référentiel `codes_prescription` (dict
# {slug: {..., "plafond": True}}) est en scope dans les templates ; on le passe
# aux tags pour résoudre l'attribut.
#
# Conséquences d'affichage d'un plafond :
#   - rendu INLINE sous le calendrier (pas dans le drawer des conditions) ;
#   - si TOUTES les PC d'une règle sont des plafonds, ses périodes
#     « autorisation sous condition » sont peintes en VERT (autorisé) — le
#     plafond s'appliquant de toute façon sur toute la période autorisée.


def _est_plafond(cp, referentiel) -> bool:
    """True si le slug de PC `cp` est marqué `plafond` dans le référentiel
    `codes_prescription` (dict {slug: data}). `data` est un dict en runtime,
    mais peut être un objet (SimpleNamespace) dans certains contextes de test :
    on tolère les deux formes."""
    if not cp or not referentiel:
        return False
    data = referentiel.get(str(cp))
    if data is None:
        return False
    if isinstance(data, dict):
        return bool(data.get("plafond"))
    return bool(getattr(data, "plafond", False))


@register.filter
def est_pc_plafond_couvert(cp, referentiel=None) -> bool:
    """True si `cp` est une PC de plafond (champ `plafond` du référentiel)."""
    return _est_plafond(cp, referentiel)


@register.simple_tag
def codes_prescription_plafond_couvert(regle, referentiel=None) -> list:
    """Sous-liste des codes_prescription de `regle` qui sont des plafonds
    (a rendre INLINE sous le calendrier)."""
    codes = getattr(regle, "codes_prescription", None) or []
    return [cp for cp in codes if _est_plafond(cp, referentiel)]


@register.simple_tag
def codes_prescription_hors_plafond(regle, referentiel=None) -> list:
    """Sous-liste des codes_prescription de `regle` qui NE sont PAS des plafonds
    (a rendre dans le drawer conditions, #271)."""
    codes = getattr(regle, "codes_prescription", None) or []
    return [cp for cp in codes if not _est_plafond(cp, referentiel)]


@register.simple_tag
def regle_uniquement_plafonds(regle, referentiel=None) -> bool:
    """True si la règle a au moins une PC et que TOUTES ses PC sont des plafonds.
    Dans ce cas, les périodes « autorisation sous condition » de la règle sont en
    réalité des périodes autorisées (le plafond s'applique de toute façon) et
    doivent être peintes en VERT (CR 2026-08)."""
    codes = getattr(regle, "codes_prescription", None) or []
    if not codes:
        return False
    return all(_est_plafond(cp, referentiel) for cp in codes)


@register.simple_tag
def calculatrice_data_json(regle, referentiel=None) -> dict:
    """Dict JSON de la regle calculatrice (couvert) ENRICHI de l'info plafond,
    pour le calendrier dynamique (calculatrice-calendrier.js).

    On ajoute deux cles au `to_json_dict` : `codes_prescription_plafond` (la
    sous-liste des slugs de PC marques `plafond` dans le referentiel) et
    `tous_plafonds` (True si toutes les PC de la regle sont des plafonds -> ses
    periodes ASC sont peintes en vert cote JS). Ainsi le JS n'a plus besoin de
    connaitre les identifiants de PC : il lit le champ, comme le back."""
    base = regle.to_json_dict() if regle is not None else {}
    codes = getattr(regle, "codes_prescription", None) or []
    plafonds = [cp for cp in codes if _est_plafond(cp, referentiel)]
    base["codes_prescription_plafond"] = plafonds
    base["tous_plafonds"] = bool(codes) and len(plafonds) == len(codes)
    return base


@register.simple_tag
def drawer_conditions_a_du_contenu(regle, referentiel=None) -> bool:
    """True si le drawer « conditions » a quelque chose a montrer : au moins une
    PC HORS plafond, ou une note. Les PC plafond etant rendues inline sous le
    calendrier, une regle qui n'a QUE des PC plafond ne doit PAS afficher le lien
    / drawer (#271, CR 2026-08)."""
    if regle is None:
        return False
    if getattr(regle, "note", None):
        return True
    return len(codes_prescription_hors_plafond(regle, referentiel)) > 0


@register.simple_tag
def nb_periodes_sous_condition(regle) -> int:
    """Nombre de periodes « autorisation sous condition » d'une regle (#271).

    Sert a accorder le libelle du bouton du drawer conditions (« cette periode »
    vs « ces periodes »). On compte les periodes dont le regime effectif est
    autorisation_sous_condition (regime explicite ou type de la regle).
    """
    if regle is None:
        return 0
    regle_type = getattr(regle, "type", None) or ""
    periodes = getattr(regle, "periodes", None) or []
    return sum(
        1
        for p in periodes
        if (p.get("regime") or regle_type) == "autorisation_sous_condition"
    )


@register.simple_tag
def periodes_par_section(regle, referentiel=None) -> list[dict]:
    """Recap des periodes GROUPE PAR SECTION pour le calendrier statique (#159).

    Structure (une section par regime present, ordre du moins au plus
    restrictif ; l'autorisation pure ouvre la liste) :

    [{"titre": "Autorisé", "periodes": [{"phrase": "du ... au ...",
                                          "justification": None}]},
     {"titre": "Autorisé sous conditions", "periodes": [...]},
     {"titre": "Interdiction",
      "periodes": [{"phrase": "du 15 novembre au 15 janvier",
                    "justification": "Interdit du 15/11 au 15/01."}]}]

    `justification` = texte_condition de la REGLE (une seule par regle, #159 :
    on reutilise l'existant sans toucher au schema YAML). Rendue par le
    template dans un tooltip ⓘ. On ne l'attache qu'aux sections interdiction /
    autorisation sous condition (l'autorisation pure n'a pas de justification).
    """
    if regle is None:
        return []
    regle_type = getattr(regle, "type", None) or ""
    periodes = getattr(regle, "periodes", None) or []
    justification = getattr(regle, "texte_condition", None) or None

    # CR 2026-08 : regle 100% plafond -> les periodes ASC deviennent des
    # periodes autorisees (vert). On recatalogue leur regime en autorisation
    # pure pour qu'elles rejoignent la section « Autorisé » (et non « Autorisé
    # sous conditions »), en coherence avec le calendrier peint en vert.
    tous_plafonds = regle_uniquement_plafonds(regle, referentiel)

    sections = []

    # Autorisation pure (vert) : premiere section, sans justification. Sur une
    # regle 100% plafond, les periodes ASC sont ajoutees ici (elles sont
    # autorisees, le plafond s'appliquant de toute facon).
    autorisation = periode_autorisation_phrase(regle)
    puces_autorisation = []
    if autorisation:
        puces_autorisation.append({"phrase": autorisation, "justification": None})
    if tous_plafonds:
        for p in sorted(
            (
                p
                for p in periodes
                if (p.get("regime") or regle_type) == "autorisation_sous_condition"
            ),
            key=lambda p: (
                _day_of_year(*_parse_jjmm(p.get("du", "")))
                if _parse_jjmm(p.get("du", ""))
                else float("inf")
            ),
        ):
            puces_autorisation.append(
                {"phrase": periode_phrase(p), "justification": None}
            )
    if puces_autorisation:
        sections.append(
            {"titre": "Période d’autorisation", "periodes": puces_autorisation}
        )

    # Tri des periodes d'un meme regime par jour agricole de debut (#224) :
    # sans ca, plusieurs periodes du meme regime (ex 2 interdictions d'une regle
    # mixte) s'affichaient dans l'ordre du YAML, pas dans l'ordre du calendrier
    # (juillet->juin). On ordonne sur l'index agricole du `du` ; une borne non
    # parsable (event sans date_calendrier) est repoussee en fin (float inf).
    def _rang_agricole(p) -> float:
        jjmm = _parse_jjmm(p.get("du", ""))
        return _day_of_year(*jjmm) if jjmm else float("inf")

    for regime in _ORDRE_REGIME:
        # Regle 100% plafond : les periodes ASC ont deja ete versees dans la
        # section « Autorisé » ci-dessus, on ne les re-liste pas ici.
        if tous_plafonds and regime == "autorisation_sous_condition":
            continue
        periodes_regime = sorted(
            (p for p in periodes if (p.get("regime") or regle_type) == regime),
            key=_rang_agricole,
        )
        puces = [
            {
                "phrase": periode_phrase(p),
                "justification": justification,
            }
            for p in periodes_regime
        ]
        if puces:
            sections.append({"titre": _SECTION_TITRE[regime], "periodes": puces})

    return sections


@register.simple_tag
def periodes_datees(regle) -> list[dict]:
    """[DEPRECATED, conserve pour compat tests] Liste plate des puces datees.
    Prefere `periodes_par_section` (#159). Ordre : interdiction -> plafond ->
    autorisation sous condition -> autorisation pure.
    """
    if regle is None:
        return []
    regle_type = getattr(regle, "type", None) or ""
    periodes = getattr(regle, "periodes", None) or []

    puces = []
    for regime in _ORDRE_REGIME:
        for p in periodes:
            if (p.get("regime") or regle_type) == regime:
                puces.append(
                    {"label": _LABEL_PERIODE[regime], "phrase": periode_phrase(p)}
                )

    # Autorisation pure (vert) en derniere puce.
    autorisation = periode_autorisation_phrase(regle)
    if autorisation:
        puces.append({"label": "Période d'autorisation", "phrase": autorisation})
    return puces


@register.simple_tag
def est_interdit_toute_lannee(regle) -> bool:
    """Vrai si la regle est une interdiction couvrant TOUTE l'annee, soit une
    unique periode d'interdiction 01/07 -> 30/06 (bornes de l'annee agricole).

    Sert a n'afficher la phrase d'intro (regle.message) au-dessus du
    calendrier que dans ce cas (#85) -- tous les autres resultats n'ont que le
    calendrier + la liste des periodes.
    """
    if regle is None:
        return False
    regle_type = getattr(regle, "type", None) or ""
    periodes = getattr(regle, "periodes", None) or []
    interdictions = [
        p for p in periodes if (p.get("regime") or regle_type) == "interdiction"
    ]
    # Toute l'annee = exactement 1 periode d'interdiction, bornee 01/07->30/06,
    # et aucune autre periode (ASC, plafond...) qui viendrait nuancer.
    if len(interdictions) != 1 or len(periodes) != 1:
        return False
    p = interdictions[0]
    return p.get("du") == "01/07" and p.get("au") == "30/06"


@register.inclusion_tag("nitrates/fragments/_calendrier.html")
def calendrier_epandage(regle, referentiel=None):
    """Rend un calendrier 12 mois colore avec les periodes interdites/
    conditionnelles overlays.

    `regle` : un dataclass `Resultat` ou un objet avec `type` et
    `periodes` (compatible).
    `referentiel` : dict `codes_prescription` (optionnel). Sert a detecter les
    regles dont TOUTES les PC sont des plafonds : dans ce cas les periodes
    « autorisation sous condition » sont peintes en VERT (autorise) plutot qu'en
    orange, le plafond s'appliquant de toute facon sur la periode autorisee
    (CR 2026-08).

    Chaque periode peut porter un champ `regime` optionnel : si
    present, c'est lui qui determine la couleur du segment (regime
    mixte) ; sinon on retombe sur le `type` global de la regle.
    """
    if regle is None:
        return {"vide": True, "mois": _MOIS_PAIRES}

    regle_type = getattr(regle, "type", None) or ""
    periodes = getattr(regle, "periodes", None) or []

    # CR 2026-08 : si TOUTES les PC de la regle sont des plafonds, ses periodes
    # « autorisation sous condition » sont en realite des periodes autorisees
    # (le plafond s'applique quoi qu'il arrive) -> pas d'overlay orange, on
    # laisse le fond vert. On neutralise donc ces periodes ASC.
    tous_plafonds = regle_uniquement_plafonds(regle, referentiel)

    # Regle "sous condition / plafond TOUTE L'ANNEE" : certaines feuilles
    # (regles partagees CIE/CINE courte, type III, plafonnements) sont des
    # autorisation_sous_condition / plafonnement SANS aucune periode -- le sens
    # metier est "sous condition sur toute l'annee agricole", pas "autorise
    # librement". Sans periode, la boucle ci-dessous ne produit aucun segment
    # -> fond vert -> rendu trompeur "Autorise" (cf. retour Max 2026-06-18 sur
    # les regles partagees). On synthetise donc une periode pleine annee
    # (01/07 -> 30/06) dans le regime du type, pour que le calendrier peigne
    # l'overlay (orange) et que la legende dise "Autorise sous condition".
    # Le cas 99% (regles AVEC periodes explicites) n'est PAS touche : on ne
    # synthetise que si `periodes` est vide.
    if not periodes and regle_type in ("autorisation_sous_condition", "plafonnement"):
        periodes = [{"du": "01/07", "au": "30/06", "regime": regle_type}]

    fond = _FOND_PAR_TYPE.get(regle_type, "gris")
    label = _LABEL_PAR_TYPE.get(regle_type, regle_type or "—")

    # Construction des segments sur l'annee, chacun avec sa propre couleur.
    # Couleur par segment = couleur du `regime` de la periode si present,
    # sinon couleur du `type` global de la regle.
    segments = []
    periodes_phenologiques = []  # non parsables (ex: brunissement_soies)
    for p in periodes:
        regime_effectif = p.get("regime") or regle_type
        # Regle 100% plafond : une periode ASC devient une periode autorisee
        # (vert). On saute son overlay -> le fond vert porte le sens.
        if tous_plafonds and regime_effectif == "autorisation_sous_condition":
            continue
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
        # Tooltip au survol de la zone (#134) : meme registre que le calendrier
        # dynamique ("Interdit du 15 dec. au 15 jan."). Le statique n'en avait
        # aucun (seulement un aria-label generique "Zone rouge"). On reutilise
        # periode_phrase pour la phrase de bornes, prefixee du verbe de regime.
        verbe = _VERBE_ZONE.get(couleur, "")
        phrase = periode_phrase(p)
        tooltip = f"{verbe} {phrase}".strip() if verbe else phrase
        # Borne flottante : on l'annote directement dans le tooltip cote Python
        # (plutot que dans le template) pour garder le markup court.
        if is_flottant:
            tooltip = f"{tooltip} (dates flottantes)"
        if seg:
            for start, width in seg:
                segments.append(
                    {
                        "start_pct": start,
                        "width_pct": width,
                        "couleur": couleur,
                        "is_flottant": is_flottant,
                        "tooltip": tooltip,
                    }
                )
        else:
            # Periode avec evenement phenologique inconnu (pas de
            # date_calendrier) -> affichee en texte a part. On resout les
            # bornes vers leur libelle lisible (#85, plus de snake_case).
            du = p.get("du", "")
            au = p.get("au", "")
            periodes_phenologiques.append(
                {
                    **p,
                    "du_label": (
                        du if DATE_JJMM_RE.match(str(du)) else _libelle_phenologique(du)
                    ),
                    "au_label": (
                        au if DATE_JJMM_RE.match(str(au)) else _libelle_phenologique(au)
                    ),
                }
            )

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
            du_pheno = not DATE_JJMM_RE.match(str(p["du"]))
            au_pheno = not DATE_JJMM_RE.match(str(p["au"]))
            # Couleur de la borne = couleur du regime de SA periode (#107 :
            # une borne phenologique prend orange pour l'ASC / rouge pour
            # l'interdiction, comme les bornes de zone, pas du noir).
            regime_effectif = p.get("regime") or regle_type
            couleur_borne = _COULEUR_ZONE_PAR_TYPE.get(regime_effectif)
            bornes_brutes.append(
                {
                    # Label affiche sous le tick : pour une borne phenologique
                    # on resout le slug vers son libelle_public lisible (#85),
                    # plus de snake_case sur la barre. Date fixe : inchange.
                    "label": _libelle_phenologique(p["du"]) if du_pheno else p["du"],
                    "pct": seg[0][0],
                    "is_phenologique": du_pheno,
                    "couleur": couleur_borne if du_pheno else None,
                    # #107 : sous-texte « Ici exemple au <date> » = date
                    # conventionnelle (date_calendrier) qui a servi a placer
                    # la borne phenologique sur le calendrier.
                    "date_exemple": (
                        _date_exemple_phenologique(p["du"]) if du_pheno else None
                    ),
                }
            )
            if len(seg) == 1:
                end_pct = seg[0][0] + seg[0][1]
            else:
                # Cas pivot : la fin est sur le 2e segment
                end_pct = seg[1][0] + seg[1][1]
            bornes_brutes.append(
                {
                    "label": _libelle_phenologique(p["au"]) if au_pheno else p["au"],
                    "pct": end_pct,
                    "is_phenologique": au_pheno,
                    "couleur": couleur_borne if au_pheno else None,
                    "date_exemple": (
                        _date_exemple_phenologique(p["au"]) if au_pheno else None
                    ),
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
        "orange": "Autorisé sous conditions",
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
        "mois": _MOIS_PAIRES,
        "fond": fond,
        "label": label,
        "segments": segments,
        "today_pct": today_pct,
        "bornes": bornes,
        "periodes_phenologiques": periodes_phenologiques,
        "regle_type": regle_type,
        "legende": legende,
    }


@register.simple_tag
def contenu_rich(cle: str, niveau_base: int = 3):
    """Rend une zone de contenu riche éditable (carte #131).

    Charge les blocs du `ContenuRichDSFR` de clé `cle` (cache process-local),
    les compile en HTML DSFR safe et renvoie le résultat. Zone absente ou vide
    -> chaîne vide (pas de 500 côté public). `niveau_base` = niveau du 1er
    titre HTML (3 = <h3>, sous les prescriptions du panneau résultat).

    Usage : {% contenu_rich "resultat.regles_permanentes" %}
    """
    from django.utils.text import slugify

    from envergo.nitrates.contenu_rich.compilateur import compile_dsfr
    from envergo.nitrates.contenu_rich.loader import load_blocs

    # La clé identifie la zone de façon unique sur la page -> sert de préfixe
    # d'id pour les accordéons, pour éviter les collisions entre zones (#157).
    id_prefix = f"cr-{slugify(cle)}"
    return compile_dsfr(load_blocs(cle), niveau_base=niveau_base, id_prefix=id_prefix)


@register.simple_tag
def compile_blocs(blocs, niveau_base: int = 3, id_prefix: str = "contenu-rich"):
    """Compile des blocs DSFR fournis directement (carte #136).

    Sert à rendre le champ `blocs` porté par un objet (ex CodePrescription.blocs)
    sans passer par un ContenuRichDSFR. Accepte la liste de blocs OU l'enveloppe
    {schema, blocs}. Vide -> chaîne vide.

    `id_prefix` : passer un identifiant stable et unique par appel sur la page
    (ex. le code prescription `cp`) pour éviter que deux blocs riches rendus sur
    la même page partagent les mêmes `id` d'accordéon (carte #157).

    Usage : {% compile_blocs pc.blocs id_prefix=cp %}
    """
    from django.utils.text import slugify

    from envergo.nitrates.contenu_rich.compilateur import compile_dsfr

    prefix = f"cr-{slugify(str(id_prefix))}" if id_prefix else "contenu-rich"
    return compile_dsfr(blocs or [], niveau_base=niveau_base, id_prefix=prefix)
