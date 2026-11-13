import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Dream

User = get_user_model()


class DreamModelTests(TestCase):
    """Tests du modèle Dream."""

    def setUp(self) -> None:
        """Crée un utilisateur de test."""
        self.user = User.objects.create_user("alice", "alice@example.com")

    def test_new_dream_is_pending_by_default(self) -> None:
        """Un nouveau rêve est en attente de traitement et daté automatiquement."""
        dream = Dream.objects.create(user=self.user)

        self.assertEqual(dream.status, Dream.Status.PENDING)
        self.assertIsNotNone(dream.created_at)

    def test_str(self) -> None:
        """Un rêve s'affiche avec son auteur et sa date."""
        dream = Dream.objects.create(user=self.user)

        self.assertIn("alice", str(dream))

    def test_confidence_must_be_between_0_and_1(self) -> None:
        """Un score de confiance hors de [0, 1] est refusé."""
        dream = Dream(user=self.user, confidence=1.5)

        with self.assertRaises(ValidationError):
            dream.full_clean()

    def test_unknown_emotion_is_refused(self) -> None:
        """Seules les émotions prévues sont acceptées."""
        dream = Dream(user=self.user, emotion="joie-intense")

        with self.assertRaises(ValidationError):
            dream.full_clean()

    def test_deleting_user_deletes_their_dreams(self) -> None:
        """Supprimer un compte supprime ses rêves (droit à l'effacement RGPD)."""
        Dream.objects.create(user=self.user)

        self.user.delete()

        self.assertFalse(Dream.objects.exists())

    def test_dream_is_registered_in_admin(self) -> None:
        """Le modèle Dream est visible dans l'admin Django."""
        self.assertTrue(admin.site.is_registered(Dream))


class DreamAccessTests(TestCase):
    """Un utilisateur ne peut accéder qu'à ses propres rêves."""

    def setUp(self) -> None:
        """Crée deux utilisateurs ayant chacun un rêve."""
        self.alice = User.objects.create_user("alice", "alice@example.com")
        self.bob = User.objects.create_user("bob", "bob@example.com")
        self.alice_dream = Dream.objects.create(
            user=self.alice, transcription="Je volais au-dessus de la mer"
        )
        self.bob_dream = Dream.objects.create(
            user=self.bob, transcription="J'étais perdu dans une forêt"
        )

    def test_anonymous_user_is_redirected_to_login(self) -> None:
        """Un visiteur non connecté est renvoyé vers la page de connexion."""
        url = reverse("dreams:list")

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_list_shows_only_own_dreams(self) -> None:
        """La liste ne contient que les rêves de l'utilisateur connecté."""
        self.client.force_login(self.alice)

        response = self.client.get(reverse("dreams:list"))

        self.assertEqual(list(response.context["dreams"]), [self.alice_dream])
        self.assertContains(response, "Je volais")
        self.assertNotContains(response, "perdu dans une forêt")

    def test_user_can_see_own_dream(self) -> None:
        """Un utilisateur peut ouvrir son propre rêve."""
        self.client.force_login(self.alice)

        response = self.client.get(reverse("dreams:detail", args=[self.alice_dream.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Je volais")

    def test_user_cannot_see_other_users_dream(self) -> None:
        """Le rêve d'un autre utilisateur renvoie une 404."""
        self.client.force_login(self.alice)

        response = self.client.get(reverse("dreams:detail", args=[self.bob_dream.pk]))

        self.assertEqual(response.status_code, 404)


class DreamHistoryTests(TestCase):
    """Tests de l'historique : ordre, pagination, miniature et icône d'émotion."""

    def setUp(self) -> None:
        """Connecte un utilisateur."""
        self.user = User.objects.create_user("alice", "alice@example.com")
        self.client.force_login(self.user)
        self.url = reverse("dreams:list")

    def create_dreams(self, count: int) -> list[Dream]:
        """Crée des rêves datés d'un jour d'écart, du plus ancien au plus récent.

        Args:
            count: Le nombre de rêves à créer.

        Returns:
            Les rêves créés, du plus ancien au plus récent.
        """
        start = timezone.now() - timedelta(days=count)
        dreams = []
        for day in range(count):
            dream = Dream.objects.create(user=self.user, transcription=f"Rêve {day}")
            # created_at est rempli automatiquement : on le change après coup.
            Dream.objects.filter(pk=dream.pk).update(
                created_at=start + timedelta(days=day)
            )
            dreams.append(dream)
        return dreams

    def test_dreams_are_listed_from_newest_to_oldest(self) -> None:
        """Le rêve le plus récent est affiché en premier."""
        oldest, middle, newest = self.create_dreams(3)

        response = self.client.get(self.url)

        self.assertEqual(list(response.context["dreams"]), [newest, middle, oldest])

    def test_list_shows_ten_dreams_per_page(self) -> None:
        """L'historique affiche 10 rêves par page, la suite en page 2."""
        dreams = self.create_dreams(11)

        first_page = self.client.get(self.url)
        second_page = self.client.get(self.url, {"page": 2})

        self.assertEqual(len(first_page.context["dreams"]), 10)
        self.assertContains(first_page, "Page 1 sur 2")
        self.assertEqual(list(second_page.context["dreams"]), [dreams[0]])

    def test_no_pagination_with_few_dreams(self) -> None:
        """Avec 10 rêves ou moins, il n'y a pas de navigation entre pages."""
        self.create_dreams(10)

        response = self.client.get(self.url)

        self.assertNotContains(response, "Page 1 sur")

    def test_unknown_page_returns_404(self) -> None:
        """Une page qui n'existe pas renvoie une erreur 404."""
        self.create_dreams(3)

        response = self.client.get(self.url, {"page": 5})

        self.assertEqual(response.status_code, 404)

    def test_dream_without_image_shows_placeholder(self) -> None:
        """Un rêve sans image affiche la petite lune de remplacement."""
        self.create_dreams(1)

        response = self.client.get(self.url)

        self.assertContains(response, "img/dream-placeholder.svg")

    def test_dream_with_image_shows_thumbnail(self) -> None:
        """Un rêve avec une image affiche sa miniature."""
        Dream.objects.create(user=self.user, image="dreams/2026/11/abc.webp")

        response = self.client.get(self.url)

        self.assertContains(response, "dreams/2026/11/abc.webp")
        self.assertNotContains(response, "img/dream-placeholder.svg")

    @override_settings(
        CLOUDINARY_URL="cloudinary://123456:secret@demo-cloud",
        STORAGES={
            "default": {"BACKEND": "dreams.storage.CloudinaryStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        },
    )
    def test_thumbnail_is_resized_by_cloudinary(self) -> None:
        """Avec Cloudinary, l'historique charge une miniature, pas l'image entière."""
        Dream.objects.create(user=self.user, image="dreams/2026/11/abc.webp")

        response = self.client.get(self.url)

        self.assertContains(response, "/c_fill,h_120,w_120/")
        self.assertContains(response, "dreams/2026/11/abc.webp")

    def test_emotion_is_shown_with_its_icon(self) -> None:
        """L'émotion d'un rêve est affichée avec son emoji."""
        Dream.objects.create(user=self.user, emotion=Dream.Emotion.SCARY)

        response = self.client.get(self.url)

        self.assertContains(response, "😱")
        self.assertContains(response, "Effrayant")

    def test_every_emotion_has_an_icon(self) -> None:
        """Chaque émotion possible a son emoji (aucun oubli si on en ajoute une)."""
        for emotion in Dream.Emotion:
            with self.subTest(emotion=emotion):
                self.assertNotEqual(Dream(emotion=emotion).emotion_icon, "")


class DreamFilterTests(TestCase):
    """Tests des filtres de l'historique : période et émotion."""

    def setUp(self) -> None:
        """Crée quatre rêves à des dates et émotions différentes."""
        self.user = User.objects.create_user("alice", "alice@example.com")
        self.client.force_login(self.user)
        self.url = reverse("dreams:list")
        self.october_scary = self.create_dream(date(2026, 10, 15), "scary")
        self.november_scary = self.create_dream(date(2026, 11, 2), "scary")
        self.november_happy = self.create_dream(date(2026, 11, 10), "happy")
        self.december_sad = self.create_dream(date(2026, 12, 1), "sad")

    def create_dream(self, day: date, emotion: str) -> Dream:
        """Crée un rêve daté de `day` à 8 h (heure de Paris).

        Args:
            day: Le jour du rêve.
            emotion: L'émotion du rêve.

        Returns:
            Le rêve créé.
        """
        dream = Dream.objects.create(user=self.user, emotion=emotion)
        created_at = timezone.make_aware(datetime.combine(day, time(8)))
        Dream.objects.filter(pk=dream.pk).update(created_at=created_at)
        return dream

    def get_dreams(self, **filters: str) -> list[Dream]:
        """Affiche l'historique avec ces filtres et renvoie les rêves listés."""
        response = self.client.get(self.url, filters)
        return list(response.context["dreams"])

    def test_without_filter_all_dreams_are_listed(self) -> None:
        """Sans filtre, tous les rêves sont affichés."""
        self.assertEqual(len(self.get_dreams()), 4)

    def test_filter_by_period(self) -> None:
        """Seuls les rêves de la période sont affichés, bornes comprises."""
        dreams = self.get_dreams(start="2026-11-02", end="2026-11-10")

        self.assertEqual(dreams, [self.november_happy, self.november_scary])

    def test_filter_with_start_date_only(self) -> None:
        """Avec seulement « Du », on garde les rêves à partir de cette date."""
        dreams = self.get_dreams(start="2026-11-05")

        self.assertEqual(dreams, [self.december_sad, self.november_happy])

    def test_filter_by_emotion(self) -> None:
        """Seuls les rêves de l'émotion choisie sont affichés."""
        dreams = self.get_dreams(emotion="scary")

        self.assertEqual(dreams, [self.november_scary, self.october_scary])

    def test_filters_are_combined(self) -> None:
        """Période et émotion se combinent."""
        dreams = self.get_dreams(start="2026-11-01", end="2026-11-30", emotion="scary")

        self.assertEqual(dreams, [self.november_scary])

    def test_start_after_end_shows_an_error(self) -> None:
        """Une période à l'envers affiche une erreur et ne filtre pas."""
        response = self.client.get(
            self.url, {"start": "2026-12-01", "end": "2026-11-01"}
        )

        self.assertContains(response, "La date de début doit être avant")
        self.assertEqual(len(response.context["dreams"]), 4)

    def test_invalid_values_show_an_error(self) -> None:
        """Une date ou une émotion inconnue affiche une erreur, sans planter."""
        response = self.client.get(
            self.url, {"start": "pas-une-date", "emotion": "joie"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["filter_form"].errors)
        self.assertEqual(len(response.context["dreams"]), 4)

    def test_no_result_shows_a_message(self) -> None:
        """Si aucun rêve ne correspond, la page l'indique."""
        response = self.client.get(self.url, {"emotion": "strange"})

        self.assertContains(response, "Aucun rêve ne correspond à ces filtres.")

    def test_filters_are_kept_when_changing_page(self) -> None:
        """Les liens de pagination gardent les filtres."""
        for _ in range(11):
            self.create_dream(date(2026, 11, 20), "scary")

        response = self.client.get(self.url, {"emotion": "scary"})

        self.assertContains(response, "?emotion=scary&amp;page=2")

    def test_filters_only_apply_to_own_dreams(self) -> None:
        """Les filtres ne font jamais apparaître les rêves des autres."""
        bob = User.objects.create_user("bob", "bob@example.com")
        Dream.objects.create(user=bob, emotion="scary")

        dreams = self.get_dreams(emotion="scary")

        self.assertEqual(dreams, [self.november_scary, self.october_scary])


class DreamDeleteTests(TestCase):
    """Tests de la suppression d'un rêve."""

    def setUp(self) -> None:
        """Crée deux utilisateurs ayant chacun un rêve, et connecte Alice."""
        self.alice = User.objects.create_user("alice", "alice@example.com")
        self.bob = User.objects.create_user("bob", "bob@example.com")
        self.alice_dream = Dream.objects.create(
            user=self.alice, transcription="Je volais au-dessus de la mer"
        )
        self.bob_dream = Dream.objects.create(
            user=self.bob, transcription="J'étais perdu dans une forêt"
        )
        self.client.force_login(self.alice)

    def delete_url(self, dream: Dream) -> str:
        """Renvoie l'adresse de suppression d'un rêve."""
        return reverse("dreams:delete", args=[dream.pk])

    def test_detail_page_has_delete_button(self) -> None:
        """La page d'un rêve propose de le supprimer."""
        response = self.client.get(reverse("dreams:detail", args=[self.alice_dream.pk]))

        self.assertContains(response, self.delete_url(self.alice_dream))

    def test_get_asks_for_confirmation_without_deleting(self) -> None:
        """Ouvrir la page de suppression demande confirmation, sans rien supprimer."""
        response = self.client.get(self.delete_url(self.alice_dream))

        self.assertContains(response, "Supprimer ce rêve ?")
        self.assertContains(response, "Je volais")
        self.assertTrue(Dream.objects.filter(pk=self.alice_dream.pk).exists())

    def test_post_deletes_dream_and_redirects_to_history(self) -> None:
        """Confirmer supprime le rêve et renvoie vers l'historique avec un message."""
        response = self.client.post(self.delete_url(self.alice_dream), follow=True)

        self.assertRedirects(response, reverse("dreams:list"))
        self.assertContains(response, "Votre rêve a bien été supprimé.")
        self.assertFalse(Dream.objects.filter(pk=self.alice_dream.pk).exists())

    def test_user_cannot_delete_other_users_dream(self) -> None:
        """Le rêve d'un autre utilisateur renvoie une 404 et n'est pas supprimé."""
        page = self.client.get(self.delete_url(self.bob_dream))
        deletion = self.client.post(self.delete_url(self.bob_dream))

        self.assertEqual(page.status_code, 404)
        self.assertEqual(deletion.status_code, 404)
        self.assertTrue(Dream.objects.filter(pk=self.bob_dream.pk).exists())

    def test_anonymous_user_cannot_delete(self) -> None:
        """Un visiteur non connecté est renvoyé vers la connexion."""
        self.client.logout()

        response = self.client.post(self.delete_url(self.alice_dream))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)
        self.assertTrue(Dream.objects.filter(pk=self.alice_dream.pk).exists())


def fake_audio(header: bytes, name: str = "reve.webm") -> SimpleUploadedFile:
    """Crée un faux fichier audio qui commence par la signature donnée.

    Args:
        header: Premiers octets du fichier (signature du format).
        name: Nom du fichier.

    Returns:
        Un fichier prêt à être envoyé dans une requête de test.
    """
    return SimpleUploadedFile(name, header + b"\x00" * 100, content_type="audio/webm")


WEBM_HEADER = b"\x1a\x45\xdf\xa3"
MP4_HEADER = b"\x00\x00\x00\x20ftypM4A "


class RecordPageTests(TestCase):
    """Tests de la page « Raconter un rêve »."""

    def test_anonymous_user_is_redirected_to_login(self) -> None:
        """La page d'enregistrement exige d'être connecté."""
        url = reverse("dreams:record")

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_page_gives_settings_to_javascript(self) -> None:
        """La page transmet au JavaScript l'URL d'envoi et la durée maximale."""
        user = User.objects.create_user("alice", "alice@example.com")
        self.client.force_login(user)

        response = self.client.get(reverse("dreams:record"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, f'data-upload-url="{reverse("dreams:upload_audio")}"'
        )
        self.assertContains(response, 'data-max-seconds="300"')
        self.assertContains(response, "js/recorder.js")


class AudioUploadTests(TestCase):
    """Tests de la réception de l'enregistrement audio.

    La transcription est simulée : ces tests n'appellent jamais Groq.
    """

    def setUp(self) -> None:
        """Connecte un utilisateur de test et simule la transcription."""
        self.user = User.objects.create_user("alice", "alice@example.com")
        self.client.force_login(self.user)
        self.url = reverse("dreams:upload_audio")
        patcher = patch("dreams.views.transcribe", return_value="Je volais.")
        self.transcribe = patcher.start()
        self.addCleanup(patcher.stop)

    def test_anonymous_user_cannot_upload(self) -> None:
        """Un visiteur non connecté ne peut pas envoyer d'audio."""
        self.client.logout()

        response = self.client.post(self.url, {"audio": fake_audio(WEBM_HEADER)})

        self.assertEqual(response.status_code, 302)

    def test_get_is_not_allowed(self) -> None:
        """L'URL d'envoi n'accepte que les requêtes POST."""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)

    def test_browser_formats_are_accepted(self) -> None:
        """Les formats produits par les navigateurs sont acceptés."""
        for header in (WEBM_HEADER, MP4_HEADER):
            with self.subTest(header=header):
                response = self.client.post(self.url, {"audio": fake_audio(header)})

                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["ok"])

    def test_missing_audio_is_refused(self) -> None:
        """Une requête sans fichier est refusée avec un message clair."""
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Aucun enregistrement n'a été reçu.")

    def test_non_audio_file_is_refused(self) -> None:
        """Un fichier qui n'est pas de l'audio est refusé, même renommé en .webm."""
        response = self.client.post(
            self.url, {"audio": fake_audio(b"Ceci est un texte", name="faux.webm")}
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    @override_settings(DREAM_AUDIO_MAX_SIZE=50)
    def test_too_large_audio_is_refused(self) -> None:
        """Un enregistrement plus lourd que la limite est refusé."""
        response = self.client.post(self.url, {"audio": fake_audio(WEBM_HEADER)})

        self.assertEqual(response.status_code, 400)
        self.assertIn("trop lourd", response.json()["error"])

    def test_audio_is_never_stored(self) -> None:
        """Seule la transcription est conservée, jamais l'audio (RGPD)."""
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                self.client.post(self.url, {"audio": fake_audio(WEBM_HEADER)})

            self.assertEqual(list(Path(media_root).iterdir()), [])
        self.assertEqual(Dream.objects.get().transcription, "Je volais.")

    def test_invalid_audio_is_never_sent_to_groq(self) -> None:
        """Un fichier refusé n'est jamais envoyé à l'API de transcription."""
        self.client.post(self.url, {"audio": fake_audio(b"Ceci est un texte")})

        self.transcribe.assert_not_called()
