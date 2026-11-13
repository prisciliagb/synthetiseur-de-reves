"""Tests de l'image du rêve : génération, stockage et image de remplacement.

Replicate et Cloudinary ne sont jamais appelés pour de vrai : leurs fonctions
sont remplacées par des faux (« mocks »). Les images de test sont écrites dans
un dossier temporaire, effacé à la fin.
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import cloudinary.exceptions
import httpx
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .models import Dream
from .services.image import ImageGenerationError, generate_dream_image
from .storage import CloudinaryStorage

User = get_user_model()

IMAGE_URL = "https://replicate.delivery/abc/out-0.webp"
IMAGE_BYTES = b"RIFF\x00\x00\x00\x00WEBPVP8 fausse image"


def replicate_response(status_code: int = 201, json: object = None) -> httpx.Response:
    """Fabrique une fausse réponse de Replicate.

    Args:
        status_code: Code HTTP de la réponse.
        json: Contenu JSON ; par défaut, une génération réussie.

    Returns:
        La réponse HTTP simulée.
    """
    if json is None:
        json = {"status": "succeeded", "output": [IMAGE_URL]}
    request = httpx.Request("POST", "https://api.replicate.com/v1/predictions")
    return httpx.Response(status_code, json=json, request=request)


def image_download(content_type: str = "image/webp") -> httpx.Response:
    """Fabrique le faux téléchargement de l'image produite.

    Args:
        content_type: Type annoncé du fichier téléchargé.

    Returns:
        La réponse HTTP simulée.
    """
    return httpx.Response(
        200,
        content=IMAGE_BYTES,
        headers={"content-type": content_type},
        request=httpx.Request("GET", IMAGE_URL),
    )


class TemporaryMediaMixin:
    """Écrit les fichiers de test dans un dossier temporaire."""

    def setUp(self) -> None:
        """Crée le dossier temporaire et l'utilise comme MEDIA_ROOT."""
        super().setUp()
        self.media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        settings_override = override_settings(MEDIA_ROOT=self.media_root)
        settings_override.enable()
        self.addCleanup(settings_override.disable)


@override_settings(REPLICATE_API_TOKEN="jeton-de-test", REPLICATE_MAX_ATTEMPTS=2)
@patch("dreams.services.api.time.sleep")
@patch("dreams.services.image.httpx.get")
@patch("dreams.services.image.httpx.post")
class GenerateDreamImageTests(TemporaryMediaMixin, SimpleTestCase):
    """Tests du service `generate_dream_image()`."""

    def make_dream(self) -> Dream:
        """Crée un rêve (non enregistré) avec un prompt d'image."""
        return Dream(image_prompt="A house floating above the sea.")

    def test_image_is_generated_and_stored(self, post, get, sleep) -> None:
        """L'image produite par Replicate est téléchargée puis stockée."""
        post.return_value = replicate_response()
        get.return_value = image_download()
        dream = self.make_dream()

        generate_dream_image(dream)

        self.assertTrue(dream.image.name.startswith("dreams/"))
        self.assertTrue(dream.image.name.endswith(".webp"))
        self.assertEqual(
            (Path(self.media_root) / dream.image.name).read_bytes(), IMAGE_BYTES
        )
        get.assert_called_once()
        self.assertEqual(get.call_args.args[0], IMAGE_URL)

    def test_calls_flux_schnell_with_prompt_and_timeout(self, post, get, sleep) -> None:
        """L'appel envoie le prompt à FLUX Schnell, avec un délai maximal."""
        post.return_value = replicate_response()
        get.return_value = image_download()

        generate_dream_image(self.make_dream())

        url = post.call_args.args[0]
        kwargs = post.call_args.kwargs
        self.assertIn("black-forest-labs/flux-schnell", url)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer jeton-de-test")
        self.assertEqual(
            kwargs["json"]["input"]["prompt"], "A house floating above the sea."
        )
        self.assertIn("timeout", kwargs)

    def test_image_names_are_random(self, post, get, sleep) -> None:
        """Deux images n'ont jamais le même nom (adresse impossible à deviner)."""
        post.return_value = replicate_response()
        get.return_value = image_download()
        first, second = self.make_dream(), self.make_dream()

        generate_dream_image(first)
        generate_dream_image(second)

        self.assertNotEqual(first.image.name, second.image.name)

    def test_retries_after_timeout(self, post, get, sleep) -> None:
        """Après un délai dépassé, une nouvelle tentative est faite."""
        post.side_effect = [httpx.ReadTimeout("trop long"), replicate_response()]
        get.return_value = image_download()
        dream = self.make_dream()

        generate_dream_image(dream)

        self.assertEqual(post.call_count, 2)
        self.assertTrue(dream.image)

    def test_replicate_unavailable_raises_error(self, post, get, sleep) -> None:
        """Si Replicate reste injoignable, une erreur est levée, sans image."""
        post.side_effect = httpx.ConnectError("injoignable")
        dream = self.make_dream()

        with self.assertRaises(ImageGenerationError):
            generate_dream_image(dream)

        self.assertEqual(post.call_count, 2)
        self.assertFalse(dream.image)

    def test_refused_request_is_not_retried(self, post, get, sleep) -> None:
        """Une requête refusée (422 : prompt invalide…) n'est pas retentée."""
        post.return_value = replicate_response(422, {"detail": "invalid"})

        with self.assertRaises(ImageGenerationError):
            generate_dream_image(self.make_dream())

        self.assertEqual(post.call_count, 1)

    def test_failed_generation_raises_error(self, post, get, sleep) -> None:
        """Une génération échouée (contenu refusé…) lève une erreur."""
        post.return_value = replicate_response(
            json={"status": "failed", "output": None, "error": "NSFW"}
        )

        with self.assertRaises(ImageGenerationError):
            generate_dream_image(self.make_dream())

        get.assert_not_called()

    def test_downloaded_file_must_be_an_image(self, post, get, sleep) -> None:
        """Un téléchargement qui n'est pas une image est refusé."""
        post.return_value = replicate_response()
        get.return_value = image_download(content_type="text/html")

        with self.assertRaises(ImageGenerationError):
            generate_dream_image(self.make_dream())

    def test_storage_failure_raises_error(self, post, get, sleep) -> None:
        """Si le stockage (Cloudinary) échoue, une erreur est levée."""
        post.return_value = replicate_response()
        get.return_value = image_download()

        with patch(
            "django.core.files.storage.FileSystemStorage._save",
            side_effect=OSError("stockage indisponible"),
        ):
            with self.assertRaises(ImageGenerationError):
                generate_dream_image(self.make_dream())

    def test_empty_prompt_never_calls_replicate(self, post, get, sleep) -> None:
        """Sans prompt d'image, Replicate n'est pas appelé."""
        with self.assertRaises(ImageGenerationError):
            generate_dream_image(Dream(image_prompt=""))

        post.assert_not_called()

    @override_settings(REPLICATE_API_TOKEN="")
    def test_missing_token_never_calls_replicate(self, post, get, sleep) -> None:
        """Sans jeton configuré, Replicate n'est pas appelé."""
        with self.assertRaises(ImageGenerationError):
            generate_dream_image(self.make_dream())

        post.assert_not_called()


@override_settings(CLOUDINARY_URL="cloudinary://123456:secret@demo-cloud")
class CloudinaryStorageTests(SimpleTestCase):
    """Tests du stockage des images sur Cloudinary."""

    @patch("dreams.storage.cloudinary.uploader.upload")
    def test_save_uploads_to_cloudinary(self, upload) -> None:
        """Enregistrer une image l'envoie sur Cloudinary."""
        upload.return_value = {"public_id": "dreams/2026/11/abc", "format": "webp"}

        name = CloudinaryStorage().save(
            "dreams/2026/11/abc.webp", ContentFile(IMAGE_BYTES)
        )

        self.assertEqual(name, "dreams/2026/11/abc.webp")
        self.assertEqual(upload.call_args.args[0], IMAGE_BYTES)
        self.assertEqual(upload.call_args.kwargs["public_id"], "dreams/2026/11/abc")

    @patch(
        "dreams.storage.cloudinary.uploader.upload",
        side_effect=cloudinary.exceptions.Error("refusé"),
    )
    def test_upload_error_becomes_oserror(self, upload) -> None:
        """Une erreur de Cloudinary devient une OSError, comme le veut Django."""
        with self.assertRaises(OSError):
            CloudinaryStorage().save("dreams/abc.webp", ContentFile(IMAGE_BYTES))

    def test_url_points_to_cloudinary_in_https(self) -> None:
        """L'adresse de l'image est une adresse Cloudinary sécurisée."""
        url = CloudinaryStorage().url("dreams/2026/11/abc.webp")

        self.assertTrue(url.startswith("https://res.cloudinary.com/demo-cloud/"))
        self.assertTrue(url.endswith("dreams/2026/11/abc.webp"))

    def test_thumbnail_url_asks_cloudinary_for_a_small_square(self) -> None:
        """La miniature demande à Cloudinary une image carrée réduite."""
        url = CloudinaryStorage().thumbnail_url("dreams/2026/11/abc.webp", 120)

        self.assertTrue(url.startswith("https://res.cloudinary.com/demo-cloud/"))
        self.assertIn("c_fill,h_120,w_120", url)
        self.assertTrue(url.endswith("dreams/2026/11/abc.webp"))

    @patch("dreams.storage.cloudinary.uploader.destroy")
    def test_delete_removes_image_from_cloudinary(self, destroy) -> None:
        """Supprimer l'image la supprime de Cloudinary."""
        CloudinaryStorage().delete("dreams/2026/11/abc.webp")

        destroy.assert_called_once_with("dreams/2026/11/abc", resource_type="image")


class DeleteImageTests(TemporaryMediaMixin, TestCase):
    """RGPD : l'image d'un rêve est supprimée avec le rêve."""

    def setUp(self) -> None:
        """Crée un rêve avec une image."""
        super().setUp()
        self.user = User.objects.create_user("alice", "alice@example.com")
        self.dream = Dream(user=self.user)
        self.dream.image.save("abc.webp", ContentFile(IMAGE_BYTES))
        self.path = Path(self.dream.image.path)

    def test_deleting_dream_deletes_its_image(self) -> None:
        """Supprimer un rêve supprime son image du stockage."""
        self.assertTrue(self.path.exists())

        self.dream.delete()

        self.assertFalse(self.path.exists())

    def test_delete_page_deletes_image(self) -> None:
        """Supprimer un rêve depuis le site supprime aussi son image."""
        self.client.force_login(self.user)

        self.client.post(reverse("dreams:delete", args=[self.dream.pk]))

        self.assertFalse(Dream.objects.exists())
        self.assertFalse(self.path.exists())

    def test_deleting_account_deletes_images(self) -> None:
        """Supprimer un compte supprime les images de ses rêves."""
        self.user.delete()

        self.assertFalse(self.path.exists())
