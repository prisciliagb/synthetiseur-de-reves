"""Transcription d'un enregistrement audio en texte avec Groq Whisper.

Tout l'échange avec l'API Groq est isolé ici : le reste de l'application
appelle seulement `transcribe()` et n'a pas à connaître les détails de l'API.
"""

import logging
import time

import httpx
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

logger = logging.getLogger(__name__)

GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Codes HTTP qui signalent un problème temporaire : on peut réessayer.
# 429 = trop de requêtes, 5xx = erreur ou surcharge du serveur de Groq.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

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
    retentés plusieurs fois, en attendant un peu plus longtemps à chaque fois.

    Args:
        audio: Le fichier audio à transcrire, déjà validé.

    Returns:
        Le texte du rêve.

    Raises:
        TranscriptionError: Si la transcription est impossible. Le message
            de l'erreur peut être affiché tel quel à l'utilisateur.
    """
    if not settings.GROQ_API_KEY:
        logger.error("GROQ_API_KEY n'est pas configurée : transcription impossible.")
        raise TranscriptionError(UNAVAILABLE_MESSAGE)

    max_attempts = settings.GROQ_MAX_ATTEMPTS
    for attempt in range(1, max_attempts + 1):
        try:
            response = _call_groq(audio)
        except httpx.TransportError as error:
            # Délai dépassé, connexion impossible… : problème temporaire.
            logger.warning(
                "Transcription, tentative %s/%s : %s",
                attempt,
                max_attempts,
                type(error).__name__,
            )
        else:
            if response.status_code == 200:
                return _extract_text(response)
            if response.status_code not in RETRYABLE_STATUS_CODES:
                # Erreur définitive (clé invalide, fichier refusé…) : inutile
                # de réessayer.
                logger.error(
                    "Transcription refusée par Groq (HTTP %s).", response.status_code
                )
                raise TranscriptionError(
                    "Votre enregistrement n'a pas pu être transcrit. "
                    "Essayez de le refaire."
                )
            logger.warning(
                "Transcription, tentative %s/%s : HTTP %s",
                attempt,
                max_attempts,
                response.status_code,
            )

        if attempt < max_attempts:
            # Attente de 1 s, puis 2 s, puis 4 s… avant de réessayer.
            time.sleep(2 ** (attempt - 1))

    logger.error("Transcription abandonnée après %s tentatives.", max_attempts)
    raise TranscriptionError(UNAVAILABLE_MESSAGE)


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
            "response_format": "json",
        },
        files={"file": (audio.name, audio.read(), audio.content_type)},
        timeout=settings.GROQ_TIMEOUT,
    )


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
