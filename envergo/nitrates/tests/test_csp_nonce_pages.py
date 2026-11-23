"""CSP sans 'unsafe-inline' dans script-src : chaque <script> inline porte le
nonce de la requête.

Dès qu'un nonce figure dans script-src, les navigateurs ignorent
'unsafe-inline' : un seul <script> inline sans nonce est bloqué en production.
On rend donc les pages réelles (simulateur public, back-office) avec une
politique à nonce et on vérifie que chaque script inline porte exactement le
nonce annoncé dans l'en-tête.
"""

import ast
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.test import override_settings
from django.urls import reverse

from envergo.contrib.middleware import SetUrlConfBasedOnSite
from envergo.middleware.csp import ContentSecurityPolicyMiddleware
from envergo.nitrates.views_admin_yaml import _CSP_ADMIN_YAML
from envergo.pages.views import rate_limited, server_error
from envergo.utils.csp import CSP

pytestmark = pytest.mark.django_db

POLITIQUE_A_NONCE = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF, CSP.NONCE],
}

# Types de <script> que le navigateur n'exécute pas (données) : pas de nonce.
TYPES_DONNEES = {"application/json", "application/ld+json"}


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inline = []

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        attrs = dict(attrs)
        if "src" in attrs or (attrs.get("type") or "").lower() in TYPES_DONNEES:
            return
        self.inline.append(attrs)


def _nonce_entete(reponse):
    entete = reponse["Content-Security-Policy"]
    m = re.search(r"'nonce-([^']+)'", entete)
    assert m, f"pas de nonce dans l'en-tête : {entete}"
    return m.group(1)


def _verifier_nonces(reponse, statut=200):
    assert reponse.status_code == statut
    html = reponse.content.decode()
    parser = _Scripts()
    parser.feed(html)
    assert parser.inline, "la page devrait contenir des scripts inline"
    nonce = _nonce_entete(reponse)
    sans_nonce = [a for a in parser.inline if a.get("nonce") != nonce]
    assert not sans_nonce, f"<script> inline sans le nonce de la requête : {sans_nonce}"
    assert "'unsafe-inline'" not in reponse["Content-Security-Policy"]


def _url(nom):
    return reverse(nom, urlconf="config.urls_nitrates")


@pytest.fixture
def nitrates_site(settings):
    settings.ENVERGO_NITRATES_DOMAIN = "testserver"
    site, _ = Site.objects.get_or_create(domain="testserver")
    return site


@pytest.fixture
def staff_client(client):
    u = get_user_model().objects.create_user(
        email="csp@test.local", name="CSP", password="x", is_staff=True
    )
    client.force_login(u)
    return client


@override_settings(SECURE_CSP=POLITIQUE_A_NONCE, SECURE_CSP_REPORT_ONLY={})
@pytest.mark.parametrize(
    "chemin",
    ["/", "/simulateur/", "/definitions/", "/mentions-legales/", "/accessibilite/"],
)
def test_pages_publiques_scripts_inline_avec_nonce(client, nitrates_site, chemin):
    _verifier_nonces(client.get(chemin))


@override_settings(SECURE_CSP=POLITIQUE_A_NONCE, SECURE_CSP_REPORT_ONLY={})
@pytest.mark.parametrize(
    "nom",
    [
        "nitrates_admin_validation_index",
        "nitrates_admin_ouverture_index",
        "nitrates_admin_matrice_index",
    ],
)
def test_pages_back_office_scripts_inline_avec_nonce(staff_client, nitrates_site, nom):
    _verifier_nonces(staff_client.get(_url(nom)))


@override_settings(SECURE_CSP=POLITIQUE_A_NONCE, SECURE_CSP_REPORT_ONLY={})
@pytest.mark.parametrize("vue,statut", [(server_error, 500), (rate_limited, 429)])
def test_pages_erreur_500_429_scripts_inline_avec_nonce(rf, nitrates_site, vue, statut):
    """Les gestionnaires 500 / 429 rendent leur gabarit avec un contexte
    construit à la main (pas de RequestContext) : le nonce doit y être."""
    chaine = ContentSecurityPolicyMiddleware(SetUrlConfBasedOnSite(vue))
    _verifier_nonces(chaine(rf.get("/")), statut=statut)


@override_settings(SECURE_CSP=POLITIQUE_A_NONCE, SECURE_CSP_REPORT_ONLY={})
def test_page_404_scripts_inline_avec_nonce(client, nitrates_site):
    _verifier_nonces(client.get("/page-qui-n-existe-pas/"), statut=404)


@override_settings(SECURE_CSP=POLITIQUE_A_NONCE, SECURE_CSP_REPORT_ONLY={})
def test_nonce_change_a_chaque_requete(client, nitrates_site):
    """Un nonce figé (page en cache, nonce en dur) annulerait la protection."""
    n1 = _nonce_entete(client.get("/"))
    n2 = _nonce_entete(client.get("/"))
    assert n1 != n2


@override_settings(SECURE_CSP=POLITIQUE_A_NONCE, SECURE_CSP_REPORT_ONLY={})
def test_back_office_htmx_servi_en_propre(staff_client, nitrates_site):
    """htmx du layout admin : plus de CDN (unpkg bloqué par la CSP hors
    éditeur YAML), et les scripts des fragments swappés reçoivent le nonce de
    la page via htmx.config.inlineScriptNonce."""
    html = staff_client.get(_url("nitrates_admin_validation_index")).content.decode()
    assert "unpkg.com" not in html
    assert "nitrates/vendor/htmx-2.0.4.min.js" in html
    assert "inlineScriptNonce" in html


class TestPolitiqueProduction:
    """Lit _CSP_POLICY dans le source de production.py (module non importable
    en test : sentry_sdk, secrets), comme test_csp_header."""

    def _directive(self, nom):
        src = Path("config/settings/production.py").read_text(encoding="utf-8")
        for noeud in ast.parse(src).body:
            if (
                isinstance(noeud, ast.Assign)
                and isinstance(noeud.targets[0], ast.Name)
                and noeud.targets[0].id == "_CSP_POLICY"
            ):
                for cle, val in zip(noeud.value.keys, noeud.value.values):
                    if getattr(cle, "value", None) == nom:
                        return [ast.unparse(e) for e in val.elts]
        raise AssertionError(f"directive {nom} introuvable dans _CSP_POLICY")

    def test_script_src_sans_unsafe_inline_et_avec_nonce(self):
        sources = self._directive("script-src")
        assert "CSP.UNSAFE_INLINE" not in sources
        assert "\"'unsafe-inline'\"" not in sources
        assert "CSP.NONCE" in sources

    def test_style_src_garde_unsafe_inline(self):
        # Hors périmètre de ce chantier : documente le choix.
        assert "CSP.UNSAFE_INLINE" in self._directive("style-src")


def test_csp_admin_yaml_ne_remet_pas_unsafe_inline():
    for sources in _CSP_ADMIN_YAML.values():
        assert CSP.UNSAFE_INLINE not in sources
        assert "unsafe-inline" not in " ".join(sources)
