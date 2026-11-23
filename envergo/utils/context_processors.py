from django.conf import settings
from django.templatetags.static import static
from django.urls import NoReverseMatch, reverse

from envergo.middleware.csp import get_nonce
from envergo.users.forms import NewsletterOptInForm


def settings_context(_request):
    """Settings available by default to the templates context."""
    # Note: we intentionally do NOT expose the entire settings
    # to prevent accidental leaking of sensitive information

    # We disable the chatbox on the catchment area page
    # Because it breaks the map, for reasons I just don't understand
    try:
        catchment_area_page_url = reverse("demo_catchment_area")
    except NoReverseMatch:
        catchment_area_page_url = None

    if _request.path == catchment_area_page_url:
        chatbox_enabled = False
    else:
        chatbox_enabled = (
            settings.CRISP["HAIE"]["CHATBOX_ENABLED"]
            if _request.site.domain == settings.ENVERGO_HAIE_DOMAIN
            else settings.CRISP["AMENAGEMENT"]["CHATBOX_ENABLED"]
        )

    if _request.site.domain == settings.ENVERGO_HAIE_DOMAIN:
        analytics = settings.ANALYTICS["HAIE"]
    elif _request.site.domain == settings.ENVERGO_NITRATES_DOMAIN:
        analytics = settings.ANALYTICS["NITRATES"]
    else:
        analytics = settings.ANALYTICS["AMENAGEMENT"]

    crisp_website_id = (
        settings.CRISP["HAIE"]["WEBSITE_ID"]
        if _request.site.domain == settings.ENVERGO_HAIE_DOMAIN
        else settings.CRISP["AMENAGEMENT"]["WEBSITE_ID"]
    )

    return {
        "DEBUG": settings.DEBUG,
        "ANALYTICS": analytics,
        "SENTRY_DSN": settings.SENTRY_DSN,
        "SENTRY_KEY": settings.SENTRY_KEY,
        "ENV_NAME": settings.ENV_NAME,
        "CRISP_CHATBOX_ENABLED": chatbox_enabled,
        "CRISP_WEBSITE_ID": crisp_website_id,
        "HAIE_FAQ_URLS": settings.HAIE_FAQ_URLS,
        "DISPLAY_TEACHING_TOPBAR": settings.DISPLAY_TEACHING_TOPBAR,
    }


def multi_sites_context(_request):
    """Give some useful context to handle multi sites"""
    # _request.base_template has been populated by a middleware
    return {
        "base_template": _request.base_template,
        "contact_url": f"{reverse("contact_us")}"
        f"{settings.CONTACT_TEAM_ANCHOR if _request.site.domain == settings.ENVERGO_HAIE_DOMAIN else ''}",
        "contact_dossier_anchor": settings.CONTACT_DOSSIER_ANCHOR,
        "preview_image_url": (
            _request.build_absolute_uri(static("images/preview_haie.png"))
            if _request.site.domain == settings.ENVERGO_HAIE_DOMAIN
            else None
        ),
    }


def newsletter_context(_request):
    return {
        "newsletter_opt_in_form": NewsletterOptInForm(),
    }


def csp(request):
    """Expose le nonce CSP de la requête aux gabarits (`{{ csp_nonce }}`).

    REVERT_AT_MERGE_TIME_FOR_UPSTREAM_ENVERGO
    Backport de `django.template.context_processors.csp` (Django 6.0), comme
    le middleware de `envergo/middleware/csp.py` : à remplacer par celui de
    Django au passage en 6.0. Le nonce est un `LazyNonce` : il n'est généré
    que si un gabarit le lit, et le middleware ne l'écrit dans l'en-tête que
    dans ce cas. Chaque `<script>` inline doit porter `nonce="{{ csp_nonce }}"`,
    sinon la CSP de production le bloque.
    """
    return {"csp_nonce": get_nonce(request)}
