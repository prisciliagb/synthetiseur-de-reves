from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from django.http import HttpRequest, JsonResponse
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from .forms import AudioRecordingForm
from .models import Dream
from .services.analysis import AnalysisError, analyze_dream
from .services.image import ImageGenerationError, generate_dream_image
from .services.transcription import TranscriptionError, transcribe


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
    """Reçoit l'enregistrement audio, le transcrit, l'analyse et crée le rêve.

    L'audio n'est jamais enregistré : il est contrôlé (taille, format), envoyé
    à Groq Whisper, puis supprimé. Seule la transcription est conservée. Le
    texte est ensuite analysé par le LLM (émotion et prompt d'image), puis
    l'image est générée par Replicate et stockée sur Cloudinary.
    """

    http_method_names = ["post"]

    def post(self, request: HttpRequest) -> JsonResponse:
        """Transcrit l'enregistrement reçu et crée le rêve correspondant.

        Args:
            request: La requête contenant le fichier « audio ».

        Returns:
            Une réponse JSON :
            - 200 avec l'adresse du rêve créé si tout s'est bien passé ;
            - 400 si l'audio est invalide ;
            - 502 si la transcription a échoué.
        """
        form = AudioRecordingForm(files=request.FILES)
        if not form.is_valid():
            return JsonResponse(
                {"ok": False, "error": form.errors["audio"][0]}, status=400
            )

        audio = form.cleaned_data["audio"]
        try:
            transcription = transcribe(audio)
        except TranscriptionError as error:
            return JsonResponse({"ok": False, "error": error.user_message}, status=502)
        finally:
            # RGPD : l'audio est supprimé dès la fin de la transcription, qu'elle
            # ait réussi ou non. Fermer le fichier efface sa copie temporaire.
            audio.close()

        dream = Dream(
            user=request.user,
            transcription=transcription,
            status=Dream.Status.DONE,
        )
        try:
            analysis = analyze_dream(transcription)
        except AnalysisError:
            # L'analyse a échoué, mais la transcription est gardée : le rêve
            # est quand même enregistré, sans émotion.
            pass
        else:
            dream.emotion = analysis.emotion
            dream.confidence = analysis.confidence
            dream.image_prompt = analysis.image_prompt
            try:
                generate_dream_image(dream)
            except ImageGenerationError:
                # Pas d'image : la page du rêve affiche l'image de remplacement.
                pass
        dream.save()
        return JsonResponse(
            {"ok": True, "redirect_url": reverse("dreams:detail", args=[dream.pk])}
        )
