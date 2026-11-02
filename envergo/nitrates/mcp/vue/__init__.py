"""Vue interactive MCP Apps (`ui://nitrates/epandage-<version>.html`).

Une page HTML autonome que l'hôte (ChatGPT, Claude...) affiche dans un cadre
isolé sous la réponse des outils de localisation, de simulation et de
comparaison. Elle dialogue avec l'hôte en JSON-RPC sur postMessage (spec MCP
Apps 2026-01-26) : calendrier aux couleurs du simulateur, questions
complémentaires en boutons, carte cliquable qui renvoie le point choisi dans
la conversation.
"""

import base64
import hashlib
from functools import lru_cache
from pathlib import Path

PREFIXE_URI = "ui://nitrates/epandage"
MIME = "text/html;profile=mcp-app"
META = {
    "ui": {
        # Leaflet (cdnjs) et tuiles du Plan IGN (Geoplateforme) : rien d'autre.
        "csp": {
            "resourceDomains": [
                "https://cdnjs.cloudflare.com",
                "https://data.geopf.fr",
            ],
            "connectDomains": [],
        },
        "prefersBorder": True,
    },
    # Meme chose au format de ChatGPT (Apps SDK) : sans lui, ChatGPT affiche
    # la vue avec « CSP desactivee ».
    "openai/widgetCSP": {
        "resource_domains": ["https://cdnjs.cloudflare.com", "https://data.geopf.fr"],
        "connect_domains": [],
    },
    "openai/widgetPrefersBorder": True,
    "openai/widgetDescription": (
        "Calendrier d'épandage, questions du simulateur et carte de la parcelle."
    ),
}


@lru_cache(maxsize=1)
def icone_png() -> bytes:
    return (Path(__file__).parent / "icone.png").read_bytes()


def icone_data_uri() -> str:
    return "data:image/png;base64," + base64.b64encode(icone_png()).decode("ascii")


@lru_cache(maxsize=1)
def _html() -> str:
    return (Path(__file__).parent / "epandage.html").read_text(encoding="utf-8")


# URI versionnee par le contenu : ChatGPT garde la vue en cache par URI, et
# une conversation continuee gardait l'ancienne vue apres une correction. Une
# vue modifiee prend une nouvelle URI, relue des que l'hote relit les outils.
URI = f"{PREFIXE_URI}-{hashlib.sha1(_html().encode()).hexdigest()[:8]}.html"


def est_uri_de_la_vue(uri) -> bool:
    """Toute version de la vue (ancienne URI encore en cache chez l'hôte
    comprise) : on sert la vue actuelle."""
    return (
        isinstance(uri, str) and uri.startswith(PREFIXE_URI) and uri.endswith(".html")
    )


def description_ressource() -> dict:
    return {
        "uri": URI,
        "name": "Vue épandage nitrates",
        "mimeType": MIME,
        "_meta": META,
    }


def contenu_ressource(uri: str = URI) -> dict:
    return {"uri": uri, "mimeType": MIME, "text": _html(), "_meta": META}
