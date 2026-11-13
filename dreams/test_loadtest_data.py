"""Tests de la commande qui prépare les données du test de charge."""

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from .models import Dream

User = get_user_model()


class LoadTestDataTests(TestCase):
    """Tests de `manage.py donnees_test_de_charge`."""

    def run_command(self, *args: str) -> str:
        """Lance la commande et renvoie ce qu'elle affiche."""
        output = StringIO()
        call_command("donnees_test_de_charge", *args, stdout=output, stderr=output)
        return output.getvalue()

    def test_creates_accounts_with_dreams(self) -> None:
        """La commande crée les comptes « charge-… » et leurs rêves analysés."""
        self.run_command("--comptes", "3", "--reves", "5", "--mot-de-passe", "mdp-test")

        users = User.objects.filter(username__startswith="charge-")
        self.assertEqual(users.count(), 3)
        self.assertTrue(users.get(username="charge-01").check_password("mdp-test"))
        self.assertEqual(Dream.objects.count(), 15)
        self.assertFalse(Dream.objects.filter(emotion="").exists())

    def test_password_is_required(self) -> None:
        """Sans mot de passe, rien n'est créé."""
        output = self.run_command("--comptes", "2")

        self.assertIn("mot de passe", output)
        self.assertFalse(User.objects.exists())

    def test_delete_only_removes_load_test_accounts(self) -> None:
        """--supprimer efface les comptes de test, jamais les vrais comptes."""
        real_user = User.objects.create_user("alice", "alice@example.com")
        Dream.objects.create(user=real_user)
        self.run_command("--comptes", "2", "--reves", "3", "--mot-de-passe", "mdp")

        self.run_command("--supprimer")

        self.assertEqual(list(User.objects.all()), [real_user])
        self.assertEqual(Dream.objects.count(), 1)
