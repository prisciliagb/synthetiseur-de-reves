"""Pages générales du site, qui n'appartiennent à aucune application."""

from typing import Any

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView


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
