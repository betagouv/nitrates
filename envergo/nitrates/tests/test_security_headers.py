"""Headers de securite complementaires nitrates (#265, findings ZAP DashLord).

Le middleware SecurityHeadersMiddleware pose Permissions-Policy et
Cross-Origin-Resource-Policy, non geres nativement par Django 4.2. COEP est
volontairement omis (casserait carto/Matomo/Sentry/Crisp).
"""

from django.http import HttpResponse

from envergo.nitrates.middleware import SecurityHeadersMiddleware


def _run(response=None):
    mw = SecurityHeadersMiddleware(lambda req: HttpResponse("ok"))
    return mw.process_response(None, response or HttpResponse("ok"))


def test_permissions_policy_present():
    response = _run()
    assert "Permissions-Policy" in response
    policy = response["Permissions-Policy"]
    # API sensibles neutralisees
    assert "camera=()" in policy
    assert "microphone=()" in policy
    assert "payment=()" in policy
    # geolocation laissee active pour notre origine (carte)
    assert "geolocation=(self)" in policy


def test_corp_same_origin():
    response = _run()
    assert response["Cross-Origin-Resource-Policy"] == "same-origin"


def test_coep_volontairement_absent():
    """COEP omis : il casserait les ressources tierces (carto, Matomo...)."""
    response = _run()
    assert "Cross-Origin-Embedder-Policy" not in response


def test_ne_surcharge_pas_un_header_existant():
    """Une vue peut poser ses propres headers -> le middleware ne les ecrase pas."""
    r = HttpResponse("ok")
    r["Permissions-Policy"] = "geolocation=()"
    r["Cross-Origin-Resource-Policy"] = "cross-origin"
    _run(r)
    assert r["Permissions-Policy"] == "geolocation=()"
    assert r["Cross-Origin-Resource-Policy"] == "cross-origin"
