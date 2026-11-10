from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

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
