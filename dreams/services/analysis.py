"""Analyse d'un rêve avec le LLM de Groq : émotion et prompt d'image.

Un seul appel au LLM renvoie, en JSON, l'émotion dominante du rêve, un score
de confiance et une description en anglais pour générer l'image. La réponse
d'un LLM n'est jamais garantie : elle est donc toujours validée avant usage.
"""

import json
import logging
import math
from dataclasses import dataclass
from decimal import Decimal

import httpx
from django.conf import settings

from ..models import Dream
from .api import ApiError, call_api

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

# Longueur maximale gardée pour le prompt d'image (le LLM pourrait déborder).
IMAGE_PROMPT_MAX_LENGTH = 1000


def _system_prompt() -> str:
    """Construit les consignes données au LLM.

    La liste des émotions vient du modèle `Dream` : si on en ajoute une, le
    LLM la connaît automatiquement.

    Returns:
        Les consignes du LLM.
    """
    emotions = "\n".join(
        f'- "{value}" : {label.lower()}' for value, label in Dream.Emotion.choices
    )
    return (
        "Tu analyses le récit d'un rêve raconté par un utilisateur.\n"
        "Réponds uniquement avec un objet JSON, sans aucun autre texte, "
        "de la forme :\n"
        '{"emotion": "...", "confidence": 0.0, "image_prompt": "..."}\n\n'
        "- emotion : l'émotion dominante du rêve, obligatoirement une de ces "
        f"valeurs :\n{emotions}\n"
        "- confidence : ta certitude sur cette émotion, entre 0 et 1.\n"
        "- image_prompt : une description visuelle du rêve, EN ANGLAIS, "
        "en une ou deux phrases, pour un générateur d'images. Décris la scène, "
        "l'ambiance, les couleurs et la lumière. Pas de texte dans l'image, "
        "et aucun nom de personne réelle."
    )


@dataclass(frozen=True)
class DreamAnalysis:
    """Résultat validé de l'analyse d'un rêve.

    Attributes:
        emotion: Une valeur de `Dream.Emotion` (toujours valide).
        confidence: Score entre 0 et 1, ou None s'il est inconnu.
        image_prompt: Description en anglais pour l'image (peut être vide).
    """

    emotion: str
    confidence: float | None
    image_prompt: str


class AnalysisError(Exception):
    """L'analyse du rêve n'a pas pu être faite (Groq indisponible…)."""


def analyze_dream(transcription: str) -> DreamAnalysis:
    """Détecte l'émotion d'un rêve et écrit le prompt de son image.

    Args:
        transcription: Le texte du rêve.

    Returns:
        L'analyse validée du rêve.

    Raises:
        AnalysisError: Si Groq n'a pas pu être appelé.
    """
    try:
        response = call_api(
            lambda: _call_llm(transcription),
            task="Analyse",
            api_key=settings.GROQ_API_KEY,
            max_attempts=settings.GROQ_MAX_ATTEMPTS,
            service="Groq",
            cost=analysis_cost,
        )
    except ApiError:
        raise AnalysisError from None
    return parse_analysis(_extract_content(response))


def analysis_cost(response: httpx.Response) -> Decimal:
    """Estime le coût d'une analyse d'après le nombre de jetons utilisés.

    Groq indique dans sa réponse les jetons lus (« prompt_tokens ») et écrits
    (« completion_tokens ») ; chacun a son prix par million.

    Args:
        response: La réponse de Groq, qui contient « usage ».

    Returns:
        Le coût estimé, en dollars.
    """
    usage = response.json()["usage"]
    million = Decimal(1_000_000)
    return (
        Decimal(usage["prompt_tokens"]) * settings.GROQ_LLM_PRICE_INPUT_PER_MILLION
        + Decimal(usage["completion_tokens"])
        * settings.GROQ_LLM_PRICE_OUTPUT_PER_MILLION
    ) / million


def _call_llm(transcription: str) -> httpx.Response:
    """Envoie le rêve au LLM de Groq.

    Args:
        transcription: Le texte du rêve.

    Returns:
        La réponse HTTP de Groq.

    Raises:
        httpx.TransportError: Si Groq ne répond pas à temps ou est injoignable.
    """
    return httpx.post(
        GROQ_CHAT_URL,
        headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
        json={
            "model": settings.GROQ_LLM_MODEL,
            "messages": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": transcription},
            ],
            # Mode JSON : Groq garantit une réponse au format JSON.
            "response_format": {"type": "json_object"},
            # Réponses peu « créatives » : la classification reste stable.
            "temperature": 0.3,
        },
        timeout=settings.GROQ_TIMEOUT,
    )


def _extract_content(response: httpx.Response) -> str:
    """Récupère le texte écrit par le LLM dans la réponse de Groq.

    Args:
        response: Réponse HTTP 200 de Groq.

    Returns:
        Le texte du LLM, ou une chaîne vide si la réponse est illisible.
    """
    try:
        return response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        logger.error("Analyse : réponse de Groq illisible.")
        return ""


def parse_analysis(content: str) -> DreamAnalysis:
    """Valide la réponse JSON du LLM.

    Tout ce qui est invalide est remplacé par une valeur sûre : une émotion
    inconnue devient « neutre », une confiance invalide devient None.

    Args:
        content: Le texte renvoyé par le LLM, censé être du JSON.

    Returns:
        L'analyse validée.
    """
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        data = None
    if not isinstance(data, dict):
        logger.warning("Analyse : JSON invalide, émotion « neutre » par défaut.")
        return DreamAnalysis(Dream.Emotion.NEUTRAL, None, "")

    emotion = data.get("emotion")
    if emotion in Dream.Emotion.values:
        confidence = _validate_confidence(data.get("confidence"))
    else:
        logger.warning("Analyse : émotion inconnue, « neutre » par défaut.")
        emotion = Dream.Emotion.NEUTRAL
        # La confiance portait sur une émotion invalide : elle ne vaut rien.
        confidence = None

    image_prompt = data.get("image_prompt")
    if not isinstance(image_prompt, str):
        image_prompt = ""
    image_prompt = image_prompt.strip()[:IMAGE_PROMPT_MAX_LENGTH]

    return DreamAnalysis(emotion, confidence, image_prompt)


def _validate_confidence(value: object) -> float | None:
    """Ramène la confiance entre 0 et 1.

    Args:
        value: La confiance donnée par le LLM.

    Returns:
        Un nombre entre 0 et 1, ou None si la valeur n'est pas un nombre.
    """
    # bool est un sous-type de int en Python : on l'exclut explicitement.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if math.isnan(value):
        return None
    return min(max(float(value), 0.0), 1.0)
