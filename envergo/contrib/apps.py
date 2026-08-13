from django.apps import AppConfig


class ContribConfig(AppConfig):
    name = "envergo.contrib"

    def ready(self):
        from envergo.contrib.sites_from_settings import patch_site_manager

        patch_site_manager()
