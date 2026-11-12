"""Stockage des images des rêves sur Cloudinary.

Le disque d'un hébergeur comme Render est effacé à chaque redéploiement :
une image enregistrée dans `media/` y disparaîtrait. Ce « storage » Django
envoie donc les fichiers sur Cloudinary, qui les conserve.

Il est branché dans `settings.STORAGES` : le champ `Dream.image` l'utilise sans
rien changer au modèle, et `dream.image.url` renvoie l'adresse Cloudinary.
"""

import logging
import posixpath
from urllib.parse import urlparse

import cloudinary
import cloudinary.exceptions
import cloudinary.uploader
import cloudinary.utils
from django.conf import settings
from django.core.files.base import File
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

logger = logging.getLogger(__name__)


def _split_name(name: str) -> tuple[str, str]:
    """Sépare un nom de fichier en identifiant Cloudinary et extension.

    Args:
        name: Le nom du fichier, par exemple « dreams/2026/11/ab12.webp ».

    Returns:
        L'identifiant (« dreams/2026/11/ab12 ») et l'extension (« webp »).
    """
    public_id, extension = posixpath.splitext(name)
    return public_id, extension.lstrip(".")


@deconstructible
class CloudinaryStorage(Storage):
    """Enregistre les fichiers sur Cloudinary au lieu du disque."""

    def __init__(self) -> None:
        """Configure Cloudinary à partir de CLOUDINARY_URL.

        CLOUDINARY_URL a la forme cloudinary://<api_key>:<api_secret>@<cloud>.
        """
        url = urlparse(settings.CLOUDINARY_URL)
        cloudinary.config(
            cloud_name=url.hostname,
            api_key=url.username,
            api_secret=url.password,
            secure=True,
        )

    def _save(self, name: str, content: File) -> str:
        """Envoie le fichier sur Cloudinary.

        Args:
            name: Le nom voulu pour le fichier.
            content: Le contenu du fichier.

        Returns:
            Le nom sous lequel le fichier est enregistré.

        Raises:
            OSError: Si Cloudinary a refusé ou n'a pas pu recevoir le fichier.
        """
        public_id, _ = _split_name(name)
        content.seek(0)
        try:
            result = cloudinary.uploader.upload(
                content.read(),
                public_id=public_id,
                resource_type="image",
                overwrite=False,
            )
        except cloudinary.exceptions.Error as error:
            # Django attend une OSError quand un stockage échoue.
            raise OSError(f"Envoi sur Cloudinary impossible : {error}") from error
        return f"{result['public_id']}.{result['format']}"

    def url(self, name: str) -> str:
        """Renvoie l'adresse publique (https) de l'image sur Cloudinary.

        Args:
            name: Le nom du fichier enregistré.

        Returns:
            L'adresse de l'image.
        """
        public_id, extension = _split_name(name)
        url, _ = cloudinary.utils.cloudinary_url(
            public_id, format=extension, secure=True
        )
        return url

    def exists(self, name: str) -> bool:
        """Indique si un fichier porte déjà ce nom.

        Les noms sont aléatoires (uuid) : il n'y a jamais de doublon, donc on
        évite un appel inutile à Cloudinary.

        Args:
            name: Le nom du fichier.

        Returns:
            Toujours False.
        """
        return False

    def delete(self, name: str) -> None:
        """Supprime l'image de Cloudinary.

        Args:
            name: Le nom du fichier enregistré.

        Raises:
            OSError: Si Cloudinary n'a pas pu supprimer l'image.
        """
        public_id, _ = _split_name(name)
        try:
            cloudinary.uploader.destroy(public_id, resource_type="image")
        except cloudinary.exceptions.Error as error:
            raise OSError(f"Suppression sur Cloudinary impossible : {error}") from error
