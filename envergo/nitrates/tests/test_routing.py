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


def test_home_redirects_unauth_to_login(client, nitrates_site, settings):
    """En mode ferme (lockdown + root non ouvert aux alpha-testeurs, cf. #113),
    la racine `/` est protegee : un visiteur non authentifie est redirige vers
    le login. Le mode OUVERT (200 + bandeau construction) est teste a part
    dans test_root_alpha_construction.py."""
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = False
    response = client.get("/")
    assert response.status_code == 302
    assert "login" in response["Location"].lower()


def test_home_served_to_authenticated_user(client, nitrates_site, django_user_model):
    """Un utilisateur connecte (juriste/admin) voit le meme simulateur que
    `/simulateur/` quand il visite `/`."""
    user = django_user_model.objects.create_user(
        email="juriste@test.local", name="Juriste", password="x", is_active=True
    )
    client.force_login(user)
    response = client.get("/")
    assert response.status_code == 200
    # Le simulateur affiche son h1.
    assert b"r\xc3\xa8gles d'\xc3\xa9pandage" in response.content


def test_middleware_uses_nitrates_urlconf(client, nitrates_site):
    """The middleware routes nitrates requests through config.urls_nitrates."""
    response = client.get("/")
    assert response.wsgi_request.urlconf == "config.urls_nitrates"
