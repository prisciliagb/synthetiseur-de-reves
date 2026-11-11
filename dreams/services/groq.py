"""Appel à l'API Groq avec délai maximal et nouvelles tentatives.

La transcription (Whisper) et l'analyse (LLM) utilisent toutes les deux Groq :
la gestion des échecs est écrite une seule fois, ici.
"""

import logging
import time
from collections.abc import Callable

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

# Codes HTTP qui signalent un problème temporaire : on peut réessayer.
# 429 = trop de requêtes, 5xx = erreur ou surcharge du serveur de Groq.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class GroqError(Exception):
    """L'appel à Groq a échoué."""


class GroqUnavailableError(GroqError):
    """Groq est indisponible : clé absente, ou échecs temporaires répétés."""


class GroqRefusedError(GroqError):
    """Groq a refusé la requête (clé invalide, contenu refusé…).

    Réessayer ne servirait à rien : la réponse serait la même.
    """


def call_groq(send: Callable[[], httpx.Response], task: str) -> httpx.Response:
    """Appelle Groq en réessayant en cas d'échec temporaire.

    Args:
        send: Fonction qui envoie la requête et renvoie la réponse. Elle est
            rappelée à chaque tentative.
        task: Nom de la tâche (« Transcription », « Analyse »), pour les logs.

    Returns:
        La réponse HTTP 200 de Groq.

    Raises:
        GroqUnavailableError: Si la clé manque ou si toutes les tentatives
            ont échoué.
        GroqRefusedError: Si Groq a refusé définitivement la requête.
    """
    if not settings.GROQ_API_KEY:
        logger.error("%s : GROQ_API_KEY n'est pas configurée.", task)
        raise GroqUnavailableError

    max_attempts = settings.GROQ_MAX_ATTEMPTS
    for attempt in range(1, max_attempts + 1):
        try:
            response = send()
        except httpx.TransportError as error:
            # Délai dépassé, connexion impossible… : problème temporaire.
            logger.warning(
                "%s, tentative %s/%s : %s",
                task,
                attempt,
                max_attempts,
                type(error).__name__,
            )
        else:
            if response.status_code == 200:
                return response
            if response.status_code not in RETRYABLE_STATUS_CODES:
                # Erreur définitive : inutile de réessayer.
                logger.error(
                    "%s refusée par Groq (HTTP %s).", task, response.status_code
                )
                raise GroqRefusedError
            logger.warning(
                "%s, tentative %s/%s : HTTP %s",
                task,
                attempt,
                max_attempts,
                response.status_code,
            )

        if attempt < max_attempts:
            # Attente de 1 s, puis 2 s, puis 4 s… avant de réessayer.
            time.sleep(2 ** (attempt - 1))

    logger.error("%s abandonnée après %s tentatives.", task, max_attempts)
    raise GroqUnavailableError
