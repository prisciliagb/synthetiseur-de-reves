"""Réactions automatiques aux événements sur les rêves."""

import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Dream

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=Dream)
def delete_dream_image(sender: type[Dream], instance: Dream, **kwargs: object) -> None:
    """Supprime l'image d'un rêve quand le rêve est supprimé (RGPD).

    Django ne supprime pas les fichiers tout seul : sans ce signal, l'image
    resterait sur Cloudinary après la suppression du rêve ou du compte.

    Args:
        sender: La classe du modèle supprimé.
        instance: Le rêve supprimé.
        **kwargs: Autres informations envoyées par Django.
    """
    if not instance.image:
        return
    try:
        instance.image.delete(save=False)
    except OSError:
        # La suppression du rêve ne doit pas échouer à cause du stockage.
        logger.error("Image du rêve %s non supprimée du stockage.", instance.pk)
