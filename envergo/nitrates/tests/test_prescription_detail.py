"""Page publique d'un code de prescription (#147, demande juristes).

Sert n'importe quel PC par identifiant pour que les rédactions puissent
se référencer par lien direct (« voir PC11 Grand Est »).
"""

import pytest
from django.contrib.sites.models import Site

from envergo.nitrates.models import CodePrescription

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def nitrates_site(settings):
    """Route les requêtes de test vers config.urls_nitrates (multisite par
    domaine, cf. test_routing.py)."""
    settings.ENVERGO_NITRATES_DOMAIN = "testserver"
    site, _ = Site.objects.get_or_create(domain="testserver")
    site.name = "Simulateur nitrates"
    site.save()
    return site


def _url(identifiant):
    return f"/prescription/{identifiant}/"


def test_pc_de_base_rendu_texte_court(client):
    # pc5 n'a pas de contenu riche dans la fixture : fallback texte_court.
    r = client.get(_url("pc5"))
    assert r.status_code == 200
    html = r.content.decode()
    assert "PC5" in html
    # Fragment sans apostrophe (échappée en &#x27; dans le HTML).
    assert "engrais min" in html


def test_declinaison_geographique_servie(client):
    # Les déclinaisons (pc11_ge...) sont seedées par la fixture depuis #147.
    r = client.get(_url("pc11_ge"))
    assert r.status_code == 200
    assert "PC11_GE" in r.content.decode()


def test_pc_inconnu_404(client):
    assert client.get(_url("pc_nexiste_pas")).status_code == 404


def test_contenu_riche_prioritaire(client):
    """pc1 a des blocs seedés (#136) : le rendu riche prime sur texte_court."""
    r = client.get(_url("pc1"))
    assert r.status_code == 200
    html = r.content.decode()
    assert 'class="contenu-rich"' in html
    pc1 = CodePrescription.objects.get(identifiant="pc1")
    # Le fallback texte brut ne doit PAS être rendu en parallèle.
    assert pc1.texte_court.splitlines()[0] not in html


def test_exempt_du_lockdown_root_public(client, settings):
    """Quand le root public est ouvert, la page PC est lisible sans login
    (elle est linkée depuis les résultats du simulateur public)."""
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = True
    r = client.get(_url("pc1"))
    assert r.status_code == 200


def test_verrouillee_si_root_ferme(client, settings):
    """Lockdown sans ouverture du root : la page reste derrière le login."""
    settings.LOCKDOWN_BEHIND_LOGIN = True
    settings.NITRATES_ROOT_OUVERT = False
    r = client.get(_url("pc1"))
    assert r.status_code == 302
