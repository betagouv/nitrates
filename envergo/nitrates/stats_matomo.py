"""Page statistiques (#517) : nombre de simulations lu dans Matomo.

Pas de compteur en base : Matomo (stats.beta.gouv.fr) reste la seule source.
L'event `Simulateur / SimulationLancee` est poussé par nitrates_analytics.js ;
ici on relit son volume par semaine ou par mois via l'API Reporting, avec un
token d'un compte Matomo en LECTURE SEULE (jamais un token admin en env).

Chaque environnement lit son propre site Matomo (ANALYTICS["NITRATES"]
["SITE_ID"] : 282 prod, 276 staging). Le token part en POST, pas dans
l'URL, pour ne pas finir dans les logs d'accès.

Résilience : réponse gardée en cache (CACHE_TTL), et une copie « dernière
valeur connue » sans expiration sert de repli si Matomo ne répond pas. Sans
aucune des deux, la page affiche un message et ne casse pas.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

EVENT_SIMULATION = "SimulationLancee"
PERIODES = ("week", "month")
CACHE_TTL = 6 * 3600
TIMEOUT = 10
#: Fenêtre affichée quand aucune date de début n'est configurée.
NB_PERIODES_PAR_DEFAUT = 12

MOIS = (
    "janv.",
    "févr.",
    "mars",
    "avr.",
    "mai",
    "juin",
    "juil.",
    "août",
    "sept.",
    "oct.",
    "nov.",
    "déc.",
)


class StatsIndisponibles(Exception):
    pass


@dataclass(frozen=True)
class Point:
    debut: date
    libelle: str
    libelle_long: str
    simulations: int


def _config():
    conf = settings.ANALYTICS["NITRATES"]
    if not (conf.get("TRACKER_URL") and conf.get("SITE_ID")):
        raise StatsIndisponibles("Matomo non configuré")
    if not conf.get("SECURITY_TOKEN"):
        raise StatsIndisponibles("Token Matomo absent")
    return conf


def _date_debut():
    brute = getattr(settings, "NITRATES_STATS_DATE_DEBUT", "")
    if not brute:
        return None
    return datetime.strptime(brute, "%Y-%m-%d").date()


def _plage(periode):
    debut = _date_debut()
    if debut is None:
        return f"last{NB_PERIODES_PAR_DEFAUT}"
    return f"{debut:%Y-%m-%d},today"


def _libelles(cle, periode):
    """Clé Matomo -> (date de début, libellé court, libellé long)."""
    if periode == "month":
        debut = datetime.strptime(cle, "%Y-%m").date()
        mois = MOIS[debut.month - 1]
        return debut, f"{mois} {debut:%y}", f"{mois} {debut.year}"
    # semaine : "2026-10-05,2026-10-11"
    debut = datetime.strptime(cle.split(",")[0], "%Y-%m-%d").date()
    return (
        debut,
        f"{debut:%d/%m}",
        f"semaine du {debut.day} {MOIS[debut.month - 1]} {debut.year}",
    )


def parse_events(data, periode):
    """Réponse Events.getAction (multi-périodes) -> liste de Point triée."""
    if not isinstance(data, dict) or data.get("result") == "error":
        raise StatsIndisponibles(
            data.get("message", "réponse inattendue")
            if isinstance(data, dict)
            else "réponse inattendue"
        )
    points = []
    for cle, lignes in data.items():
        nb = 0
        for ligne in lignes or []:
            if ligne.get("label") == EVENT_SIMULATION:
                # Matomo renvoie nb_events tantôt en int, tantôt en str
                nb += int(ligne.get("nb_events") or 0)
        debut, court, long = _libelles(cle, periode)
        points.append(Point(debut, court, long, nb))
    return sorted(points, key=lambda p: p.debut)


def _fetch(periode):
    conf = _config()
    try:
        reponse = requests.post(
            urljoin(conf["TRACKER_URL"], "index.php"),
            data={
                "module": "API",
                "method": "Events.getAction",
                "idSite": conf["SITE_ID"],
                "period": periode,
                "date": _plage(periode),
                "format": "JSON",
                "token_auth": conf["SECURITY_TOKEN"],
            },
            timeout=TIMEOUT,
        )
        reponse.raise_for_status()
        data = reponse.json()
    except (requests.RequestException, ValueError) as e:
        raise StatsIndisponibles(str(e)) from e
    return parse_events(data, periode)


def simulations_par_periode(periode):
    """Points (semaine ou mois) du nombre de simulations, ou None si indisponible."""
    if periode not in PERIODES:
        raise ValueError(periode)
    site = settings.ANALYTICS["NITRATES"].get("SITE_ID", "")
    cle = f"nitrates_stats:{site}:{periode}:{_plage(periode)}"
    points = cache.get(cle)
    if points is not None:
        return points
    try:
        points = _fetch(periode)
    except StatsIndisponibles as e:
        logger.warning("Stats Matomo indisponibles (%s) : %s", periode, e)
        return cache.get(f"{cle}:dernier")
    cache.set(cle, points, CACHE_TTL)
    cache.set(f"{cle}:dernier", points, None)
    return points
