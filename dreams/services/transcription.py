"""Transcription d'un enregistrement audio en texte avec Groq Whisper.

Tout l'échange avec l'API Groq est isolé ici : le reste de l'application
appelle seulement `transcribe()` et n'a pas à connaître les détails de l'API.
"""

import logging
from decimal import Decimal

import httpx
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

from .api import ApiRefusedError, ApiUnavailableError, call_api

logger = logging.getLogger(__name__)

GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

UNAVAILABLE_MESSAGE = (
    "Le service de transcription est momentanément indisponible. "
    "Réessayez dans quelques minutes."
)


class TranscriptionError(Exception):
    """La transcription a échoué.

    Attributes:
        user_message: Message compréhensible à afficher à l'utilisateur.
    """

    def __init__(self, user_message: str) -> None:
        """Crée l'erreur avec le message destiné à l'utilisateur.

        Args:
            user_message: Message compréhensible à afficher à l'utilisateur.
        """
        super().__init__(user_message)
        self.user_message = user_message


def transcribe(audio: UploadedFile) -> str:
    """Transcrit un enregistrement audio en texte français.

    Les échecs temporaires (délai dépassé, réseau, serveur surchargé) sont
    retentés plusieurs fois par `call_api()`.

    Args:
        audio: Le fichier audio à transcrire, déjà validé.

    Returns:
        Le texte du rêve.

    Raises:
        TranscriptionError: Si la transcription est impossible. Le message
            de l'erreur peut être affiché tel quel à l'utilisateur.
    """
    try:
        response = call_api(
            lambda: _call_groq(audio),
            task="Transcription",
            api_key=settings.GROQ_API_KEY,
            max_attempts=settings.GROQ_MAX_ATTEMPTS,
            service="Groq",
            cost=transcription_cost,
        )
    except ApiRefusedError:
        raise TranscriptionError(
            "Votre enregistrement n'a pas pu être transcrit. Essayez de le refaire."
        ) from None
    except ApiUnavailableError:
        raise TranscriptionError(UNAVAILABLE_MESSAGE) from None
    return _extract_text(response)


def _call_groq(audio: UploadedFile) -> httpx.Response:
    """Envoie l'audio à l'API de transcription de Groq.

    Args:
        audio: Le fichier audio à transcrire.

    Returns:
        La réponse HTTP de Groq.

    Raises:
        httpx.TransportError: Si Groq ne répond pas à temps ou est injoignable.
    """
    audio.seek(0)
    return httpx.post(
        GROQ_TRANSCRIPTION_URL,
        headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
        data={
            "model": settings.GROQ_WHISPER_MODEL,
            "language": "fr",
            # « verbose_json » donne aussi la durée de l'audio, pour le coût.
            "response_format": "verbose_json",
        },
        files={"file": (audio.name, audio.read(), audio.content_type)},
        timeout=settings.GROQ_TIMEOUT,
    )


def transcription_cost(response: httpx.Response) -> Decimal:
    """Estime le coût d'une transcription d'après la durée de l'audio.

    Groq facture Whisper à l'heure d'audio, avec un minimum de 10 secondes.

    Args:
        response: La réponse de Groq, qui contient la durée (« duration »).

    Returns:
        Le coût estimé, en dollars.
    """
    seconds = Decimal(str(response.json()["duration"]))
    billed = max(seconds, Decimal(settings.GROQ_WHISPER_MIN_BILLED_SECONDS))
    return billed / 3600 * settings.GROQ_WHISPER_PRICE_PER_HOUR


def _extract_text(response: httpx.Response) -> str:
    """Récupère le texte de la réponse de Groq.

    Args:
        response: Réponse HTTP 200 de Groq.

    Returns:
        Le texte transcrit, sans espaces superflus.

    Raises:
        TranscriptionError: Si la réponse est illisible ou si aucune parole
            n'a été reconnue.
    """
    try:
        text = response.json()["text"].strip()
    except (ValueError, KeyError, TypeError, AttributeError):
        logger.error("Réponse de Groq illisible.")
        raise TranscriptionError(UNAVAILABLE_MESSAGE) from None
    if not text:
        raise TranscriptionError(
            "Aucune parole n'a été reconnue dans l'enregistrement. "
            "Parlez plus près du micro et réessayez."
        )
    return text
