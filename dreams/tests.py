from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class DreamAccessTests(TestCase):
    """Les pages de rêves sont réservées aux utilisateurs connectés."""

    def test_dream_list_redirects_anonymous_user_to_login(self) -> None:
        """Un visiteur non connecté est renvoyé vers la page de connexion."""
        url = reverse("dreams:list")

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_dream_list_is_accessible_when_logged_in(self) -> None:
        """Un utilisateur connecté accède à ses rêves."""
        user = get_user_model().objects.create_user("alice", "alice@example.com")
        self.client.force_login(user)

        response = self.client.get(reverse("dreams:list"))

        self.assertEqual(response.status_code, 200)
