from django.conf import settings
from django.shortcuts import redirect

from envergo.contrib.sites_from_settings import build_site_from_settings


class SetUrlConfBasedOnSite:
    """Route every request to the nitrates urlconf.

    REVERT_AT_MERGE_TIME_FOR_UPSTREAM_ENVERGO

    Le fork ne sert que le site nitrates. Les urlconfs amenagement et
    haie restent dans le repo en code dormant pour faciliter un futur
    remerge avec MTES-MCT/envergo upstream, mais le middleware ne route
    plus vers eux.

    Upstream fait dependre l'identite du site d'une ligne en base
    (Site.objects.get_current(request), qui matche le Host: HTTP sur
    django_site.domain). Concretement il faut declarer son deploiement
    en base pour que l'app reponde : une app fraiche, ou une base
    reinitialisee, renvoie 500 partout (y compris /admin/login/) tant
    que la ligne n'existe pas. On ne veut pas de ce couplage : le
    domaine servi est une donnee de configuration, pas une donnee
    metier, donc il vient de l'environnement.

    `request.site` est desormais construit en memoire depuis
    settings.ENVERGO_NITRATES_DOMAIN. Aucune requete DB sur le chemin
    requete, aucune ligne a declarer : l'app demarre et sert.

    Le modele Site reste dans INSTALLED_APPS (les FK TopBar.site et
    analytics.Event.site en dependent, cf. code dormant upstream), il
    n'est simplement plus consulte pour resoudre le site courant.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.urlconf = "config.urls_nitrates"
        request.base_template = "nitrates/base.html"
        request.site = build_site_from_settings()
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
            # Pages publiques des codes de prescription (#147) : contenu
            # reglementaire read-only, linke depuis les resultats du root
            # public (renvois "voir PC11 Grand Est" inseres par les juristes).
            if path.startswith("/prescription/"):
                return True
            # /simulateur/debug/ (mal nomme : ce n'est PAS un panneau debug mais
            # l'endpoint de GEOLOCALISATION appele au clic sur la carte, carte
            # #57). Sa reponse porte `simulateur_ouvert` qui pilote l'affichage
            # du formulaire sur le root public. Sans cet exempt, le clic carte
            # est redirige vers le login (302 suivi en silence par fetch -> HTML
            # au lieu de JSON), `simulateur_ouvert` est absent et le formulaire
            # ne s'affiche JAMAIS (symptome : "cliquez sur la carte" fige). On
            # l'exempte AVANT le prefixe /simulateur/ (qui, lui, reste ferme).
            if path.startswith("/simulateur/debug/"):
                return True
            # Page « Aide & définitions » (carte #110) : contenu éditorial
            # public (définitions réglementaires), accessible depuis l'onglet
            # de navigation du root ouvert. Chemin exact, rien d'autre.
            if path == "/definitions/":
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
