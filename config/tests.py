"""Tests de la page d'accueil, de la mise en page et des réglages de production."""

import os
import subprocess
import sys
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.utils import get_random_secret_key
from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase, override_settings
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


class ProductionSettingsTests(SimpleTestCase):
    """Les réglages de production passent la vérification de sécurité de Django."""

    def run_manage(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        """Lance une commande manage.py avec des variables d'environnement.

        Les réglages sont lus au démarrage de Django : pour tester ceux de la
        production, il faut donc un nouveau processus.

        Args:
            *args: La commande et ses options.
            **env: Les variables d'environnement à ajouter.

        Returns:
            Le résultat de la commande.
        """
        return subprocess.run(
            [sys.executable, "manage.py", *args],
            cwd=settings.BASE_DIR,
            env={**os.environ, **env},
            capture_output=True,
            text=True,
            check=False,
        )

    def test_check_deploy_passes_on_render(self) -> None:
        """`check --deploy` ne signale aucun problème avec les réglages de Render."""
        result = self.run_manage(
            "check",
            "--deploy",
            "--fail-level",
            "WARNING",
            SECRET_KEY=get_random_secret_key(),
            DEBUG="False",
            RENDER_EXTERNAL_HOSTNAME="synthetiseur.onrender.com",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_render_hostname_is_allowed(self) -> None:
        """L'adresse fournie par Render est autorisée, en https pour les formulaires."""
        result = self.run_manage(
            "shell",
            "-c",
            "from django.conf import settings; "
            "print(settings.ALLOWED_HOSTS, settings.CSRF_TRUSTED_ORIGINS)",
            SECRET_KEY=get_random_secret_key(),
            DEBUG="False",
            RENDER_EXTERNAL_HOSTNAME="synthetiseur.onrender.com",
        )

        self.assertIn("'synthetiseur.onrender.com'", result.stdout)
        self.assertIn("'https://synthetiseur.onrender.com'", result.stdout)


class HealthTests(TestCase):
    """Tests de l'endpoint `/health`."""

    def test_health_is_public_and_ok(self) -> None:
        """`/health` répond sans connexion, avec l'état de la base."""
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["database"], "ok")

    @override_settings(GROQ_API_KEY="cle-tres-secrete", REPLICATE_API_TOKEN="")
    def test_health_never_shows_api_keys(self) -> None:
        """`/health` dit si une clé est configurée, sans jamais l'afficher."""
        response = self.client.get("/health")

        self.assertEqual(response.json()["services"]["groq"], True)
        self.assertEqual(response.json()["services"]["replicate"], False)
        self.assertNotContains(response, "cle-tres-secrete")

    def test_health_reports_database_failure(self) -> None:
        """Si la base ne répond pas, `/health` renvoie une erreur 503."""
        with patch("config.views.connection.cursor", side_effect=DatabaseError):
            response = self.client.get("/health")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "error")
