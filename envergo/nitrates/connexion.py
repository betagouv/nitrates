"""Point d'entrée unique de la connexion à l'admin nitrates (#577).

Un visiteur non connecté qui tombe sur une page réservée est envoyé
DIRECTEMENT vers ProConnect, jamais vers la page de login de l'admin Django :
  - c'est plus rapide (cette page n'affiche que le bouton ProConnect) ;
  - l'URL de la page de login contient le préfixe admin, volontairement
    secret en prod (`DJANGO_ADMIN_URL`). La renvoyer à un anonyme dans un
    en-tête `Location` le révélait à n'importe quel scanner.

Sans ProConnect (local, tests), on retombe sur le login admin classique,
seule voie d'authentification disponible.
"""

from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.urls import reverse


def url_connexion():
    """URL vers laquelle envoyer un anonyme qui doit se connecter."""
    if getattr(settings, "PROCONNECT_ENABLED", False):
        return reverse("oidc_authentication_init")
    return reverse("admin:login")


def rediriger_vers_connexion(request):
    """Redirige vers la connexion en conservant la page demandée (`next`)."""
    return redirect_to_login(request.get_full_path(), url_connexion())


def staff_member_required(view_func):
    """Comme celui de Django, mais redirige via `url_connexion()`.

    Le décorateur de Django renvoie toujours vers `admin:login`, donc vers
    le préfixe secret. Même contrat d'accès : utilisateur actif et staff.

    Seul un ANONYME est envoyé vers la connexion. Un utilisateur déjà connecté
    mais sans droits staff reçoit une 403 : le renvoyer vers ProConnect le
    reconnecterait aussitôt (session SSO active) et bouclerait.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_active and request.user.is_staff:
            return view_func(request, *args, **kwargs)
        if request.user.is_authenticated:
            raise PermissionDenied
        return rediriger_vers_connexion(request)

    return _wrapped
