"""Crée (ou supprime) les comptes et les rêves utilisés par le test de charge.

Aucune API n'est appelée : les rêves sont fabriqués directement en base, avec
une transcription et une émotion déjà remplies.

Exemples :
    python manage.py donnees_test_de_charge --mot-de-passe <mdp>
    python manage.py donnees_test_de_charge --supprimer
"""

import random
from datetime import timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.utils import timezone

from dreams.models import Dream

User = get_user_model()

# Tous les comptes du test de charge commencent par ce préfixe : on peut ainsi
# les supprimer sans toucher aux vrais comptes.
PREFIX = "charge-"

SAMPLE_DREAMS = [
    "Je volais au-dessus d'une ville inconnue, les toits brillaient au soleil.",
    "J'étais en retard à un examen et je ne trouvais pas la salle.",
    "Une maison flottait sur la mer, et toutes ses fenêtres étaient allumées.",
    "Je marchais seule dans une forêt, j'entendais des pas derrière moi.",
    "Je retrouvais des amis d'enfance dans un jardin plein de fleurs.",
    "Les trains de la gare roulaient au plafond et personne ne s'en étonnait.",
]


class Command(BaseCommand):
    """Données du test de charge (docs/test-de-charge.md)."""

    help = "Crée ou supprime les comptes « charge-… » et leurs rêves."

    def add_arguments(self, parser: CommandParser) -> None:
        """Déclare les options de la commande."""
        parser.add_argument("--comptes", type=int, default=20)
        parser.add_argument("--reves", type=int, default=30)
        parser.add_argument("--mot-de-passe", dest="password")
        parser.add_argument("--supprimer", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        """Crée les données, ou les supprime avec --supprimer."""
        deleted, _ = User.objects.filter(username__startswith=PREFIX).delete()
        if options["supprimer"]:
            self.stdout.write(f"Données du test de charge supprimées ({deleted}).")
            return
        if not options["password"]:
            self.stderr.write("Indiquez un mot de passe : --mot-de-passe <mdp>")
            return

        with transaction.atomic():
            for number in range(1, options["comptes"] + 1):
                self._create_user(number, options["password"], options["reves"])
        self.stdout.write(
            f"{options['comptes']} comptes créés, avec {options['reves']} rêves chacun."
        )

    def _create_user(self, number: int, password: str, dream_count: int) -> None:
        """Crée un compte de test et ses rêves, répartis sur 60 jours.

        Args:
            number: Numéro du compte (charge-01, charge-02…).
            password: Mot de passe du compte.
            dream_count: Nombre de rêves à créer.
        """
        user = User.objects.create_user(
            f"{PREFIX}{number:02d}",
            f"{PREFIX}{number:02d}@example.com",
            password,
            rgpd_consent_at=timezone.now(),
        )
        dreams = Dream.objects.bulk_create(
            Dream(
                user=user,
                transcription=random.choice(SAMPLE_DREAMS),
                emotion=random.choice(Dream.Emotion.values),
                confidence=round(random.uniform(0.5, 1), 2),
                status=Dream.Status.DONE,
            )
            for _ in range(dream_count)
        )
        # created_at est rempli automatiquement : on le change après coup pour
        # avoir des rêves sur plusieurs semaines (statistiques, filtres).
        now = timezone.now()
        for dream in dreams:
            Dream.objects.filter(pk=dream.pk).update(
                created_at=now - timedelta(days=random.randint(0, 60))
            )
