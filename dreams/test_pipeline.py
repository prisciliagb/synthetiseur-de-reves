"""Tests de l'enchaînement des étapes : texte → émotion → image.

L'analyse et l'image sont simulées (« mocks ») : aucune API n'est appelée.
"""

import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Dream
from .services.analysis import AnalysisError, DreamAnalysis
from .services.image import ImageGenerationError
from .services.pipeline import ANALYSIS, IMAGE, next_step

User = get_user_model()

ANALYSIS_RESULT = DreamAnalysis("strange", 0.8, "A house floating above the sea.")


def fake_generate(dream: Dream) -> None:
    """Remplace la génération d'image : attache une fausse image au rêve."""
    dream.image.save("abc.webp", ContentFile(b"fausse image"), save=False)


class PipelineTestCase(TestCase):
    """Base des tests : un utilisateur connecté et un dossier media temporaire."""

    def setUp(self) -> None:
        """Connecte un utilisateur et isole les fichiers de test."""
        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)
        settings_override = override_settings(MEDIA_ROOT=media_root)
        settings_override.enable()
        self.addCleanup(settings_override.disable)

        self.user = User.objects.create_user("alice", "alice@example.com")
        self.client.force_login(self.user)

    def make_dream(self, **fields: object) -> Dream:
        """Crée un rêve transcrit, en cours de traitement."""
        fields.setdefault("transcription", "Je volais au-dessus de la mer.")
        fields.setdefault("status", Dream.Status.PROCESSING)
        return Dream.objects.create(user=self.user, **fields)

    def run_step(self, dream: Dream, step: str):
        """Lance une étape sur un rêve, comme le fait le JavaScript."""
        return self.client.post(reverse(f"dreams:{step}", args=[dream.pk]))


class NextStepTests(PipelineTestCase):
    """La prochaine étape se déduit de ce qui est déjà enregistré."""

    def test_order_is_analysis_then_image(self) -> None:
        """Après le texte vient l'analyse, puis l'image, puis plus rien."""
        dream = self.make_dream()
        self.assertEqual(next_step(dream), ANALYSIS)

        dream.emotion = Dream.Emotion.HAPPY
        self.assertEqual(next_step(dream), IMAGE)

        fake_generate(dream)
        self.assertIsNone(next_step(dream))


class UploadStartsPipelineTests(PipelineTestCase):
    """Étape 1 : l'envoi de l'audio crée le rêve et annonce l'étape suivante."""

    @patch("dreams.views.transcribe", return_value="Je volais.")
    def test_upload_saves_text_and_points_to_analysis(self, transcribe) -> None:
        """Le texte est enregistré tout de suite, avec le statut « en cours »."""
        audio = SimpleUploadedFile(
            "reve.webm", b"\x1a\x45\xdf\xa3" + b"\x00" * 100, content_type="audio/webm"
        )

        data = self.client.post(
            reverse("dreams:upload_audio"), {"consent": "on", "audio": audio}
        ).json()

        dream = Dream.objects.get()
        self.assertEqual(dream.transcription, "Je volais.")
        self.assertEqual(dream.status, Dream.Status.PROCESSING)
        self.assertEqual(data["next_step"], ANALYSIS)
        self.assertEqual(data["next_url"], reverse("dreams:analysis", args=[dream.pk]))


@patch("dreams.services.pipeline.generate_dream_image", side_effect=fake_generate)
@patch("dreams.services.pipeline.analyze_dream", return_value=ANALYSIS_RESULT)
class FullPipelineTests(PipelineTestCase):
    """Étapes 2 et 3 : tout s'enchaîne jusqu'au rêve complet."""

    def test_analysis_saves_emotion_and_prompt(self, analyze, generate) -> None:
        """L'analyse enregistre l'émotion et le prompt, puis annonce l'image."""
        dream = self.make_dream()

        data = self.run_step(dream, ANALYSIS).json()

        dream.refresh_from_db()
        self.assertEqual(dream.emotion, Dream.Emotion.STRANGE)
        self.assertEqual(dream.image_prompt, "A house floating above the sea.")
        self.assertEqual(dream.status, Dream.Status.PROCESSING)
        self.assertEqual(data["next_url"], reverse("dreams:image", args=[dream.pk]))

    def test_image_completes_the_dream(self, analyze, generate) -> None:
        """L'image termine le rêve : statut « Terminé », plus d'étape."""
        dream = self.make_dream()
        self.run_step(dream, ANALYSIS)

        data = self.run_step(dream, IMAGE).json()

        dream.refresh_from_db()
        self.assertTrue(dream.image)
        self.assertEqual(dream.status, Dream.Status.DONE)
        self.assertIsNone(data["next_url"])
        self.assertEqual(
            data["redirect_url"], reverse("dreams:detail", args=[dream.pk])
        )

    def test_step_already_done_is_not_run_again(self, analyze, generate) -> None:
        """Relancer une étape déjà faite ne refait rien (pas d'appel payant)."""
        dream = self.make_dream(emotion=Dream.Emotion.HAPPY)

        data = self.run_step(dream, ANALYSIS).json()

        analyze.assert_not_called()
        self.assertEqual(data["next_step"], IMAGE)

    def test_image_needs_analysis_first(self, analyze, generate) -> None:
        """L'image ne peut pas être lancée avant l'analyse."""
        dream = self.make_dream()

        data = self.run_step(dream, IMAGE).json()

        generate.assert_not_called()
        self.assertEqual(data["next_step"], ANALYSIS)


class StepFailureTests(PipelineTestCase):
    """Si une étape échoue, les résultats déjà obtenus sont conservés."""

    @patch("dreams.services.pipeline.analyze_dream", side_effect=AnalysisError)
    def test_analysis_failure_keeps_text(self, analyze) -> None:
        """Échec de l'analyse : le texte reste, le rêve passe en « Échec »."""
        dream = self.make_dream()

        response = self.run_step(dream, ANALYSIS)

        dream.refresh_from_db()
        self.assertEqual(response.status_code, 502)
        self.assertIn("analyse", response.json()["error"])
        self.assertEqual(dream.transcription, "Je volais au-dessus de la mer.")
        self.assertEqual(dream.status, Dream.Status.FAILED)

    @patch(
        "dreams.services.pipeline.generate_dream_image",
        side_effect=ImageGenerationError,
    )
    def test_image_failure_keeps_text_and_emotion(self, generate) -> None:
        """Échec de l'image : le texte et l'émotion restent."""
        dream = self.make_dream(emotion=Dream.Emotion.SAD, image_prompt="Rain.")

        response = self.run_step(dream, IMAGE)

        dream.refresh_from_db()
        self.assertEqual(response.status_code, 502)
        self.assertIn("image", response.json()["error"])
        self.assertEqual(dream.emotion, Dream.Emotion.SAD)
        self.assertEqual(dream.status, Dream.Status.FAILED)
        # La réponse indique quand même où voir le rêve et quoi relancer.
        self.assertEqual(response.json()["next_step"], IMAGE)

    @patch("dreams.services.pipeline.generate_dream_image", side_effect=fake_generate)
    def test_failed_step_can_be_relaunched(self, generate) -> None:
        """Une étape échouée peut être relancée et terminer le rêve."""
        dream = self.make_dream(
            emotion=Dream.Emotion.SAD, image_prompt="Rain.", status=Dream.Status.FAILED
        )

        self.run_step(dream, IMAGE)

        dream.refresh_from_db()
        self.assertEqual(dream.status, Dream.Status.DONE)


class StepSecurityTests(PipelineTestCase):
    """On ne peut lancer une étape que sur ses propres rêves."""

    @patch("dreams.services.pipeline.analyze_dream", return_value=ANALYSIS_RESULT)
    def test_other_users_dream_is_not_found(self, analyze) -> None:
        """Le rêve d'un autre utilisateur renvoie 404, sans rien exécuter."""
        bob = User.objects.create_user("bob", "bob@example.com")
        dream = Dream.objects.create(user=bob, transcription="Rêve de Bob.")

        response = self.run_step(dream, ANALYSIS)

        self.assertEqual(response.status_code, 404)
        analyze.assert_not_called()

    def test_get_is_not_allowed(self) -> None:
        """Les étapes n'acceptent que les requêtes POST."""
        dream = self.make_dream()

        response = self.client.get(reverse("dreams:analysis", args=[dream.pk]))

        self.assertEqual(response.status_code, 405)

    def test_anonymous_user_is_redirected(self) -> None:
        """Un visiteur non connecté est renvoyé vers la connexion."""
        dream = self.make_dream()
        self.client.logout()

        response = self.run_step(dream, ANALYSIS)

        self.assertEqual(response.status_code, 302)


class DreamPageTests(PipelineTestCase):
    """La page du rêve montre les résultats et permet de relancer."""

    def test_incomplete_dream_offers_to_relaunch(self) -> None:
        """Un rêve en échec propose de relancer les étapes manquantes."""
        dream = self.make_dream(
            emotion=Dream.Emotion.SAD, status=Dream.Status.FAILED, image_prompt="Rain."
        )

        response = self.client.get(reverse("dreams:detail", args=[dream.pk]))

        self.assertContains(response, "Relancer les étapes manquantes")
        self.assertContains(response, "Les résultats déjà obtenus sont conservés")
        self.assertContains(response, reverse("dreams:image", args=[dream.pk]))
        self.assertContains(response, "Triste")

    def test_complete_dream_has_no_relaunch_button(self) -> None:
        """Un rêve complet n'affiche pas le bouton « Relancer »."""
        dream = self.make_dream(emotion=Dream.Emotion.HAPPY, status=Dream.Status.DONE)
        fake_generate(dream)
        dream.save()

        response = self.client.get(reverse("dreams:detail", args=[dream.pk]))

        self.assertNotContains(response, "Relancer les étapes manquantes")

    def test_record_page_has_progress_indicator(self) -> None:
        """La page d'enregistrement contient l'indicateur des 3 étapes."""
        response = self.client.get(reverse("dreams:record"))

        self.assertContains(response, 'id="pipeline-progress"')
        for step in ("transcription", "analysis", "image"):
            self.assertContains(response, f'data-step="{step}"')
        self.assertContains(response, "js/pipeline.js")
