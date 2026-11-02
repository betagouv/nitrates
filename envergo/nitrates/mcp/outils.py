"""Outils MCP exposés aux assistants.

Les descriptions sont lues par le modèle de l'assistant pour décider quand et
comment appeler chaque outil : elles sont écrites pour lui (ce que fait
l'outil, quand l'utiliser, ce qu'il faut demander à l'agriculteur avant).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from envergo.nitrates.mcp import services, vue

_LOCALISATION = {
    "commune": {
        "type": "string",
        "description": "Nom de la commune de la parcelle (ex. « Châlons-en-Champagne »).",
    },
    "code_postal": {
        "type": "string",
        "description": "Code postal, pour lever une homonymie de commune.",
    },
    "code_insee": {
        "type": "string",
        "description": "Code INSEE de la commune s'il est connu (renvoyé par localiser_parcelle).",
    },
    "reference_cadastrale": {
        "type": "string",
        "description": (
            "Référence cadastrale de la parcelle (section et numéro, ex. « YM 28 »), "
            "avec la commune. Sur le bail ou l'avis de taxe foncière : le moyen le "
            "plus précis."
        ),
    },
    "adresse": {
        "type": "string",
        "description": "Adresse ou lieu-dit, plus précis que la commune seule.",
    },
    "zone": {
        "type": "string",
        "description": (
            "Zone choisie par l'agriculteur sur la carte, avec la commune : numéro "
            "d'une aire de captage (« 1 », « 2 »...) ou « hors » s'il est en dehors."
        ),
    },
    "lat": {
        "type": "number",
        "description": (
            "Latitude WGS84. À utiliser seulement avec un point renvoyé par "
            "localiser_parcelle (zone choisie sur la carte) : ne jamais demander "
            "de coordonnées GPS à l'agriculteur."
        ),
    },
    "lng": {"type": "number", "description": "Longitude WGS84 (cf. lat)."},
}

_CLES_LOCALISATION = ("commune", "code_postal", "code_insee", "adresse", "lat")


def _elements_manquants(arguments: dict, requis: dict) -> dict | None:
    """Ce qui manque pour répondre, à demander en une seule fois, plutôt que
    de laisser l'assistant répondre au jugé."""
    manque = []
    if not any(arguments.get(c) not in (None, "") for c in _CLES_LOCALISATION):
        # Le lieu d'abord, seul : tout le reste (programme, aire de captage,
        # questions) en depend.
        return {
            "statut": "elements_manquants",
            "manque": [
                {
                    "element": "lieu",
                    "question": "Sur quelle commune est la parcelle ?",
                }
            ],
            "consigne": (
                "Demander UNIQUEMENT la commune de la parcelle, en une phrase, "
                "sans rien expliquer d'autre ni appeler d'autre outil avant."
            ),
        }
    for cle, question in requis.items():
        if arguments.get(cle) in (None, ""):
            manque.append({"element": cle, "question": question})
    if not manque:
        return None
    return {
        "statut": "elements_manquants",
        "manque": manque,
        "consigne": (
            "Avant toute réponse sur le fond, demander ces éléments à "
            "l'agriculteur en une seule question courte, puis rappeler l'outil."
        ),
    }


_REPONSES = {
    "type": "object",
    "description": (
        "Réponses aux questions complémentaires déjà posées, sous la forme "
        "{champ: valeur} avec le `champ` et une `valeur` des `choix` renvoyés "
        "par l'outil. Les dates demandées (date_semis_couvert...) se donnent "
        "au format JJ/MM."
    ),
    "additionalProperties": True,
}

_DATE = {
    "type": "string",
    "description": "Date d'épandage envisagée, JJ/MM ou AAAA-MM-JJ.",
}


# Vue interactive (extension MCP Apps, que ChatGPT et Claude affichent sous la
# reponse de l'outil) : calendrier, questions en boutons, carte cliquable.
URI_VUE = vue.URI


@dataclass(frozen=True)
class Outil:
    nom: str
    titre: str
    description: str
    schema: dict
    executer: Callable[[dict, str], dict]
    vue: bool = False

    def declaration(self) -> dict:
        declaration = self._declaration()
        if self.vue:
            declaration["_meta"] = {
                "ui": {"resourceUri": URI_VUE},
                # Alias historique de l'Apps SDK, toujours lu par ChatGPT.
                "openai/outputTemplate": URI_VUE,
                "openai/widgetAccessible": True,
            }
        return declaration

    def _declaration(self) -> dict:
        return {
            "name": self.nom,
            "title": self.titre,
            "description": self.description,
            "inputSchema": self.schema,
            "annotations": {
                "title": self.titre,
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        }


def _localiser_precisement(arguments: dict):
    """Localisation + garde-fou de l'aire de captage. Renvoie (loc, demande) :
    `demande` non vide = il faut d'abord savoir où est la parcelle."""
    loc = services.localisation_depuis_arguments(arguments)
    demande = services.preciser_localisation(loc, arguments.get("zone"))
    return loc, demande


def _localiser(arguments: dict, base_url: str) -> dict:
    loc = services.localisation_depuis_arguments(arguments)
    if arguments.get("zone"):
        services.preciser_localisation(loc, arguments["zone"])
    return services.contexte_geographique(loc)


def _lister_cultures(arguments: dict, base_url: str) -> dict:
    return services.catalogue_cultures()


def _lister_fertilisants(arguments: dict, base_url: str) -> dict:
    return services.catalogue_fertilisants()


def _simuler(arguments: dict, base_url: str) -> dict:
    manque = _elements_manquants(
        arguments,
        {
            "culture": "Quelle culture ou quel couvert sur la parcelle ?",
            "fertilisant": "Quel produit (lisier, fumier, digestat, engrais...) ?",
        },
    )
    if manque:
        return manque
    choix = services.demande_de_choix(arguments)
    if choix:
        return choix
    loc, demande = _localiser_precisement(arguments)
    if demande:
        return demande
    sortie = services.simuler(
        loc,
        arguments.get("culture") or "",
        arguments.get("fertilisant") or "",
        reponses=arguments.get("reponses") or {},
        date_demandee=arguments.get("date") or "",
        base_url=base_url,
    )
    sortie["localisation"] = loc.as_dict()
    return sortie


def _comparer(arguments: dict, base_url: str) -> dict:
    manque = _elements_manquants(
        arguments,
        {
            "fertilisant": "Quel produit (lisier, fumier, digestat, engrais...) ?",
            "date": "À quelle date voulez-vous épandre ?",
        },
    )
    if manque:
        return manque
    choix = services.demande_de_choix(arguments)
    if choix:
        return choix
    loc, demande = _localiser_precisement(arguments)
    if demande:
        return demande
    return services.comparer_cultures(
        loc,
        arguments.get("fertilisant") or "",
        arguments.get("date") or "",
        reponses=arguments.get("reponses") or {},
        base_url=base_url,
    )


def _comparer_types(arguments: dict, base_url: str) -> dict:
    manque = _elements_manquants(
        arguments,
        {
            "culture": "Quelle culture ou quel couvert sur la parcelle ?",
            "date": "À quelle date voulez-vous épandre ?",
        },
    )
    if manque:
        return manque
    choix = services.demande_de_choix(arguments)
    if choix:
        return choix
    loc, demande = _localiser_precisement(arguments)
    if demande:
        return demande
    return services.comparer_fertilisants(
        loc,
        arguments.get("culture") or "",
        arguments.get("date") or "",
        reponses=arguments.get("reponses") or {},
        base_url=base_url,
    )


def _prescription(arguments: dict, base_url: str) -> dict:
    return services.lire_prescription(arguments.get("code") or "", base_url)


def _document(arguments: dict, base_url: str) -> dict:
    return services.lire_document(arguments.get("identifiant") or "", base_url)


def _aplsh(arguments: dict, base_url: str) -> dict:
    manque = _elements_manquants(
        arguments,
        {
            "fertilisant": "Quel produit (lisier, fumier, digestat...) ?",
            "date": "À quelle date l'apport ?",
        },
    )
    if manque:
        return manque
    choix = services.demande_de_choix(arguments)
    if choix:
        return choix
    loc, demande = _localiser_precisement(arguments)
    if demande:
        return demande
    return services.calculer_aplsh(
        loc,
        arguments["fertilisant"],
        arguments["date"],
        dose=arguments.get("dose"),
        teneur_n=arguments.get("teneur_n"),
        variante=arguments.get("variante") or "",
        plafond=arguments.get("plafond_kg_aplsh_ha"),
    )


def _definition(arguments: dict, base_url: str) -> dict:
    return services.chercher_definition(arguments.get("terme") or "", base_url)


OUTILS = [
    Outil(
        nom="localiser_parcelle",
        titre="Situer une parcelle",
        description=(
            "OBLIGATOIRE EN PREMIER pour toute question d'épandage : ne rien "
            "répondre de mémoire avant (ni règle générale, ni « à vérifier »). "
            "Situe une parcelle agricole (commune, référence cadastrale, adresse "
            "ou lieu-dit) et indique la réglementation nitrates qui s'y applique : "
            "zone vulnérable ou non, programme d'actions national ou régional, "
            "aire de captage (zone d'action renforcée). À appeler EN PREMIER, avant "
            "toute réponse. Affiche une carte avec les aires de captage "
            "numérotées : si une zone touche la commune, demander à l'agriculteur "
            "s'il est dedans (laquelle) ou en dehors, puis passer zone=... aux "
            "autres outils. Si la commune est ambiguë, demander laquelle."
        ),
        schema={"type": "object", "properties": _LOCALISATION},
        executer=_localiser,
        vue=True,
    ),
    Outil(
        nom="lister_cultures",
        titre="Cultures du simulateur",
        description=(
            "Liste des cultures et couverts reconnus par le simulateur, avec "
            "leur `id`. À consulter pour traduire ce que dit l'agriculteur "
            "(« mon blé », « ma CIPAN avant maïs ») en `id` de culture. Si "
            "plusieurs ids sont plausibles, poser la question."
        ),
        schema={"type": "object", "properties": {}},
        executer=_lister_cultures,
    ),
    Outil(
        nom="lister_fertilisants",
        titre="Fertilisants du simulateur",
        description=(
            "Liste des fertilisants (fumiers, lisiers, digestats, composts, "
            "engrais minéraux, boues...) avec leur `id` et leur type "
            "réglementaire (0, Ia, Ib, II, III). À consulter pour traduire le "
            "produit de l'agriculteur en `id` de fertilisant."
        ),
        schema={"type": "object", "properties": {}},
        executer=_lister_fertilisants,
    ),
    Outil(
        nom="simuler_epandage",
        titre="Simuler un épandage",
        description=(
            "Seule source fiable pour les dates d'épandage : ne jamais répondre "
            "de mémoire. Annoncer le produit et la culture retenus (a_annoncer). "
            "Simule, comme le formulaire officiel, ce que la réglementation "
            "nitrates permet pour un fertilisant sur une culture à un endroit : "
            "calendrier des périodes d'interdiction / d'autorisation sous "
            "conditions sur l'année culturale, prescriptions à respecter, "
            "plafond d'azote éventuel, et réponse à une date précise si `date` "
            "est donnée. Peut renvoyer statut=questions_complementaires : poser "
            "alors ces questions à l'agriculteur et rappeler l'outil avec "
            "`reponses`. Renvoie l'image du calendrier : la montrer plutôt que "
            "de recopier les dates. Si le résultat contient `dates_a_preciser` (dates du "
            "couvert ou du semis), rappeler l'outil avec ces dates plutôt que de "
            "calculer soi-même. Toujours donner le `lien_simulation` à "
            "l'agriculteur."
        ),
        schema={
            "type": "object",
            "properties": {
                **_LOCALISATION,
                "culture": {
                    "type": "string",
                    "description": (
                        "id de culture (cf. lister_cultures), ex. « colza ». Pour un "
                        "couvert dont on ne sait pas s'il est récolté ni s'il reste "
                        "en place après le 1er janvier, passer « couvert » : l'outil "
                        "fait choisir l'agriculteur. Ne jamais trancher à sa place."
                    ),
                },
                "fertilisant": {
                    "type": "string",
                    "description": "id de fertilisant (cf. lister_fertilisants).",
                },
                "date": _DATE,
                "reponses": _REPONSES,
            },
        },
        executer=_simuler,
        vue=True,
    ),
    Outil(
        nom="comparer_cultures",
        titre="Où épandre à une date donnée",
        description=(
            "Pour un fertilisant, une parcelle (ou une commune) et une date, "
            "indique sur quelles cultures l'épandage est autorisé, autorisé "
            "sous conditions, interdit, ou dépend d'une précision. Répond à « "
            "j'ai du lisier à sortir en février, sur quoi je peux l'épandre ? ». "
            "Renvoie une image du calendrier par culture : la montrer."
        ),
        schema={
            "type": "object",
            "properties": {
                **_LOCALISATION,
                "fertilisant": {
                    "type": "string",
                    "description": "id de fertilisant (cf. lister_fertilisants).",
                },
                "date": _DATE,
                "reponses": _REPONSES,
            },
        },
        executer=_comparer,
        vue=True,
    ),
    Outil(
        nom="comparer_fertilisants",
        titre="Calendrier par type de fertilisant",
        description=(
            "Pour une culture, une parcelle et une date : le calendrier de chaque "
            "type de fertilisant (0, Ia, Ib, II, II digestat, III) en une seule "
            "vue. Répond à « je ne sais pas encore quoi épandre, quelles sont les "
            "règles ? ». Ne jamais répondre de mémoire."
        ),
        schema={
            "type": "object",
            "properties": {
                **_LOCALISATION,
                "culture": {
                    "type": "string",
                    "description": (
                        "id de culture (cf. lister_cultures), ou mot générique "
                        "(« couvert ») : l'outil fera alors choisir l'agriculteur."
                    ),
                },
                "date": _DATE,
                "reponses": _REPONSES,
            },
        },
        executer=_comparer_types,
        vue=True,
    ),
    Outil(
        nom="calculer_aplsh",
        titre="Calculer l'azote libéré (APLSH)",
        description=(
            "Plan de fumure : azote potentiellement libéré jusqu'en sortie d'hiver "
            "(APLSH) d'un apport organique, et dose maximale pour rester sous le "
            "plafond (70 kg/ha en général, 35 en aire de captage du Grand Est : "
            "prendre celui de la prescription de plafond). Coefficients du "
            "référentiel régional (GREN) de la parcelle. Répond à « 30 m³/ha de "
            "lisier fin août, je dépasse ? » ou « combien je peux mettre ? »."
        ),
        schema={
            "type": "object",
            "properties": {
                **_LOCALISATION,
                "fertilisant": {
                    "type": "string",
                    "description": "id de fertilisant (cf. lister_fertilisants).",
                },
                "date": {"type": "string", "description": "Date de l'apport, JJ/MM."},
                "dose": {
                    "type": "number",
                    "description": "Dose prévue, en t/ha (solide) ou m³/ha (liquide).",
                },
                "teneur_n": {
                    "type": "number",
                    "description": (
                        "Azote total en kg par t ou m³, si l'agriculteur a une "
                        "analyse ou si le référentiel ne la donne pas."
                    ),
                },
                "variante": {
                    "type": "string",
                    "description": "Précision du produit quand l'outil la demande.",
                },
                "plafond_kg_aplsh_ha": {
                    "type": "number",
                    "description": "Plafond de la prescription applicable (défaut 70).",
                },
            },
        },
        executer=_aplsh,
    ),
    Outil(
        nom="lire_prescription",
        titre="Lire une prescription",
        description=(
            "Texte complet d'une prescription conditionnée (code « pc1 », "
            "« pc11_ge »...) citée dans un résultat : les conditions à remplir "
            "pour épandre en période d'autorisation sous conditions."
        ),
        schema={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Code de la prescription."}
            },
            "required": ["code"],
        },
        executer=_prescription,
    ),
    Outil(
        nom="lire_document",
        titre="Lire un document de référence",
        description=(
            "Texte d'un document de référence cité par une prescription (annexe "
            "d'un arrêté régional : modalités des reliquats azotés, sols à faible "
            "disponibilité en azote...). Identifiant donné par lire_prescription "
            "(documents_cites) ; sans identifiant, liste les documents disponibles."
        ),
        schema={
            "type": "object",
            "properties": {
                "identifiant": {
                    "type": "string",
                    "description": "Identifiant du document (documents_cites).",
                }
            },
        },
        executer=_document,
    ),
    Outil(
        nom="chercher_definition",
        titre="Définition officielle",
        description=(
            "Définition réglementaire d'un terme du domaine (CIPAN, interculture "
            "longue, fertilisant de type II, plan d'épandage, zone vulnérable, "
            "C/N...), telle que publiée par le simulateur."
        ),
        schema={
            "type": "object",
            "properties": {
                "terme": {"type": "string", "description": "Terme à définir."}
            },
            "required": ["terme"],
        },
        executer=_definition,
    ),
]

OUTILS_PAR_NOM = {o.nom: o for o in OUTILS}
