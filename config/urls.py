"""Routes principales du projet."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("comptes/", include("accounts.urls")),
    path("reves/", include("dreams.urls")),
    path("", RedirectView.as_view(pattern_name="dreams:list"), name="home"),
]

# En développement, Django sert lui-même les images des rêves.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
