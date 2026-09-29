"""CSP nitrates : header enforce + périmètre resserré + exception admin (#261).

Le staging tourne sous config.settings.production, où SECURE_CSP est désormais
peuplé (promu depuis le report-only), resserré au périmètre réel de nitrates.
"""

from django.http import HttpResponse
from django.test import override_settings

from envergo.decorators.csp import csp_update
from envergo.middleware.csp import ContentSecurityPolicyMiddleware

CSP_ENFORCE = "Content-Security-Policy"
CSP_REPORT_ONLY = "Content-Security-Policy-Report-Only"

POLICY = {
    "default-src": ["'self'"],
    "script-src": ["'self'", "'unsafe-inline'"],
    "img-src": ["'self'", "https://data.geopf.fr"],
    "object-src": ["'none'"],
    "report-uri": "/csp/reports/",
}


def _run_middleware(rf, response=None):
    request = rf.get("/")
    middleware = ContentSecurityPolicyMiddleware(lambda req: HttpResponse("ok"))
    middleware.process_request(request)
    return middleware.process_response(request, response or HttpResponse("ok"))


@override_settings(SECURE_CSP=POLICY, SECURE_CSP_REPORT_ONLY=POLICY)
def test_enforce_header_present_when_policy_set(rf):
    """SECURE_CSP peuplé -> header enforce présent."""
    response = _run_middleware(rf)
    assert CSP_ENFORCE in response
    assert "default-src 'self'" in response[CSP_ENFORCE]
    assert "object-src 'none'" in response[CSP_ENFORCE]


@override_settings(SECURE_CSP={}, SECURE_CSP_REPORT_ONLY=POLICY)
def test_enforce_header_absent_when_policy_empty(rf):
    """SECURE_CSP vide -> pas de header enforce, report-only seul (pré-#261)."""
    response = _run_middleware(rf)
    assert CSP_ENFORCE not in response
    assert CSP_REPORT_ONLY in response


class TestProductionPolicyScope:
    """La politique de production ne doit PAS hériter des origines Envergo.

    On lit le bloc _CSP_POLICY dans le source (le module production.py entier
    n'est pas importable en test : il dépend de sentry_sdk / secrets absents).
    """

    def _policy_source(self):
        from pathlib import Path

        import config

        # config/__init__.py -> config/settings/production.py, sans importer
        # le module (qui tirerait sentry_sdk et les secrets prod). On borne au
        # bloc CSP (définitions _GEOPF/_BAN... + dict _CSP_POLICY).
        prod = Path(config.__file__).parent / "settings" / "production.py"
        src = prod.read_text()
        start = src.index("_GEOPF = ")
        end = src.index("SECURE_CSP_REPORT_ONLY", start)
        return src[start:end]

    def test_ign_and_ban_present(self):
        pol = self._policy_source()
        assert "data.geopf.fr" in pol  # IGN / Géoplateforme
        assert "api-adresse.data.gouv.fr" in pol  # BAN
        assert "geo.api.gouv.fr" in pol  # commune

    def test_no_envergo_third_parties(self):
        # Gardés volontairement : sentry.incubateur.net (monitoring) et
        # *.beta.gouv.fr (Matomo, à implémenter). Ce ne sont pas des dépendances
        # tierces Envergo. On vérifie l'absence des services Envergo non utilisés.
        pol = self._policy_source()
        for banned in (
            "crisp.chat",
            "demarches-simplifiees",
            "scw.cloud",
            "sentry-cdn",
        ):
            assert banned not in pol, f"{banned} ne devrait pas être dans la CSP"


@override_settings(SECURE_CSP=POLICY)
def test_admin_yaml_view_extends_policy_with_cdns(rf):
    """csp_update sur la vue admin ajoute cdnjs/unpkg sans toucher au global."""

    @csp_update(config={"script-src": ["https://cdnjs.cloudflare.com"]})
    def _view(request):
        return HttpResponse("ok")

    response = _run_middleware(rf, response=_view(rf.get("/")))
    script = response[CSP_ENFORCE]
    assert "cdnjs.cloudflare.com" in script  # exception admin
    assert "'self'" in script  # base préservée


def test_csp_autorise_les_medias_cellar_en_domaine_nu():
    """Régression (staging, 03/08 -> 29/09) : toutes les images de l'app de
    validation étaient bloquées par la CSP.

    Cellar adresse le bucket EN CHEMIN
    (`cellar-c2.services.clever-cloud.com/bucket-nitrates/...`), là où
    l'ancien fournisseur (scw.cloud) l'adressait en sous-domaine. La
    politique avait gardé la forme `*.domaine`, or en CSP un wildcard ne
    couvre PAS le domaine nu. Les juristes ont donc validé pendant deux mois
    sans leurs captures Miro de référence.

    Ce test lit la politique réelle de `config.settings.production`, pas une
    copie : c'est ce qui le rend utile.
    """
    # On n'importe PAS config.settings.production (il tire sentry_sdk, absent
    # en local) : on lit les sources declarees dans le fichier, ce qui teste
    # bien la politique reelle et non une copie.
    import ast
    from pathlib import Path

    src = Path("config/settings/production.py").read_text(encoding="utf-8")
    arbre = ast.parse(src)
    consts, policy = {}, None
    for noeud in arbre.body:
        if isinstance(noeud, ast.Assign) and isinstance(noeud.targets[0], ast.Name):
            nom = noeud.targets[0].id
            if isinstance(noeud.value, ast.Constant) and isinstance(
                noeud.value.value, str
            ):
                consts[nom] = noeud.value.value
            elif nom == "_CSP_POLICY" and isinstance(noeud.value, ast.Dict):
                policy = noeud.value
    assert policy is not None, "_CSP_POLICY introuvable dans production.py"

    def sources_de(directive: str) -> list:
        for cle, val in zip(policy.keys, policy.values):
            if getattr(cle, "value", None) != directive:
                continue
            out = []
            for elt in getattr(val, "elts", []):
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    out.append(elt.value)
                elif isinstance(elt, ast.Name) and elt.id in consts:
                    out.append(consts[elt.id])
            return out
        return []

    url_reelle = (
        "https://cellar-c2.services.clever-cloud.com"
        "/bucket-nitrates/media/nitrates_validation/x.png"
    )

    def couvre(source: str, url: str) -> bool:
        """Règle CSP host-source : `*.a.b` ne matche pas `a.b`."""
        from urllib.parse import urlparse

        src, cible = urlparse(source), urlparse(url)
        if src.scheme and src.scheme != cible.scheme:
            return False
        if src.netloc.startswith("*."):
            return cible.netloc.endswith(src.netloc[1:]) and (
                cible.netloc != src.netloc[2:]
            )
        return src.netloc == cible.netloc

    for directive in ("img-src", "media-src"):
        sources = sources_de(directive)
        assert any(
            couvre(s, url_reelle) for s in sources
        ), f"{directive} bloque les médias Cellar servis en domaine nu"

    # Garde-fou : on n'a pas élargi à n'importe quoi au passage.
    sources_img = sources_de("img-src")
    assert not any(couvre(s, "https://evil.example.com/x.png") for s in sources_img)
