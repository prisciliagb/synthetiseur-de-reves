"""Tests de la transcription : le service Groq Whisper et son branchement.

Groq n'est jamais appelé pour de vrai : `httpx.post` est remplacé par un
faux (« mock ») qui renvoie la réponse voulue. Les tests sont donc gratuits,
rapides et fonctionnent sans clé d'API ni connexion Internet.
"""

import os
from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .models import Dream
from .services.transcription import (
    GROQ_TRANSCRIPTION_URL,
    TranscriptionError,
    transcribe,
)

WEBM_HEADER = b"\x1a\x45\xdf\xa3"


def fake_audio() -> SimpleUploadedFile:
    """Crée un faux enregistrement WebM."""
    return SimpleUploadedFile(
        "reve.webm", WEBM_HEADER + b"\x00" * 100, content_type="audio/webm"
    )


def groq_response(status_code: int, json: object = None) -> httpx.Response:
    """Fabrique une fausse réponse de l'API Groq.

    Args:
        status_code: Code HTTP de la réponse.
        json: Contenu JSON de la réponse.

    Returns:
        La réponse HTTP simulée.
    """
    request = httpx.Request("POST", GROQ_TRANSCRIPTION_URL)
    return httpx.Response(status_code, json=json, request=request)


@override_settings(GROQ_API_KEY="cle-de-test", GROQ_MAX_ATTEMPTS=3)
@patch("dreams.services.api.time.sleep")
@patch("dreams.services.transcription.httpx.post")
class TranscribeServiceTests(SimpleTestCase):
    """Tests du service `transcribe()`."""

    def test_returns_transcribed_text(self, post, sleep) -> None:
        """Le texte renvoyé par Groq est retourné, sans espaces superflus."""
        post.return_value = groq_response(200, {"text": "  Je volais.  "})

        self.assertEqual(transcribe(fake_audio()), "Je volais.")

    def test_sends_audio_in_french_with_api_key_and_timeout(self, post, sleep) -> None:
        """L'appel envoie l'audio, la langue, la clé et un délai maximal."""
        post.return_value = groq_response(200, {"text": "Je volais."})

        transcribe(fake_audio())

        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer cle-de-test")
        self.assertEqual(kwargs["data"]["language"], "fr")
        self.assertEqual(kwargs["files"]["file"][0], "reve.webm")
        self.assertIn("timeout", kwargs)

    def test_retries_after_timeout_then_succeeds(self, post, sleep) -> None:
        """Après un délai dépassé, une nouvelle tentative est faite."""
        post.side_effect = [
            httpx.ReadTimeout("trop long"),
            groq_response(200, {"text": "Je volais."}),
        ]

        self.assertEqual(transcribe(fake_audio()), "Je volais.")
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_retries_when_groq_is_overloaded(self, post, sleep) -> None:
        """Les erreurs 429 et 503 (temporaires) sont retentées."""
        post.side_effect = [
            groq_response(429),
            groq_response(503),
            groq_response(200, {"text": "Je volais."}),
        ]

        self.assertEqual(transcribe(fake_audio()), "Je volais.")
        self.assertEqual(post.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2])

    def test_gives_up_after_max_attempts(self, post, sleep) -> None:
        """Après 3 échecs temporaires, une erreur compréhensible est levée."""
        post.side_effect = httpx.ConnectError("injoignable")

        with self.assertRaises(TranscriptionError) as context:
            transcribe(fake_audio())

        self.assertEqual(post.call_count, 3)
        self.assertIn("momentanément indisponible", context.exception.user_message)

    def test_does_not_retry_definitive_errors(self, post, sleep) -> None:
        """Une erreur définitive (clé invalide…) n'est pas retentée."""
        post.return_value = groq_response(401, {"error": "invalid api key"})

        with self.assertRaises(TranscriptionError):
            transcribe(fake_audio())

        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()

    def test_silence_gives_a_clear_message(self, post, sleep) -> None:
        """Si aucune parole n'est reconnue, le message l'explique."""
        post.return_value = groq_response(200, {"text": "   "})

        with self.assertRaises(TranscriptionError) as context:
            transcribe(fake_audio())

        self.assertIn("Aucune parole", context.exception.user_message)

    def test_unreadable_response_is_an_error(self, post, sleep) -> None:
        """Une réponse sans texte est traitée comme une erreur."""
        post.return_value = groq_response(200, {"inattendu": True})

        with self.assertRaises(TranscriptionError):
            transcribe(fake_audio())

    @override_settings(GROQ_API_KEY="")
    def test_missing_api_key_never_calls_groq(self, post, sleep) -> None:
        """Sans clé configurée, Groq n'est pas appelé."""
        with self.assertRaises(TranscriptionError):
            transcribe(fake_audio())

        post.assert_not_called()


class TranscriptionViewTests(TestCase):
    """Tests du branchement de la transcription dans l'envoi de l'audio."""

    def setUp(self) -> None:
        """Connecte un utilisateur de test."""
        self.user = get_user_model().objects.create_user("alice", "alice@example.com")
        self.client.force_login(self.user)
        self.url = reverse("dreams:upload_audio")

    @patch("dreams.views.transcribe", return_value="Je volais au-dessus de la mer.")
    def test_success_creates_dream_and_redirects_to_it(self, transcribe) -> None:
        """Une transcription réussie crée le rêve et renvoie son adresse."""
        response = self.client.post(self.url, {"audio": fake_audio()})

        dream = Dream.objects.get()
        self.assertEqual(dream.user, self.user)
        self.assertEqual(dream.transcription, "Je volais au-dessus de la mer.")
        self.assertEqual(
            response.json()["redirect_url"], reverse("dreams:detail", args=[dream.pk])
        )

    @patch(
        "dreams.views.transcribe",
        side_effect=TranscriptionError("Service momentanément indisponible."),
    )
    def test_failure_returns_message_and_creates_nothing(self, transcribe) -> None:
        """Un échec renvoie un message compréhensible et ne crée aucun rêve."""
        response = self.client.post(self.url, {"audio": fake_audio()})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()["error"], "Service momentanément indisponible."
        )
        self.assertFalse(Dream.objects.exists())

    @override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=0)
    def test_temporary_audio_file_is_deleted_after_transcription(self) -> None:
        """RGPD : la copie temporaire de l'audio est effacée, même en cas d'échec."""
        seen_paths = []

        def fake_transcribe(audio) -> str:
            # FILE_UPLOAD_MAX_MEMORY_SIZE=0 force Django à écrire l'audio dans
            # un fichier temporaire : on note son chemin pour vérifier après.
            seen_paths.append(audio.temporary_file_path())
            raise TranscriptionError("Échec simulé.")

        with patch("dreams.views.transcribe", side_effect=fake_transcribe):
            self.client.post(self.url, {"audio": fake_audio()})

        self.assertEqual(len(seen_paths), 1)
        self.assertFalse(os.path.exists(seen_paths[0]))
