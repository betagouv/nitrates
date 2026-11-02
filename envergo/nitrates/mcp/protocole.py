"""MCP sur JSON-RPC 2.0, transport « Streamable HTTP » en mode sans état.

Le client POSTe un message JSON-RPC, le serveur répond en `application/json`
(le transport autorise JSON ou SSE ; on n'a rien à pousser en flux). Pas de
session : chaque requête se suffit à elle-même, ce qui tient sur le gunicorn
WSGI existant sans dépendance supplémentaire.

Implémenté : initialize, ping, tools/list, tools/call, les notifications
(ignorées), et des listes vides pour resources/prompts que certains clients
interrogent même sans capacité déclarée.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging

from django.core.cache import cache
from django.db import DatabaseError, connection

from envergo.nitrates.mcp import geocodage, vue
from envergo.nitrates.mcp.outils import OUTILS, OUTILS_PAR_NOM
from envergo.nitrates.mcp.services import ErreurSaisie

logger = logging.getLogger(__name__)

CLE_IMAGE = "nitrates-mcp-image:{}"
DUREE_IMAGE_S = 7 * 24 * 3600

VERSIONS_PROTOCOLE = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
# Reponse a un client qui demande une version inconnue : celle dont on
# implemente toutes les fonctions utilisees (structuredContent, title).
VERSION_PAR_DEFAUT = "2025-06-18"

INSTRUCTIONS = (
    "RÈGLE ABSOLUE : ne jamais répondre de mémoire sur l'épandage, ni même en "
    "partie, ni « à vérifier ». Pas de réponse courte préalable, pas de cadre "
    "général : la première chose à faire est d'appeler les outils. S'il manque "
    "la commune, la demander seule, en une phrase.\n"
    "Ce serveur donne accès au simulateur public de la réglementation nitrates "
    "(épandage des fertilisants azotés en zone vulnérable) : « ai-je le droit "
    "d'épandre ce fertilisant sur cette parcelle à cette date, et sous quelles "
    "conditions ? ».\n"
    "Ne rien écrire sur la réglementation avant d'avoir le résultat d'un outil : "
    "pas d'introduction, pas de règle générale, appeler d'abord "
    "localiser_parcelle. Si un outil répond localisation_a_preciser, poser sa "
    "question et attendre la réponse avant toute autre chose.\n"
    "Style : réponses courtes (5 lignes au plus hors vue), sans énumérer de "
    "longues listes. Le lieu se demande d'abord et seul ; ensuite, s'il manque "
    "culture, produit ou date, les demander ensemble en une question, plutôt "
    "que de répondre au jugé. La vue (carte, calendrier, boutons) s'affiche "
    "sous la réponse : ne pas recopier les dates ni les choix qu'elle montre.\n"
    "Méthode : 1) situer la parcelle avec localiser_parcelle ; si une aire de "
    "captage touche la commune, faire dire à l'agriculteur dans quelle zone est "
    "sa parcelle ou demander sa référence cadastrale (jamais de coordonnées "
    "GPS). Si son message donne un point de la carte (lat=…, lng=…), repasser "
    "ces lat/lng tels quels à tous les outils suivants, sans commune et sans "
    "relocaliser ; 2) traduire culture et produit en ids (lister_cultures, "
    "lister_fertilisants). Ne jamais choisir à la place de l'agriculteur : un "
    "couvert dont on ne sait pas s'il est récolté ni s'il reste en place après "
    "le 1er janvier se passe tel quel (« couvert »), un produit vague aussi "
    "(« fumier ») ; l'outil répond choix_a_faire et la vue montre les choix ; "
    "3) simuler_epandage, comparer_cultures (un produit, toutes les cultures) "
    "ou comparer_fertilisants (une culture, tous les types de fertilisant) ; "
    "4) poser les questions complémentaires renvoyées, sans jamais supposer la "
    "réponse. Un message « Mes réponses : … (reponses={…}) » contient toutes "
    "les réponses : rappeler l'outil avec ce `reponses` tel quel.\n"
    "Une seule vue par réponse : un seul appel à localiser_parcelle, "
    "simuler_epandage, comparer_cultures ou comparer_fertilisants par tour, "
    "jamais plusieurs en parallèle. Plusieurs cultures : comparer_cultures ; "
    "plusieurs produits : comparer_fertilisants.\n"
    "Ne jamais inventer une règle, une date ou un plafond absents des réponses "
    "des outils : lire la prescription (lire_prescription) et les documents cités "
    "(lire_document). Les plafonds sont en kg d'azote potentiellement libéré "
    "jusqu'en sortie d'hiver (APLSH) par hectare : ne pas les présenter comme de "
    "l'azote efficace ni de l'azote total. "
    "Une période sans interdiction n'est pas un blanc-seing : "
    "rappeler en une ligne les règles permanentes. Donner le lien de la "
    "simulation. C'est de l'information réglementaire, pas du conseil "
    "agronomique."
)

# Codes d'erreur JSON-RPC 2.0.
ERREUR_PARSE = -32700
ERREUR_REQUETE = -32600
ERREUR_METHODE = -32601
ERREUR_PARAMS = -32602
ERREUR_INTERNE = -32603


def _erreur(id_, code, message):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _ok(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _initialize(params: dict, base_url: str = "") -> dict:
    demandee = (params or {}).get("protocolVersion")
    version = demandee if demandee in VERSIONS_PROTOCOLE else VERSION_PAR_DEFAUT
    return {
        "protocolVersion": version,
        "capabilities": {
            "tools": {"listChanged": False},
            "resources": {"listChanged": False},
        },
        "serverInfo": {
            "name": "nitrates",
            "title": "Simulateur nitrates (réglementation épandage)",
            "description": (
                "Simulateur officiel de la réglementation nitrates : seule source "
                "fiable sur les dates et conditions d'épandage. Ne jamais répondre "
                "de mémoire."
            ),
            "version": "0.1.0",
            # Pictogramme Nitrat'Info, en data URI d'abord (rien a telecharger,
            # juste meme derriere un tunnel ou un proxy), puis par lien.
            "icons": [
                {
                    "src": vue.icone_data_uri(),
                    "mimeType": "image/png",
                    "sizes": ["256x256"],
                },
                {
                    "src": f"{base_url}/mcp/icone.png",
                    "mimeType": "image/png",
                    "sizes": ["256x256"],
                },
            ],
        },
        "instructions": INSTRUCTIONS,
    }


def _resultat_outil(donnees: dict, en_erreur=False, base_url: str = "") -> dict:
    """Résultat MCP : JSON en texte + structuredContent, puis les images (PNG)
    éventuelles en contenu `image`. Chaque image est aussi servie par lien
    (cf. views_mcp.ImageMcpView) pour les clients qui ne l'affichent pas."""
    images = donnees.pop("_images", None) or []
    meta_vue = donnees.pop("_vue", None)
    contenu_images = []
    if images:
        donnees["images"] = []
        for image in images:
            cle = hashlib.sha1(image["png"]).hexdigest()
            cache.set(CLE_IMAGE.format(cle), image["png"], DUREE_IMAGE_S)
            donnees["images"].append(
                {"titre": image["titre"], "url": f"{base_url}/mcp/image/{cle}.png"}
            )
            contenu_images.append(
                {
                    "type": "image",
                    "data": base64.b64encode(image["png"]).decode("ascii"),
                    "mimeType": "image/png",
                    "annotations": {"audience": ["user", "assistant"]},
                }
            )
    resultat = {
        "content": [{"type": "text", "text": json.dumps(donnees, ensure_ascii=False)}]
        + contenu_images,
        "structuredContent": donnees,
        "isError": en_erreur,
    }
    if meta_vue:
        # Donnees pour la vue seulement (geometries...) : `_meta` n'est pas
        # transmis au modele, il ne pese pas sur sa fenetre de contexte.
        resultat["_meta"] = meta_vue
    return resultat


def _tools_call(params: dict, base_url: str) -> dict:
    nom = (params or {}).get("name")
    outil = OUTILS_PAR_NOM.get(nom)
    if outil is None:
        raise KeyError(nom)
    arguments = (params or {}).get("arguments") or {}
    if not isinstance(arguments, dict):
        return _resultat_outil({"erreur": "arguments doit être un objet"}, True)
    try:
        return _resultat_outil(outil.executer(arguments, base_url), base_url=base_url)
    except ErreurSaisie as exc:
        # Erreur « metier » rendue au modele (isError) pour qu'il se corrige,
        # pas une erreur de protocole.
        return _resultat_outil({"erreur": str(exc), **exc.details}, True)
    except DatabaseError:
        # Base momentanement perdue (redemarrage, manque de memoire) : le dire
        # au modele plutot qu'une erreur interne, pour qu'il ne comble pas le
        # vide de memoire.
        logger.exception("MCP : base indisponible pendant %s", nom)
        if not connection.in_atomic_block:
            connection.close()  # la suivante repartira sur une connexion neuve
        return _resultat_outil(
            {
                "erreur": "Simulateur momentanément indisponible. Réessayer dans "
                "une minute ; en attendant, ne rien répondre de mémoire."
            },
            True,
        )
    except geocodage.GeocodageIndisponible:
        return _resultat_outil(
            {
                "erreur": "Service de géocodage indisponible. Réessayer, ou "
                "donner les coordonnées lat/lng de la parcelle."
            },
            True,
        )


def traiter_message(message, base_url: str):
    """Traite un message JSON-RPC. Renvoie la réponse (dict) ou None pour une
    notification (pas de réponse attendue)."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _erreur(None, ERREUR_REQUETE, "Requête JSON-RPC 2.0 invalide")
    methode = message.get("method")
    id_ = message.get("id")
    est_notification = "id" not in message
    if methode is None:
        # Reponse du client a une requete serveur : on n'en emet jamais.
        return None
    params = message.get("params") or {}

    try:
        if methode == "initialize":
            resultat = _initialize(params, base_url)
        elif methode == "ping":
            resultat = {}
        elif methode == "tools/list":
            resultat = {"tools": [o.declaration() for o in OUTILS]}
        elif methode == "tools/call":
            try:
                resultat = _tools_call(params, base_url)
            except KeyError:
                return _erreur(
                    id_, ERREUR_PARAMS, f"Outil inconnu : {params.get('name')}"
                )
        elif methode == "resources/list":
            resultat = {"resources": [vue.description_ressource()]}
        elif methode == "resources/read":
            uri = (params or {}).get("uri")
            if not vue.est_uri_de_la_vue(uri):
                return _erreur(id_, ERREUR_PARAMS, f"Ressource inconnue : {uri}")
            resultat = {"contents": [vue.contenu_ressource(uri)]}
        elif methode == "resources/templates/list":
            resultat = {"resourceTemplates": []}
        elif methode == "prompts/list":
            resultat = {"prompts": []}
        elif methode.startswith("notifications/"):
            return None
        else:
            return (
                None
                if est_notification
                else _erreur(id_, ERREUR_METHODE, f"Méthode non supportée : {methode}")
            )
    except Exception:
        logger.exception("MCP : échec de %s", methode)
        return (
            None
            if est_notification
            else _erreur(id_, ERREUR_INTERNE, "Erreur interne du serveur")
        )
    return None if est_notification else _ok(id_, resultat)


def traiter_corps(corps: bytes, base_url: str):
    """Corps HTTP -> réponse JSON (dict ou liste) ou None (rien à renvoyer)."""
    try:
        message = json.loads(corps or b"")
    except (ValueError, UnicodeDecodeError):
        return _erreur(None, ERREUR_PARSE, "JSON invalide")
    if isinstance(message, list):
        # Lots JSON-RPC (autorises par la revision 2025-03-26 du protocole).
        reponses = [r for r in (traiter_message(m, base_url) for m in message) if r]
        return reponses or None
    return traiter_message(message, base_url)
