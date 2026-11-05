from django.views.generic import TemplateView


class DreamListView(TemplateView):
    """Liste des rêves de l'utilisateur connecté.

    Page provisoire : elle sera complétée avec le modèle Dream. Elle est
    protégée par LoginRequiredMiddleware, comme toutes les pages par défaut.
    """

    template_name = "dreams/dream_list.html"
