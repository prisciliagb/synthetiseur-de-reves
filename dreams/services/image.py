"""Génération de l'image d'un rêve avec Replicate FLUX Schnell.

Le prompt en anglais écrit par l'analyse (#10) est envoyé à FLUX Schnell. On
télécharge l'image produite, puis on l'enregistre dans le champ `Dream.image`,
c'est-à-dire sur Cloudinary (voir `dreams/storage.py`).
"""

import logging
import uuid

import httpx
from django.conf import settings
from django.core.files.base import ContentFile

from ..models import Dream
from .api import ApiError, call_api

logger = logging.getLogger(__name__)

REPLICATE_API_URL = "https://api.replicate.com/v1"
IMAGE_FORMAT = "webp"


class ImageGenerationError(Exception):
    """L'image du rêve n'a pas pu être générée ou enregistrée."""


def generate_dream_image(dream: Dream) -> None:
    """Génère l'image d'un rêve et l'attache au rêve (sans l'enregistrer).

    Args:
        dream: Le rêve, dont `image_prompt` est déjà rempli.

    Raises:
        ImageGenerationError: Si l'image n'a pas pu être générée,
            téléchargée ou stockée. Le rêve n'a alors pas d'image et la page
            affiche l'image de remplacement.
    """
    if not dream.image_prompt:
        raise ImageGenerationError("Aucun prompt d'image.")

    image_url = _create_image(dream.image_prompt)
    image = _download(image_url)
    try:
        # Nom aléatoire : impossible de deviner l'adresse de l'image d'un
        # autre utilisateur. `save=False` : la vue enregistre le rêve.
        dream.image.save(f"{uuid.uuid4().hex}.{IMAGE_FORMAT}", image, save=False)
    except OSError as error:
        logger.error("Image : stockage impossible (%s).", type(error).__name__)
        raise ImageGenerationError("Stockage impossible.") from error


def _create_image(prompt: str) -> str:
    """Demande l'image à FLUX Schnell et renvoie son adresse temporaire.

    Args:
        prompt: La description de l'image, en anglais.

    Returns:
        L'adresse de l'image chez Replicate (valable environ une heure).

    Raises:
        ImageGenerationError: Si Replicate n'a pas produit d'image.
    """
    try:
        response = call_api(
            lambda: _call_replicate(prompt),
            task="Image",
            api_key=settings.REPLICATE_API_TOKEN,
            max_attempts=settings.REPLICATE_MAX_ATTEMPTS,
        )
    except ApiError:
        raise ImageGenerationError("Replicate indisponible.") from None

    try:
        prediction = response.json()
        status = prediction["status"]
        output = prediction["output"]
    except (ValueError, KeyError, TypeError):
        logger.error("Image : réponse de Replicate illisible.")
        raise ImageGenerationError("Réponse illisible.") from None

    if status != "succeeded" or not output:
        # « failed » (contenu refusé…) ou image pas prête à temps.
        logger.error("Image : génération non aboutie (statut « %s »).", status)
        raise ImageGenerationError("Génération non aboutie.")
    # FLUX Schnell renvoie une liste d'adresses (une par image demandée).
    return output[0] if isinstance(output, list) else output


def _call_replicate(prompt: str) -> httpx.Response:
    """Lance la génération de l'image sur Replicate.

    Args:
        prompt: La description de l'image, en anglais.

    Returns:
        La réponse HTTP de Replicate.

    Raises:
        httpx.TransportError: Si Replicate ne répond pas à temps.
    """
    return httpx.post(
        f"{REPLICATE_API_URL}/models/{settings.REPLICATE_MODEL}/predictions",
        headers={
            "Authorization": f"Bearer {settings.REPLICATE_API_TOKEN}",
            # Replicate attend que l'image soit prête (60 s max) avant de
            # répondre : pas besoin de redemander où en est la génération.
            "Prefer": "wait",
        },
        json={
            "input": {
                "prompt": prompt,
                "aspect_ratio": "1:1",
                "num_outputs": 1,
                "output_format": IMAGE_FORMAT,
                "output_quality": 80,
            }
        },
        timeout=settings.REPLICATE_TIMEOUT,
    )


def _download(url: str) -> ContentFile:
    """Télécharge l'image produite par Replicate.

    Args:
        url: L'adresse temporaire de l'image.

    Returns:
        Le contenu de l'image.

    Raises:
        ImageGenerationError: Si le téléchargement a échoué ou si le fichier
            n'est pas une image de taille raisonnable.
    """
    try:
        response = call_api(
            lambda: httpx.get(url, timeout=settings.REPLICATE_TIMEOUT),
            task="Téléchargement de l'image",
            api_key=settings.REPLICATE_API_TOKEN,
            max_attempts=settings.REPLICATE_MAX_ATTEMPTS,
        )
    except ApiError:
        raise ImageGenerationError("Téléchargement impossible.") from None

    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        logger.error("Image : le fichier téléchargé n'est pas une image.")
        raise ImageGenerationError("Fichier invalide.")
    if len(response.content) > settings.DREAM_IMAGE_MAX_SIZE:
        logger.error("Image : fichier téléchargé trop lourd.")
        raise ImageGenerationError("Fichier trop lourd.")
    return ContentFile(response.content)
