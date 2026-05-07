import logging

from django.contrib.sites.models import Site

logger = logging.getLogger(__name__)


class SetUrlConfBasedOnSite:
    """Route every request to the nitrates urlconf.

    Le fork ne sert que le site nitrates. Les urlconfs amenagement et
    haie restent dans le repo en code dormant pour faciliter un futur
    remerge avec MTES-MCT/envergo upstream, mais le middleware ne route
    plus vers eux.

    Si le Host: HTTP entrant ne matche aucun Site en DB, on ne redirige
    pas (le routing est deja force vers nitrates) : on log juste un
    warning pour tracer les hits avec un domaine inattendu.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.urlconf = "config.urls_nitrates"
        request.base_template = "nitrates/base.html"
        try:
            request.site = Site.objects.get_current(request)
        except Site.DoesNotExist:
            # Host: ne matche aucun Site en DB. On ne redirige pas (routing
            # deja force vers nitrates). Fallback sur le Site nitrates fixe
            # pour que le code aval qui lit request.site.domain ne crash pas.
            logger.warning(
                "Request on unknown domain: %s%s",
                request.get_host(),
                request.get_full_path(),
            )
            request.site = Site.objects.filter(id=3).first()
        return self.get_response(request)
