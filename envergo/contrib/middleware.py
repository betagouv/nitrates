import logging

from django.conf import settings
from django.contrib.sites.models import Site
from django.shortcuts import redirect

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


class RequireLoginEverywhere:
    """Verrouille toutes les URL derriere une auth Django admin.

    REVERT_AT_MERGE_TIME_FOR_UPSTREAM_ENVERGO
    Staging nitrates ferme : tant qu'on n'ouvre pas le simulateur au
    public, toute requete anonyme est redirigee vers le login Django
    admin. A retirer (du settings et du fichier) le jour de la mise
    en ligne publique.

    Active si `settings.LOCKDOWN_BEHIND_LOGIN` est truthy. Sinon
    no-op : utile pour les tests et le dev local qui veulent acceder
    librement aux pages.

    Exempts (servis sans auth) :
      - tout chemin sous /{DJANGO_ADMIN_URL}/ (Django admin a sa
        propre auth, login inclus)
      - /static/*  (assets servis par whitenoise)
      - /healthcheck/  (sonde Scalingo, si on en ajoute une)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def _is_exempt(self, path):
        admin_url = getattr(settings, "ADMIN_URL", None)
        if admin_url and path.startswith("/" + admin_url.lstrip("/")):
            return True
        if path.startswith("/static/"):
            return True
        if path.startswith("/healthcheck/"):
            return True
        # ProConnect OIDC : les routes /oidc/* gerent leur propre flow auth.
        # Sans cet exempt, le middleware piege /oidc/authenticate/ et redirige
        # vers /admin/login/ -> boucle infinie de next= imbrique.
        if path.startswith("/oidc/"):
            return True
        # Root `/` ouvert aux alpha-testeurs (issue #113) : exempte SEULEMENT
        # la racine exacte, pas /simulateur/ ni l'admin qui restent fermes.
        if getattr(settings, "NITRATES_ROOT_OUVERT", False):
            if path == "/":
                return True
            # La page racine charge sa carte SIG en fetch() sur ces endpoints
            # de DONNEES PUBLIQUES read-only (zones reglementaires ZV/ZAR issues
            # des sources SIG officielles, referentiels de l'arbre). Sans cet
            # exempt, l'anonyme est redirige vers le login admin et le fetch
            # recoit du HTML au lieu de JSON -> carte vide + "Unexpected token
            # 'C', Connexion... is not valid JSON" (issue #197 suite). On ouvre
            # donc les memes donnees que la racine, rien de plus (ni /simulateur/
            # ni /api/arbre/ qui restent fermes).
            if path.startswith("/geojson/") or path.startswith("/api/referentiels/"):
                return True
        return False

    def __call__(self, request):
        if not getattr(settings, "LOCKDOWN_BEHIND_LOGIN", False):
            return self.get_response(request)
        if request.user.is_authenticated or self._is_exempt(request.path):
            return self.get_response(request)
        admin_url = getattr(settings, "ADMIN_URL", "admin/")
        login_url = "/" + admin_url.lstrip("/").rstrip("/") + "/login/"
        return redirect(f"{login_url}?next={request.get_full_path()}")
