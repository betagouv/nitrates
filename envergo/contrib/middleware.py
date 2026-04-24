import logging

from django.conf import settings
from django.contrib.sites.models import Site
from django.http import HttpResponseRedirect

logger = logging.getLogger(__name__)


class SetUrlConfBasedOnSite:
    """Route every request to the nitrates urlconf.

    REVERT_AT_MERGE_TIME_FOR_UPSTREAM_ENVERGO
    MVP nitrates: the fork only serves the nitrates site. The
    amenagement and haie urlconfs remain in the repo as inactive
    code to ease a future remerge with MTES-MCT/envergo upstream,
    but the middleware no longer routes to them.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.urlconf = "config.urls_nitrates"
        try:
            site = Site.objects.get_current(request)
        except Site.DoesNotExist:
            logger.warning(
                f"Found url with bad domain in the wild: {request.get_host()}{request.get_full_path()}"
            )
            new_url = (
                f"https://{settings.ENVERGO_NITRATES_DOMAIN}{request.get_full_path()}"
            )
            return HttpResponseRedirect(new_url)

        request.site = site
        request.base_template = "nitrates/base.html"

        response = self.get_response(request)

        return response
