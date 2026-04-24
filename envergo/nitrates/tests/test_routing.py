import pytest
from django.contrib.sites.models import Site

pytestmark = pytest.mark.django_db


@pytest.fixture
def nitrates_site(settings):
    settings.ENVERGO_NITRATES_DOMAIN = "testserver"
    site, _ = Site.objects.get_or_create(domain="testserver")
    site.name = "Simulateur nitrates"
    site.save()
    return site


def test_home_served_on_nitrates_site(client, nitrates_site):
    """The nitrates home is served when the middleware matches the nitrates domain."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"Simulateur nitrates" in response.content


def test_middleware_uses_nitrates_urlconf(client, nitrates_site):
    """The middleware routes nitrates requests through config.urls_nitrates."""
    response = client.get("/")
    assert response.wsgi_request.urlconf == "config.urls_nitrates"
