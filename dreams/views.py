from typing import Any

from django.conf import settings
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import QuerySet
from django.http import HttpRequest, JsonResponse
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import DeleteView, DetailView, ListView, TemplateView
from django.views.generic.detail import SingleObjectMixin

from .forms import AudioRecordingForm, DreamFilterForm
from .models import Dream
from .services.pipeline import ANALYSIS, IMAGE, StepError, progress, run_step
from .services.stats import compute_stats
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
    """Historique des rêves de l'utilisateur connecté, du plus récent au plus ancien.

    L'ordre vient de `Dream.Meta.ordering`. La liste est découpée en pages de
    10 rêves ; une page qui n'existe pas renvoie une erreur 404.
    """

    model = Dream
    context_object_name = "dreams"
    paginate_by = 10

    def get_queryset(self) -> QuerySet[Dream]:
        """Renvoie les rêves de l'utilisateur, filtrés selon le formulaire.

        Returns:
            Les rêves qui correspondent aux filtres de l'adresse (?start=…).
        """
        # Sans paramètre dans l'adresse, le formulaire est vide : pas d'erreur.
        self.filter_form = DreamFilterForm(self.request.GET or None)
        return self.filter_form.filter(super().get_queryset())

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Ajoute le formulaire de filtres au contexte.

        Returns:
            Le contexte du template, avec les filtres.
        """
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        context["is_filtering"] = self.filter_form.is_filtering()
        return context


class DreamStatsView(UserDreamsMixin, TemplateView):
    """Statistiques des rêves de l'utilisateur, avec les filtres de l'historique.

    Les graphiques sont dessinés par static/js/stats.js (Chart.js) à partir des
    données transmises dans la page.
    """

    template_name = "dreams/stats.html"

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


class DreamDetailView(UserDreamsMixin, DetailView):
    """Détail d'un rêve de l'utilisateur connecté."""

    model = Dream
    context_object_name = "dream"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Ajoute l'avancement, pour relancer les étapes manquantes.

        Returns:
            Le contexte du template, avec l'avancement du traitement.
        """
        context = super().get_context_data(**kwargs)
        context["progress"] = progress(self.object)
        return context


class DreamDeleteView(UserDreamsMixin, SuccessMessageMixin, DeleteView):
    """Suppression d'un rêve, après confirmation.

    - GET affiche la page de confirmation ;
    - POST supprime le rêve, puis renvoie vers l'historique.

    Un simple lien ne peut donc pas supprimer un rêve par accident. L'image
    est supprimée du stockage par le signal `delete_dream_image` (RGPD).
    Grâce à UserDreamsMixin, le rêve d'un autre utilisateur renvoie une 404.
    """

    model = Dream
    context_object_name = "dream"
    success_url = reverse_lazy("dreams:list")
    success_message = "Votre rêve a bien été supprimé."


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
    """Étape 1 : reçoit l'audio, le transcrit et crée le rêve.

    L'audio n'est jamais enregistré : il est contrôlé (taille, format), envoyé
    à Groq Whisper, puis supprimé. Seule la transcription est conservée. Le
    JavaScript lance ensuite les étapes suivantes (analyse, image).
    """

    http_method_names = ["post"]

    def post(self, request: HttpRequest) -> JsonResponse:
        """Transcrit l'enregistrement reçu et crée le rêve correspondant.

        Args:
            request: La requête contenant le fichier « audio » et le
                consentement (« consent »).

        Returns:
            Une réponse JSON :
            - 200 avec la prochaine étape si la transcription a réussi ;
            - 400 si le consentement manque ou si l'audio est invalide ;
            - 502 si la transcription a échoué.
        """
        form = AudioRecordingForm(data=request.POST, files=request.FILES)
        if not form.is_valid():
            # Le premier problème trouvé : consentement manquant, puis audio.
            first_error = next(iter(form.errors.values()))[0]
            return JsonResponse({"ok": False, "error": first_error}, status=400)

        audio = form.cleaned_data["audio"]
        try:
            transcription = transcribe(audio)
        except TranscriptionError as error:
            return JsonResponse({"ok": False, "error": error.user_message}, status=502)
        finally:
            # RGPD : l'audio est supprimé dès la fin de la transcription, qu'elle
            # ait réussi ou non. Fermer le fichier efface sa copie temporaire.
            audio.close()

        # Le texte est enregistré tout de suite : il est conservé même si une
        # étape suivante échoue.
        dream = Dream.objects.create(
            user=request.user,
            transcription=transcription,
            status=Dream.Status.PROCESSING,
        )
        return JsonResponse({"ok": True, **progress(dream)})


class DreamStepView(UserDreamsMixin, SingleObjectMixin, View):
    """Exécute une étape du traitement d'un rêve (analyse ou image).

    Grâce à UserDreamsMixin, on ne peut lancer une étape que sur ses propres
    rêves : le rêve d'un autre utilisateur renvoie une erreur 404.
    """

    http_method_names = ["post"]
    model = Dream
    step = ""

    def post(self, request: HttpRequest, pk: int) -> JsonResponse:
        """Exécute l'étape, puis indique la suivante.

        Si cette étape n'est pas la prochaine à faire (déjà faite, ou une
        étape précédente manque), rien n'est exécuté : la réponse indique
        simplement l'étape à lancer.

        Args:
            request: La requête.
            pk: L'identifiant du rêve.

        Returns:
            Une réponse JSON : 200 avec la prochaine étape, ou 502 avec un
            message si l'étape a échoué.
        """
        dream = self.get_object()
        if progress(dream)["next_step"] == self.step:
            try:
                run_step(dream, self.step)
            except StepError as error:
                return JsonResponse(
                    {"ok": False, "error": error.user_message, **progress(dream)},
                    status=502,
                )
        return JsonResponse({"ok": True, **progress(dream)})


class DreamAnalysisView(DreamStepView):
    """Étape 2 : détecte l'émotion du rêve et écrit le prompt de son image."""

    step = ANALYSIS


class DreamImageView(DreamStepView):
    """Étape 3 : génère l'image du rêve et la stocke sur Cloudinary."""

    step = IMAGE
