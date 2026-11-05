"""Routes principales du projet."""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("comptes/", include("accounts.urls")),
    path("reves/", include("dreams.urls")),
    path("", RedirectView.as_view(pattern_name="dreams:list"), name="home"),
]
