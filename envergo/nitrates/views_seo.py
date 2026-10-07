"""Référencement SEO et GEO : robots.txt, sitemap.xml, llms.txt (#290, #565).

Le CONTENU de ces fichiers vit dans les templates `nitrates/seo/` (lisibles
en revue). Ce module ne porte que la logique : prod ou pas, et quelles pages
sont réellement publiques dans la configuration courante.

REGLE : tout ce qui sert le référencement (SEO, moteurs de recherche) et le
GEO (Generative Engine Optimization, reprise par les assistants IA) est en
ACCES LIBRE, sans authentification, quel que soit l'état du lockdown. Un
robot ne se loggue pas : un robots.txt derrière le login admin est un
robots.txt qui n'existe pas. Les chemins sont exemptés une fois pour toutes
dans `CHEMINS_SEO_PUBLICS` (envergo/contrib/middleware.py), et un test
verrouille la règle (test_seo.py). Cf. docs/seo_geo.md.

Ce qui distingue les environnements, c'est le CONTENU du robots.txt, pas son
accessibilité : seule la prod s'ouvre à l'indexation, dev et staging
répondent `Disallow: /` pour ne jamais concurrencer la prod dans les
résultats de recherche.
"""

from django.conf import settings
from django.shortcuts import render
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


def est_indexable():
    return getattr(settings, "ENV_NAME", "") in ENVS_INDEXABLES


def url_absolue(chemin):
    return f"https://{settings.ENVERGO_NITRATES_DOMAIN}{chemin}"


def _nitrates(nom, **kwargs):
    return reverse(nom, urlconf="config.urls_nitrates", kwargs=kwargs or None)


def _root_public():
    lockdown = getattr(settings, "LOCKDOWN_BEHIND_LOGIN", False)
    return not lockdown or getattr(settings, "NITRATES_ROOT_OUVERT", False)


def pages_publiques():
    """Pages de contenu lisibles par un anonyme, dans l'ordre d'importance.

    Liste de tuples (chemin, titre, description courte). Le simulateur
    interne (/simulateur/) n'y figure jamais : c'est un outil de recette.
    """
    pages = []
    if _root_public():
        pages += [
            (
                _nitrates("home"),
                "Accueil et simulateur",
                "situer sa parcelle sur la carte, répondre à quelques questions "
                "sur la culture et le fertilisant, obtenir le calendrier "
                "d'épandage et les conditions à respecter.",
            ),
            (
                _nitrates("nitrates_definitions"),
                "Aide & définitions",
                "définitions des termes de la réglementation nitrates utilisés "
                "par le simulateur.",
            ),
        ]
    # Pied de page : public en toutes circonstances (#550).
    pages += [
        (
            _nitrates("nitrates_cgu"),
            "Conditions générales d'utilisation",
            "objet du service, périmètre réglementaire, territoires "
            "d'expérimentation.",
        ),
        (_nitrates("nitrates_mentions_legales"), "Mentions légales", ""),
        (_nitrates("nitrates_accessibilite"), "Déclaration d'accessibilité", ""),
        (_nitrates("nitrates_donnees_personnelles"), "Données personnelles", ""),
        (_nitrates("contact_us"), "Contact", ""),
    ]
    return pages


def prescriptions_publiques():
    """Pages /prescription/<id>/ si elles sont lisibles par un anonyme."""
    if not _root_public():
        return []
    return [
        (
            _nitrates("nitrates_prescription_detail", identifiant=pc.identifiant),
            pc,
        )
        for pc in CodePrescription.objects.order_by("identifiant")
    ]


def robots_txt(request):
    if est_indexable():
        template = "nitrates/seo/robots.txt"
    else:
        template = "nitrates/seo/robots_hors_prod.txt"
    contexte = {
        "domaine": settings.ENVERGO_NITRATES_DOMAIN,
        "env_name": getattr(settings, "ENV_NAME", ""),
        "chemins_non_indexes": CHEMINS_NON_INDEXES,
        "url_sitemap": url_absolue("/sitemap.xml"),
    }
    return render(request, template, contexte, content_type="text/plain; charset=utf-8")


def sitemap_xml(request):
    entrees = [
        (url_absolue(chemin), "1.0" if chemin == "/" else "0.5")
        for chemin, _titre, _description in pages_publiques()
    ]
    entrees += [
        (url_absolue(chemin), "0.3") for chemin, _pc in prescriptions_publiques()
    ]
    return render(
        request,
        "nitrates/seo/sitemap.xml",
        {"entrees": entrees},
        content_type="application/xml; charset=utf-8",
    )


def llms_txt(request):
    """Présentation du service pour les assistants IA (format llmstxt.org)."""
    contexte = {
        "url_accueil": url_absolue("/"),
        "pages": [
            (url_absolue(chemin), titre, description)
            for chemin, titre, description in pages_publiques()
        ],
        "prescriptions": [
            (url_absolue(chemin), pc) for chemin, pc in prescriptions_publiques()
        ],
    }
    return render(
        request,
        "nitrates/seo/llms.txt",
        contexte,
        content_type="text/markdown; charset=utf-8",
    )
