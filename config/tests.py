"""Tests de la page d'accueil et de la mise en page commune."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class HomePageTests(TestCase):
    """Tests de la page d'accueil."""

    def setUp(self) -> None:
        """Prépare l'adresse de la page d'accueil."""
        self.url = reverse("home")

    def test_visitor_can_see_home_page(self) -> None:
        """La page d'accueil est visible sans être connecté."""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "home.html")
        self.assertContains(response, "Synthétiseur de rêves")

    def test_home_page_shows_the_four_steps(self) -> None:
        """La page présente les 4 étapes du parcours."""
        response = self.client.get(self.url)

        for step in ["Enregistrez", "Découvrez", "Visualisez", "Explorez"]:
            self.assertContains(response, f"<strong>{step}</strong>")

    def test_visitor_is_invited_to_sign_up_or_log_in(self) -> None:
        """Un visiteur voit « Créer un compte » et « Se connecter »."""
        response = self.client.get(self.url)

        self.assertContains(response, f'href="{reverse("accounts:signup")}"')
        self.assertContains(response, f'href="{reverse("accounts:login")}"')
        self.assertNotContains(response, f'href="{reverse("dreams:record")}"')

    def test_logged_in_user_can_tell_a_dream(self) -> None:
        """Un utilisateur connecté voit le bouton « Raconter un rêve »."""
        user = User.objects.create_user("alice", "alice@example.com")
        self.client.force_login(user)

        response = self.client.get(self.url)

        self.assertContains(response, f'href="{reverse("dreams:record")}"')
        self.assertNotContains(response, f'href="{reverse("accounts:signup")}"')


class LayoutTests(TestCase):
    """Tests de la mise en page commune (base.html)."""

    def test_theme_and_logo_are_loaded(self) -> None:
        """Toutes les pages chargent le thème et le logo."""
        response = self.client.get(reverse("home"))

        self.assertContains(response, "css/theme.css")
        self.assertContains(response, 'class="dv-logo"')

    def test_current_page_is_highlighted_in_navigation(self) -> None:
        """Le lien de la page en cours est marqué dans la navigation."""
        user = User.objects.create_user("alice", "alice@example.com")
        self.client.force_login(user)

        stats_url = reverse("dreams:stats")

        response = self.client.get(stats_url)

        self.assertContains(
            response, f'class="nav-link active" href="{stats_url}" aria-current="page"'
        )
