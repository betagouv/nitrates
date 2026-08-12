"""Middlewares specifiques au produit nitrates."""

from django.utils.deprecation import MiddlewareMixin


class SecurityHeadersMiddleware(MiddlewareMixin):
    """Pose les headers de securite HTTP non geres nativement par Django 4.2.

    Complete les headers deja fournis par Django (HSTS, X-Frame-Options,
    Referrer-Policy, Cross-Origin-Opener-Policy, nosniff) et par le middleware
    CSP. Findings du scan ZAP DashLord (#265).

    Perimetre volontairement conservateur :
    - Permissions-Policy : neutralise les API navigateur non utilisees par le
      simulateur (camera, micro, USB, paiement...). La geolocalisation est
      laissee active (`geolocation=(self)`) car la carte peut vouloir centrer
      sur l'utilisateur.
    - Cross-Origin-Resource-Policy: same-origin : empeche l'inclusion de nos
      ressources par un autre site.

    Cross-Origin-Embedder-Policy (COEP) est volontairement OMIS : `require-corp`
    casserait le chargement des tuiles cartographiques IGN, de Matomo, Sentry et
    Crisp (ressources tierces sans en-tete CORP), pour un benefice de securite
    marginal sur ce type de site public.
    """

    #: API navigateur explicitement neutralisees. Liste allowlist "()" = interdit
    #: partout ; `geolocation=(self)` = autorise seulement notre origine.
    PERMISSIONS_POLICY = (
        "accelerometer=(), autoplay=(), camera=(), display-capture=(), "
        "encrypted-media=(), fullscreen=(self), geolocation=(self), "
        "gyroscope=(), magnetometer=(), microphone=(), midi=(), payment=(), "
        "usb=(), xr-spatial-tracking=()"
    )

    def process_response(self, request, response):
        # Ne pas ecraser un header pose en amont (view ou autre middleware).
        if "Permissions-Policy" not in response:
            response["Permissions-Policy"] = self.PERMISSIONS_POLICY
        if "Cross-Origin-Resource-Policy" not in response:
            response["Cross-Origin-Resource-Policy"] = "same-origin"
        return response
