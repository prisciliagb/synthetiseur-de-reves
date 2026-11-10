from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from django.http import HttpRequest, JsonResponse
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from .forms import AudioRecordingForm
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


class RecordDreamView(TemplateView):
    """Page pour raconter un rêve au micro."""

    template_name = "dreams/record.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Transmet au JavaScript les limites de l'enregistrement.

        Returns:
            Le contexte du template, avec la durée et la taille maximales.
        """
        context = super().get_context_data(**kwargs)
        context["max_seconds"] = settings.DREAM_AUDIO_MAX_SECONDS
        context["max_size"] = settings.DREAM_AUDIO_MAX_SIZE
        return context


class AudioUploadView(View):
    """Reçoit l'enregistrement audio envoyé par le navigateur.

    L'audio est contrôlé (taille, format) puis jamais enregistré sur le disque :
    Django le supprime automatiquement à la fin de la requête. La transcription
    sera branchée ici dans une prochaine issue.
    """

    http_method_names = ["post"]

    def post(self, request: HttpRequest) -> JsonResponse:
        """Valide l'enregistrement reçu.

        Args:
            request: La requête contenant le fichier « audio ».

        Returns:
            Une réponse JSON : 200 si l'audio est valide, 400 sinon.
        """
        form = AudioRecordingForm(files=request.FILES)
        if not form.is_valid():
            return JsonResponse(
                {"ok": False, "error": form.errors["audio"][0]}, status=400
            )
        return JsonResponse(
            {
                "ok": True,
                "message": "Votre rêve a bien été reçu. "
                "La transcription sera bientôt disponible.",
            }
        )
