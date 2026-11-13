"""Tableau de bord : analyse des rêves de l'utilisateur.

L'application `dreams` enregistre et traite les rêves ; `dashboard` les
analyse. Elle réutilise ce qui appartient à `dreams` : le modèle, le filtre
« mes rêves seulement » et le formulaire de filtres de l'historique.
"""

from typing import Any

from django.views.generic import TemplateView

from dreams.forms import DreamFilterForm
from dreams.views import UserDreamsMixin

from .services import compute_stats


class StatsView(UserDreamsMixin, TemplateView):
    """Tableau de bord : statistiques des rêves, avec les filtres de l'historique.

    Les graphiques sont dessinés par static/js/stats.js (Chart.js) à partir des
    données transmises dans la page.
    """

    template_name = "dashboard/stats.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Calcule les statistiques des rêves filtrés.

        Returns:
            Le contexte du template : filtres, statistiques et données des
            graphiques.
        """
        context = super().get_context_data(**kwargs)
        filter_form = DreamFilterForm(self.request.GET or None)
        stats = compute_stats(filter_form.filter(self.get_queryset()))
        context["filter_form"] = filter_form
        context["is_filtering"] = filter_form.is_filtering()
        context["stats"] = stats
        dominant_values = {emotion.value for emotion in stats.dominant}
        # Données lues par le JavaScript (balise json_script, sans risque XSS).
        context["chart_data"] = {
            "weeks": {
                "labels": [f"{monday:%d/%m}" for monday, _ in stats.weeks],
                "counts": [count for _, count in stats.weeks],
            },
            "emotions": {
                "labels": [e.label for e in stats.emotions],
                "counts": [e.count for e in stats.emotions],
                "dominant": [e.value in dominant_values for e in stats.emotions],
            },
        }
        return context
