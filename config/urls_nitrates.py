from django.urls import include, path

from config.urls import handler500  # noqa
from config.urls import urlpatterns as common_urlpatterns

urlpatterns = [
    path("", include("envergo.nitrates.urls")),
] + common_urlpatterns
