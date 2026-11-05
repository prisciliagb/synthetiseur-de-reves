from django.test import TestCase
from django.urls import reverse

from .models import User

PASSWORD = "UnMotDePasse-Solide-42"


class SignUpTests(TestCase):
    """Tests de l'inscription."""

    def _signup_data(self, **overrides: str) -> dict[str, str]:
        """Construit des données d'inscription valides.

        Args:
            **overrides: Champs à remplacer ou à ajouter.

        Returns:
            Les données du formulaire d'inscription.
        """
        data = {
            "username": "alice",
            "email": "alice@example.com",
            "password1": PASSWORD,
            "password2": PASSWORD,
            "rgpd_consent": "on",
        }
        data.update(overrides)
        return data

    def test_signup_page_is_public(self) -> None:
        """La page d'inscription est accessible sans être connecté."""
        response = self.client.get(reverse("accounts:signup"))
        self.assertEqual(response.status_code, 200)

    def test_signup_creates_user_and_logs_in(self) -> None:
        """Une inscription valide crée le compte et connecte l'utilisateur."""
        response = self.client.post(reverse("accounts:signup"), self._signup_data())

        self.assertRedirects(response, reverse("dreams:list"))
        user = User.objects.get(username="alice")
        self.assertIsNotNone(user.rgpd_consent_at)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_signup_without_rgpd_consent_is_refused(self) -> None:
        """Sans consentement RGPD, aucun compte n'est créé."""
        data = self._signup_data()
        del data["rgpd_consent"]

        response = self.client.post(reverse("accounts:signup"), data)

        self.assertEqual(response.status_code, 200)
        self.assertIn("rgpd_consent", response.context["form"].errors)
        self.assertFalse(User.objects.exists())

    def test_signup_with_existing_email_is_refused(self) -> None:
        """Deux comptes ne peuvent pas partager la même adresse e-mail."""
        User.objects.create_user("bob", "alice@example.com", PASSWORD)

        response = self.client.post(reverse("accounts:signup"), self._signup_data())

        self.assertIn("email", response.context["form"].errors)
        self.assertEqual(User.objects.count(), 1)


class LoginLogoutTests(TestCase):
    """Tests de la connexion et de la déconnexion."""

    def setUp(self) -> None:
        """Crée un utilisateur de test."""
        self.user = User.objects.create_user("alice", "alice@example.com", PASSWORD)

    def test_login_with_valid_credentials(self) -> None:
        """Des identifiants valides connectent l'utilisateur."""
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "alice", "password": PASSWORD},
        )

        self.assertRedirects(response, reverse("dreams:list"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_with_wrong_password_is_refused(self) -> None:
        """Un mauvais mot de passe ne connecte pas l'utilisateur."""
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "alice", "password": "mauvais"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout(self) -> None:
        """La déconnexion ferme la session et renvoie vers la connexion."""
        self.client.force_login(self.user)

        response = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", self.client.session)
