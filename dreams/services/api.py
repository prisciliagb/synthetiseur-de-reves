"""Appel à une API externe avec délai maximal et nouvelles tentatives.

Groq (transcription, analyse) et Replicate (image) utilisent tous les deux ce
module : la gestion des échecs est écrite une seule fois, ici.
"""

import logging
import time
from collections.abc import Callable

import httpx

logger = logging.getLogger(__name__)

# Codes HTTP qui signalent un problème temporaire : on peut réessayer.
# 429 = trop de requêtes, 5xx = erreur ou surcharge du serveur.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ApiError(Exception):
    """L'appel à l'API externe a échoué."""


class ApiUnavailableError(ApiError):
    """L'API est indisponible : clé absente, ou échecs temporaires répétés."""


class ApiRefusedError(ApiError):
    """L'API a refusé la requête (clé invalide, contenu refusé…).

    Réessayer ne servirait à rien : la réponse serait la même.
    """


def call_api(
    send: Callable[[], httpx.Response],
    task: str,
    api_key: str,
    max_attempts: int,
) -> httpx.Response:
    """Appelle une API en réessayant en cas d'échec temporaire.

    Args:
        send: Fonction qui envoie la requête et renvoie la réponse. Elle est
            rappelée à chaque tentative.
        task: Nom de la tâche (« Transcription », « Image »…), pour les logs.
        api_key: Clé de l'API ; si elle est vide, l'API n'est pas appelée.
        max_attempts: Nombre total de tentatives.

    Returns:
        La réponse HTTP de l'API, avec un code de succès (2xx).

    Raises:
        ApiUnavailableError: Si la clé manque ou si toutes les tentatives
            ont échoué.
        ApiRefusedError: Si l'API a refusé définitivement la requête.
    """
    if not api_key:
        logger.error("%s : la clé d'API n'est pas configurée.", task)
        raise ApiUnavailableError

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
            if response.is_success:
                return response
            if response.status_code not in RETRYABLE_STATUS_CODES:
                # Erreur définitive : inutile de réessayer.
                logger.error("%s refusée (HTTP %s).", task, response.status_code)
                raise ApiRefusedError
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
    raise ApiUnavailableError
