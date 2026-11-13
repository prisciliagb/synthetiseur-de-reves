"""Pages générales du site, qui n'appartiennent à aucune application."""

import logging
from typing import Any

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.db import DatabaseError, connection
from django.http import HttpRequest, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView

logger = logging.getLogger(__name__)


@method_decorator(login_not_required, name="dispatch")
class HomeView(TemplateView):
    """Page d'accueil : présente l'application, accessible sans être connecté."""

    template_name = "home.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Ajoute la durée maximale d'un enregistrement, citée dans les étapes.

        Returns:
            Le contexte du template.
        """
        context = super().get_context_data(**kwargs)
        context["max_minutes"] = settings.DREAM_AUDIO_MAX_SECONDS // 60
        return context


@method_decorator([login_not_required, never_cache], name="dispatch")
class HealthView(View):
    """État de l'application, pour un outil de surveillance (`/health`).

    Vérifie que la base de données répond, et indique quels services
    externes sont configurés. Les clés elles-mêmes ne sont jamais affichées.
    """

    http_method_names = ["get", "head"]

    def get(self, request: HttpRequest) -> JsonResponse:
        """Renvoie l'état de l'application.

        Args:
            request: La requête.

        Returns:
            Une réponse JSON : 200 si tout va bien, 503 si la base de
            données ne répond pas.
        """
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            database_ok = True
        except DatabaseError:
            logger.exception("Health : la base de données ne répond pas.")
            database_ok = False

        return JsonResponse(
            {
                "status": "ok" if database_ok else "error",
                "database": "ok" if database_ok else "error",
                # Vrai / faux seulement : la valeur des clés reste secrète.
                "services": {
                    "groq": bool(settings.GROQ_API_KEY),
                    "replicate": bool(settings.REPLICATE_API_TOKEN),
                    "cloudinary": bool(settings.CLOUDINARY_URL),
                },
            },
            status=200 if database_ok else 503,
        )
