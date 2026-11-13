"""Tests des statistiques : calculs (service) et page « Statistiques »."""

import json
from datetime import date, datetime, time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Dream
from .services.stats import compute_stats

User = get_user_model()


class StatsTestMixin:
    """Crée des rêves datés pour les tests."""

    def setUp(self) -> None:
        """Crée un utilisateur."""
        super().setUp()
        self.user = User.objects.create_user("alice", "alice@example.com")

    def create_dream(self, day: date, emotion: str = "", user=None) -> Dream:
        """Crée un rêve daté de `day` à 8 h (heure de Paris).

        Args:
            day: Le jour du rêve.
            emotion: L'émotion du rêve (vide : pas encore analysé).
            user: Le propriétaire (par défaut, Alice).

        Returns:
            Le rêve créé.
        """
        dream = Dream.objects.create(user=user or self.user, emotion=emotion)
        created_at = timezone.make_aware(datetime.combine(day, time(8)))
        Dream.objects.filter(pk=dream.pk).update(created_at=created_at)
        return dream


class ComputeStatsTests(StatsTestMixin, TestCase):
    """Tests du calcul des statistiques."""

    def stats(self):
        """Calcule les statistiques des rêves d'Alice."""
        return compute_stats(Dream.objects.filter(user=self.user))

    def test_no_dream(self) -> None:
        """Sans rêve, tout est à zéro et il n'y a pas d'émotion dominante."""
        stats = self.stats()

        self.assertEqual(stats.total, 0)
        self.assertEqual(stats.weeks, [])
        self.assertEqual(stats.dominant, [])

    def test_dreams_are_counted_per_week_with_empty_weeks(self) -> None:
        """Chaque semaine (du lundi) a son total, semaines vides comprises."""
        self.create_dream(date(2026, 11, 2))  # lundi
        self.create_dream(date(2026, 11, 8))  # dimanche, même semaine
        self.create_dream(date(2026, 11, 18))  # deux semaines plus tard

        weeks = self.stats().weeks

        self.assertEqual(
            weeks,
            [(date(2026, 11, 2), 2), (date(2026, 11, 9), 0), (date(2026, 11, 16), 1)],
        )

    def test_emotions_are_sorted_from_most_frequent(self) -> None:
        """Les émotions sont triées de la plus fréquente à la moins fréquente."""
        self.create_dream(date(2026, 11, 2), "sad")
        self.create_dream(date(2026, 11, 3), "scary")
        self.create_dream(date(2026, 11, 4), "scary")

        emotions = self.stats().emotions

        self.assertEqual([e.value for e in emotions[:2]], ["scary", "sad"])
        self.assertEqual(len(emotions), len(Dream.Emotion.choices))
        self.assertEqual(emotions[0].percent, 67)

    def test_dominant_emotion(self) -> None:
        """L'émotion la plus fréquente est l'émotion dominante."""
        self.create_dream(date(2026, 11, 2), "happy")
        self.create_dream(date(2026, 11, 3), "scary")
        self.create_dream(date(2026, 11, 4), "scary")

        dominant = self.stats().dominant

        self.assertEqual([e.value for e in dominant], ["scary"])

    def test_tie_gives_several_dominant_emotions(self) -> None:
        """En cas d'égalité, toutes les émotions à égalité sont dominantes."""
        self.create_dream(date(2026, 11, 2), "happy")
        self.create_dream(date(2026, 11, 3), "sad")

        dominant = self.stats().dominant

        self.assertEqual({e.value for e in dominant}, {"happy", "sad"})

    def test_dreams_not_analyzed_are_not_in_emotions(self) -> None:
        """Un rêve sans émotion compte dans le total, pas dans les émotions."""
        self.create_dream(date(2026, 11, 2))
        self.create_dream(date(2026, 11, 3), "sad")

        stats = self.stats()

        self.assertEqual(stats.total, 2)
        self.assertEqual(stats.analyzed, 1)
        self.assertEqual(stats.dominant[0].percent, 100)


class StatsPageTests(StatsTestMixin, TestCase):
    """Tests de la page « Statistiques »."""

    def setUp(self) -> None:
        """Connecte Alice."""
        super().setUp()
        self.client.force_login(self.user)
        self.url = reverse("dreams:stats")

    def chart_data(self, response) -> dict:
        """Lit les données transmises aux graphiques."""
        return response.context["chart_data"]

    def test_anonymous_user_is_redirected_to_login(self) -> None:
        """Un visiteur non connecté est renvoyé vers la connexion."""
        self.client.logout()

        response = self.client.get(self.url)

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={self.url}")

    def test_page_is_in_navigation(self) -> None:
        """Le lien « Statistiques » est dans la barre de navigation."""
        response = self.client.get(reverse("dreams:list"))

        self.assertContains(response, f'href="{self.url}"')

    def test_page_shows_dominant_emotion_and_charts(self) -> None:
        """La page affiche l'émotion dominante et les données des graphiques."""
        self.create_dream(date(2026, 11, 2), "scary")
        self.create_dream(date(2026, 11, 3), "scary")
        self.create_dream(date(2026, 11, 10), "happy")

        response = self.client.get(self.url)

        self.assertContains(response, "Effrayant")
        self.assertContains(response, 'id="stats-data"')
        data = self.chart_data(response)
        self.assertEqual(data["weeks"]["counts"], [2, 1])
        self.assertEqual(data["emotions"]["labels"][0], "Effrayant")
        self.assertEqual(data["emotions"]["dominant"][:2], [True, False])

    def test_chart_data_is_valid_json_in_page(self) -> None:
        """Les données sont écrites dans la page en JSON lisible par le JS."""
        self.create_dream(date(2026, 11, 2), "sad")

        response = self.client.get(self.url)

        content = response.content.decode()
        start = content.index('id="stats-data" type="application/json">') + 40
        end = content.index("</script>", start)
        self.assertEqual(json.loads(content[start:end]), self.chart_data(response))

    def test_filters_apply_to_stats(self) -> None:
        """Les filtres de période et d'émotion s'appliquent aux graphiques."""
        self.create_dream(date(2026, 10, 5), "scary")
        self.create_dream(date(2026, 11, 2), "happy")
        self.create_dream(date(2026, 11, 3), "scary")

        response = self.client.get(
            self.url, {"start": "2026-11-01", "end": "2026-11-30"}
        )

        stats = response.context["stats"]
        self.assertEqual(stats.total, 2)
        self.assertEqual(self.chart_data(response)["weeks"]["labels"], ["02/11"])

    def test_only_own_dreams_are_counted(self) -> None:
        """Les rêves des autres utilisateurs ne sont jamais comptés."""
        bob = User.objects.create_user("bob", "bob@example.com")
        self.create_dream(date(2026, 11, 2), "sad", user=bob)
        self.create_dream(date(2026, 11, 2), "happy")

        stats = self.client.get(self.url).context["stats"]

        self.assertEqual(stats.total, 1)
        self.assertEqual([e.value for e in stats.dominant], ["happy"])

    def test_no_dream_shows_invitation(self) -> None:
        """Sans rêve, la page invite à en raconter un, sans graphique."""
        response = self.client.get(self.url)

        self.assertContains(response, "après votre premier rêve")
        self.assertNotContains(response, "chart-weeks")

    def test_no_result_with_filters_shows_message(self) -> None:
        """Si aucun rêve ne correspond aux filtres, la page l'indique."""
        self.create_dream(date(2026, 11, 2), "sad")

        response = self.client.get(self.url, {"emotion": "happy"})

        self.assertContains(response, "Aucun rêve ne correspond à ces filtres.")
        self.assertNotContains(response, "chart-weeks")
