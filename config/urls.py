"""Routes principales du projet."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from .views import HealthView, HomeView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("comptes/", include("accounts.urls")),
    path("reves/", include("dreams.urls")),
    path("tableau-de-bord/", include("dashboard.urls")),
    path("", HomeView.as_view(), name="home"),
    # État de l'application, pour la surveillance (issue #21).
    path("health", HealthView.as_view(), name="health"),
]

# En développement, Django sert lui-même les images des rêves.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
