"""Appel à une API externe avec délai maximal et nouvelles tentatives.

Groq (transcription, analyse) et Replicate (image) utilisent tous les deux ce
module : la gestion des échecs est écrite une seule fois, ici.

Chaque appel est aussi tracé (issue #21) : une ligne de log structurée (JSON)
et un enregistrement `ApiCall`, avec la durée, le résultat et le coût estimé.
Le total des coûts est consultable dans l'admin.
"""

import json
import logging
import time
from collections.abc import Callable
from decimal import Decimal, InvalidOperation

import httpx
from django.db import DatabaseError

from ..models import ApiCall

logger = logging.getLogger(__name__)

# Calcule le coût estimé d'un appel réussi à partir de la réponse de l'API.
CostFunction = Callable[[httpx.Response], Decimal]

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
    service: str,
    cost: CostFunction | None = None,
) -> httpx.Response:
    """Appelle une API en réessayant en cas d'échec temporaire, et trace l'appel.

    Args:
        send: Fonction qui envoie la requête et renvoie la réponse. Elle est
            rappelée à chaque tentative.
        task: Nom de la tâche (« Transcription », « Image »…), pour les logs.
        api_key: Clé de l'API ; si elle est vide, l'API n'est pas appelée.
        max_attempts: Nombre total de tentatives.
        service: Fournisseur appelé (« Groq », « Replicate »).
        cost: Fonction qui estime le coût d'un appel réussi. Sans elle (ou
            si l'appel échoue), le coût est compté à 0.

    Returns:
        La réponse HTTP de l'API, avec un code de succès (2xx).

    Raises:
        ApiUnavailableError: Si la clé manque ou si toutes les tentatives
            ont échoué.
        ApiRefusedError: Si l'API a refusé définitivement la requête.
    """
    started = time.monotonic()
    trace = {"service": service, "task": task, "attempts": 0, "http_status": None}

    if not api_key:
        logger.error("%s : la clé d'API n'est pas configurée.", task)
        _record(trace, started, success=False)
        raise ApiUnavailableError

    for attempt in range(1, max_attempts + 1):
        trace["attempts"] = attempt
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
            trace["http_status"] = response.status_code
            if response.is_success:
                _record(trace, started, success=True, cost=_estimate(cost, response))
                return response
            if response.status_code not in RETRYABLE_STATUS_CODES:
                # Erreur définitive : inutile de réessayer.
                logger.error("%s refusée (HTTP %s).", task, response.status_code)
                _record(trace, started, success=False)
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
    _record(trace, started, success=False)
    raise ApiUnavailableError


def _estimate(cost: CostFunction | None, response: httpx.Response) -> Decimal:
    """Estime le coût d'un appel réussi, sans jamais faire échouer l'appel.

    Args:
        cost: La fonction de calcul du coût, ou None si l'appel est gratuit.
        response: La réponse de l'API.

    Returns:
        Le coût estimé en dollars (0 si on ne peut pas le calculer).
    """
    if cost is None:
        return Decimal(0)
    try:
        return cost(response)
    except (ValueError, KeyError, TypeError, AttributeError, InvalidOperation):
        # Réponse inattendue : le rêve compte plus que l'estimation du coût.
        logger.warning("Coût de l'appel impossible à estimer.")
        return Decimal(0)


def _record(
    trace: dict[str, object],
    started: float,
    success: bool,
    cost: Decimal = Decimal(0),
) -> None:
    """Écrit la ligne de log structurée et enregistre l'appel en base.

    Args:
        trace: Service, tâche, nombre de tentatives et dernier code HTTP.
        started: Moment du début de l'appel (time.monotonic()).
        success: Vrai si l'API a répondu avec succès.
        cost: Coût estimé de l'appel, en dollars.
    """
    duration_ms = round((time.monotonic() - started) * 1000)
    cost = cost.quantize(Decimal("0.000001"))
    # Une ligne JSON par appel : facile à lire et à filtrer dans les logs.
    entry = {
        **trace,
        "success": success,
        "duration_ms": duration_ms,
        "cost_usd": str(cost),
    }
    logger.info("Appel API %s", json.dumps(entry, ensure_ascii=False))
    try:
        ApiCall.objects.create(
            service=trace["service"],
            task=trace["task"],
            success=success,
            http_status=trace["http_status"],
            attempts=trace["attempts"],
            duration_ms=duration_ms,
            cost_usd=cost,
        )
    except DatabaseError:
        # Le suivi des coûts ne doit jamais bloquer le traitement d'un rêve.
        logger.exception("Appel API non enregistré en base.")
