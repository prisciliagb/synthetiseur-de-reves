from django.db.models import QuerySet
from django.views.generic import DetailView, ListView

from .models import Dream


class UserDreamsMixin:
    """Limite les rêves accessibles à ceux de l'utilisateur connecté.

    Toute vue qui hérite de ce mixin ne peut lire que les rêves de
    l'utilisateur. Un rêve d'un autre utilisateur renvoie une erreur 404,
    comme s'il n'existait pas.
    """

    def get_queryset(self) -> QuerySet[Dream]:
        """Renvoie uniquement les rêves de l'utilisateur connecté."""
        return Dream.objects.filter(user=self.request.user)


class DreamListView(UserDreamsMixin, ListView):
    """Liste des rêves de l'utilisateur connecté."""

    model = Dream
    context_object_name = "dreams"


class DreamDetailView(UserDreamsMixin, DetailView):
    """Détail d'un rêve de l'utilisateur connecté."""

    model = Dream
    context_object_name = "dream"
