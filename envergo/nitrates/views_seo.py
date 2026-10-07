"""Fichiers de référencement : robots.txt, sitemap.xml, llms.txt (#290, #565).

REGLE : tout ce qui sert le référencement (SEO, moteurs de recherche) et le
GEO (Generative Engine Optimization, référencement par les assistants IA) est
en ACCES LIBRE, sans authentification, quel que soit l'état du lockdown. Un
robot ne se loggue pas : un robots.txt derrière le login admin est un
robots.txt qui n'existe pas. Les chemins sont exemptés une fois pour toutes
dans `CHEMINS_SEO_PUBLICS` (envergo/contrib/middleware.py), et un test
verrouille la règle (test_seo.py). Cf. docs/seo_geo.md.

Ce qui distingue les environnements, c'est le CONTENU du robots.txt, pas son
accessibilité : seule la prod s'ouvre à l'indexation, dev et staging
répondent `Disallow: /` pour ne jamais concurrencer la prod dans les
résultats de recherche.

Le sitemap et le llms.txt ne listent que les pages réellement lisibles par
un anonyme dans la configuration courante (`pages_publiques`) : on ne
pointe pas les robots vers des pages qui redirigent vers un login.
"""

from xml.sax.saxutils import escape

from django.conf import settings
from django.http import HttpResponse
from django.urls import reverse

from envergo.nitrates.models import CodePrescription

#: Valeurs d'ENV_NAME pour lesquelles on ouvre l'indexation. "prod" est la
#: valeur posée par l'IaC nitrates, "production" celle d'Envergo amont.
ENVS_INDEXABLES = ("prod", "production")

#: Préfixes que les robots n'ont rien à explorer : écrans internes (login),
#: endpoints techniques ou de données brutes. Le préfixe admin réel de la
#: prod n'est volontairement PAS listé (il est secret, DJANGO_ADMIN_URL) ;
#: /admin/ correspond aux écrans nitrates montés en dur sous ce préfixe.
CHEMINS_NON_INDEXES = (
    "/admin/",
    "/simulateur/",
    "/api/",
    "/geojson/",
    "/yaml-browser/",
    "/oidc/",
    "/_probe/",
    "/simulation/",
    "/urlmappings/",
    "/analytics/",
    "/feedback/",
    "/csp/",
)

DESCRIPTION_SERVICE = (
    "Nitrat'Info indique aux agriculteurs les périodes et conditions "
    "d'épandage des fertilisants azotés applicables à leur parcelle en zone "
    "vulnérable aux nitrates, selon le programme d'actions national (PAN) et "
    "les programmes d'actions régionaux (PAR)."
)


def est_indexable():
    return getattr(settings, "ENV_NAME", "") in ENVS_INDEXABLES


def url_absolue(chemin):
    return f"https://{settings.ENVERGO_NITRATES_DOMAIN}{chemin}"


def _nitrates(nom, **kwargs):
    return reverse(nom, urlconf="config.urls_nitrates", kwargs=kwargs or None)


def pages_publiques():
    """Pages de contenu lisibles par un anonyme, dans l'ordre d'importance.

    Liste de tuples (chemin, titre, description courte). Le simulateur
    interne (/simulateur/) n'y figure jamais : c'est un outil de recette.
    """
    lockdown = getattr(settings, "LOCKDOWN_BEHIND_LOGIN", False)
    root_ouvert = getattr(settings, "NITRATES_ROOT_OUVERT", False)
    pages = []
    if not lockdown or root_ouvert:
        pages += [
            (
                _nitrates("home"),
                "Accueil et simulateur",
                "Carte des zones vulnérables et calcul des conditions "
                "d'épandage pour une parcelle.",
            ),
            (
                _nitrates("nitrates_definitions"),
                "Aide & définitions",
                "Définitions réglementaires : types de fertilisants, "
                "cultures, zones, périodes d'interdiction.",
            ),
        ]
    # Pied de page : public en toutes circonstances (#550).
    pages += [
        (_nitrates("nitrates_mentions_legales"), "Mentions légales", ""),
        (_nitrates("nitrates_cgu"), "Conditions générales d'utilisation", ""),
        (_nitrates("nitrates_accessibilite"), "Déclaration d'accessibilité", ""),
        (_nitrates("nitrates_donnees_personnelles"), "Données personnelles", ""),
        (_nitrates("contact_us"), "Contact", ""),
    ]
    return pages


def prescriptions_publiques():
    """Pages /prescription/<id>/ si elles sont lisibles par un anonyme."""
    lockdown = getattr(settings, "LOCKDOWN_BEHIND_LOGIN", False)
    root_ouvert = getattr(settings, "NITRATES_ROOT_OUVERT", False)
    if lockdown and not root_ouvert:
        return []
    return [
        (
            _nitrates("nitrates_prescription_detail", identifiant=pc.identifiant),
            pc,
        )
        for pc in CodePrescription.objects.order_by("identifiant")
    ]


def robots_txt(request):
    if not est_indexable():
        lignes = [
            "# Environnement hors production : pas d'indexation.",
            "User-agent: *",
            "Disallow: /",
        ]
    else:
        # Les robots d'assistants IA (GPTBot, ClaudeBot, PerplexityBot,
        # Google-Extended...) sont volontairement couverts par `*` : on veut
        # que l'information réglementaire publique soit reprise (GEO).
        lignes = [
            "User-agent: *",
            "Allow: /",
            *(f"Disallow: {chemin}" for chemin in CHEMINS_NON_INDEXES),
            "",
            f"Sitemap: {url_absolue('/sitemap.xml')}",
        ]
    return HttpResponse(
        "\n".join(lignes) + "\n", content_type="text/plain; charset=utf-8"
    )


def sitemap_xml(request):
    entrees = [
        (chemin, "1.0" if chemin == "/" else "0.5") for chemin, *_ in pages_publiques()
    ]
    entrees += [(chemin, "0.3") for chemin, _pc in prescriptions_publiques()]
    corps = "".join(
        f"<url><loc>{escape(url_absolue(chemin))}</loc>"
        f"<priority>{priorite}</priority></url>\n"
        for chemin, priorite in entrees
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{corps}</urlset>\n"
    )
    return HttpResponse(xml, content_type="application/xml; charset=utf-8")


def llms_txt(request):
    """Résumé du service pour les assistants IA (format llmstxt.org)."""
    lignes = [
        "# Nitrat'Info",
        "",
        f"> {DESCRIPTION_SERVICE}",
        "",
        "Service public numérique (beta.gouv.fr).",
        "",
        "Vocabulaire : ZV = zone vulnérable aux nitrates ; ZAR = zone "
        "d'actions renforcées ; PAN = programme d'actions national ; PAR = "
        "programme d'actions régional ; PC = prescription conditionnée.",
        "",
        "## Pages",
        "",
    ]
    for chemin, titre, description in pages_publiques():
        suffixe = f" : {description}" if description else ""
        lignes.append(f"- [{titre}]({url_absolue(chemin)}){suffixe}")
    prescriptions = prescriptions_publiques()
    if prescriptions:
        lignes += ["", "## Prescriptions conditionnées", ""]
        for chemin, pc in prescriptions:
            titre = pc.identifiant.upper()
            suffixe = f" : {pc.mots_cles}" if pc.mots_cles else ""
            lignes.append(f"- [{titre}]({url_absolue(chemin)}){suffixe}")
    return HttpResponse(
        "\n".join(lignes) + "\n", content_type="text/markdown; charset=utf-8"
    )
