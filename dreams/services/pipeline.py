"""Enchaînement des étapes de traitement d'un rêve.

Un rêve passe par trois étapes : transcription → analyse → image. Chaque
étape enregistre son résultat dès qu'elle réussit : si une étape échoue, les
résultats déjà obtenus sont conservés et l'étape peut être relancée.

La transcription a lieu à l'envoi de l'audio (l'audio n'est jamais gardé) ;
ce module gère les étapes suivantes, qui ne dépendent que du texte.
"""

from django.urls import reverse

from ..models import Dream
from .analysis import AnalysisError, analyze_dream
from .image import ImageGenerationError, generate_dream_image

# Les étapes, dans l'ordre. Le nom sert aussi de nom d'URL (« dreams:analysis »).
ANALYSIS = "analysis"
IMAGE = "image"


class StepError(Exception):
    """Une étape du traitement a échoué.

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


def next_step(dream: Dream) -> str | None:
    """Indique la prochaine étape à faire pour ce rêve.

    Elle se déduit de ce qui est déjà enregistré : pas d'émotion → analyse,
    pas d'image → image.

    Args:
        dream: Le rêve.

    Returns:
        Le nom de la prochaine étape, ou None si le rêve est complet.
    """
    if not dream.emotion:
        return ANALYSIS
    if not dream.image:
        return IMAGE
    return None


def progress(dream: Dream) -> dict[str, str | None]:
    """Décrit l'avancement du rêve pour le JavaScript.

    Args:
        dream: Le rêve.

    Returns:
        La prochaine étape, l'adresse pour la lancer (ou None si tout est
        fait) et l'adresse de la page du rêve.
    """
    step = next_step(dream)
    return {
        "next_step": step,
        "next_url": reverse(f"dreams:{step}", args=[dream.pk]) if step else None,
        "redirect_url": reverse("dreams:detail", args=[dream.pk]),
    }


def run_step(dream: Dream, step: str) -> None:
    """Exécute une étape et enregistre le rêve, qu'elle réussisse ou non.

    Args:
        dream: Le rêve à traiter.
        step: L'étape à exécuter (ANALYSIS ou IMAGE).

    Raises:
        StepError: Si l'étape a échoué. Le rêve est alors en statut « Échec »
            et garde les résultats des étapes précédentes.
    """
    dream.status = Dream.Status.PROCESSING
    try:
        if step == ANALYSIS:
            _analyze(dream)
        else:
            _generate_image(dream)
    except StepError:
        dream.status = Dream.Status.FAILED
        dream.save()
        raise
    if next_step(dream) is None:
        dream.status = Dream.Status.DONE
    dream.save()


def _analyze(dream: Dream) -> None:
    """Détecte l'émotion du rêve et écrit le prompt de son image.

    Args:
        dream: Le rêve, dont la transcription est remplie.

    Raises:
        StepError: Si l'analyse a échoué.
    """
    try:
        analysis = analyze_dream(dream.transcription)
    except AnalysisError:
        raise StepError(
            "L'analyse de l'émotion n'a pas abouti. Votre texte est bien "
            "enregistré : vous pourrez relancer l'analyse."
        ) from None
    dream.emotion = analysis.emotion
    dream.confidence = analysis.confidence
    dream.image_prompt = analysis.image_prompt


def _generate_image(dream: Dream) -> None:
    """Génère et stocke l'image du rêve.

    Args:
        dream: Le rêve, dont le prompt d'image est rempli.

    Raises:
        StepError: Si l'image n'a pas pu être créée.
    """
    try:
        generate_dream_image(dream)
    except ImageGenerationError:
        raise StepError(
            "L'image n'a pas pu être créée. Votre rêve et son émotion sont bien "
            "enregistrés : vous pourrez relancer la création de l'image."
        ) from None
