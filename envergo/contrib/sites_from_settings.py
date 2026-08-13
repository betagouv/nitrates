"""Resout le Site courant depuis les settings, sans jamais lire la base.

REVERT_AT_MERGE_TIME_FOR_UPSTREAM_ENVERGO

Upstream, l'identite du site servi est une ligne de la table
django_site : `Site.objects.get_current(request)` matche le Host: HTTP
entrant sur `django_site.domain` (ou, si SITE_ID est defini, fait un
get(pk=SITE_ID)). Dans les deux cas il faut avoir declare son
deploiement en base pour que l'app reponde. Une app fraiche, ou une
base reinitialisee, renvoie 500 partout tant que la ligne n'existe
pas -- y compris sur /admin/login/, parce que la LoginView de Django
appelle get_current_site() pour son contexte de template.

On refuse ce couplage : le domaine servi est une donnee de
configuration (elle vient de l'environnement, via
ENVERGO_NITRATES_DOMAIN), pas une donnee metier a saisir en base.

`get_current()` est le point unique par lequel passent tous les
appelants (LoginView de Django, get_current_site(), et le code dormant
Envergo). On le remplace donc ici par une version qui construit le
Site en memoire depuis les settings. Aucune requete, rien a declarer :
l'app demarre et sert.

Ce qui n'est PAS change :
  - le modele Site reste installe : les FK reelles confs.TopBar.site et
    analytics.Event.site en dependent (schema conserve pour le remerge
    upstream) ;
  - les autres managers (Site.objects.get/filter/all) restent
    intacts, donc l'admin des sites et le code qui lit explicitement
    une ligne continuent de voir la base telle qu'elle est.
"""

from django.conf import settings

NITRATES_SITE_ID = 3


def build_site_from_settings():
    """Construit (sans le sauvegarder) le Site nitrates depuis les settings."""
    from django.contrib.sites.models import Site

    return Site(
        id=NITRATES_SITE_ID,
        domain=settings.ENVERGO_NITRATES_DOMAIN,
        name="Simulateur nitrates",
    )


def patch_site_manager():
    """Fait resoudre SiteManager.get_current() depuis les settings."""
    from django.contrib.sites.models import SiteManager

    if getattr(SiteManager, "_nitrates_patched", False):
        return

    def get_current(self, request=None):
        return build_site_from_settings()

    SiteManager.get_current = get_current
    SiteManager._nitrates_patched = True
