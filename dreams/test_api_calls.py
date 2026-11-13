"""Tests du suivi des appels aux API : logs, coûts et admin (issue #21).

Aucune API n'est appelée pour de vrai : on donne à `call_api()` une fausse
fonction d'envoi qui renvoie la réponse voulue.
"""

import json
from decimal import Decimal
from unittest.mock import Mock, patch

import httpx
from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ApiCall
from .services.analysis import analysis_cost
from .services.api import ApiRefusedError, ApiUnavailableError, call_api
from .services.transcription import transcription_cost

User = get_user_model()


def response(status_code: int = 200, json_data: object = None) -> httpx.Response:
    """Fabrique une fausse réponse HTTP.

    Args:
        status_code: Code HTTP de la réponse.
        json_data: Contenu JSON de la réponse.

    Returns:
        La réponse HTTP simulée.
    """
    request = httpx.Request("POST", "https://api.example.com")
    return httpx.Response(status_code, json=json_data or {}, request=request)


def call(send: Mock, cost=None, api_key: str = "cle-de-test") -> httpx.Response:
    """Appelle `call_api()` avec des réglages de test (2 tentatives)."""
    return call_api(
        send,
        task="Analyse",
        api_key=api_key,
        max_attempts=2,
        service="Groq",
        cost=cost,
    )


@patch("dreams.services.api.time.sleep")
class CallTrackingTests(TestCase):
    """Chaque appel est enregistré, réussi ou non."""

    def test_successful_call_is_recorded_with_its_cost(self, sleep) -> None:
        """Un appel réussi est enregistré avec son service, sa durée et son coût."""
        send = Mock(return_value=response(200))

        call(send, cost=lambda _response: Decimal("0.0025"))

        api_call = ApiCall.objects.get()
        self.assertEqual(api_call.service, "Groq")
        self.assertEqual(api_call.task, "Analyse")
        self.assertTrue(api_call.success)
        self.assertEqual(api_call.http_status, 200)
        self.assertEqual(api_call.attempts, 1)
        self.assertGreaterEqual(api_call.duration_ms, 0)
        self.assertEqual(api_call.cost_usd, Decimal("0.0025"))

    def test_retried_call_counts_its_attempts(self, sleep) -> None:
        """Les nouvelles tentatives sont comptées dans le même enregistrement."""
        send = Mock(side_effect=[response(503), response(200)])

        call(send)

        api_call = ApiCall.objects.get()
        self.assertTrue(api_call.success)
        self.assertEqual(api_call.attempts, 2)

    def test_refused_call_is_recorded_as_failure_without_cost(self, sleep) -> None:
        """Un appel refusé est enregistré comme un échec, sans coût."""
        send = Mock(return_value=response(401))

        with self.assertRaises(ApiRefusedError):
            call(send, cost=lambda _response: Decimal("1"))

        api_call = ApiCall.objects.get()
        self.assertFalse(api_call.success)
        self.assertEqual(api_call.http_status, 401)
        self.assertEqual(api_call.cost_usd, Decimal(0))

    def test_abandoned_call_is_recorded_as_failure(self, sleep) -> None:
        """Un appel abandonné après toutes ses tentatives est un échec."""
        send = Mock(side_effect=httpx.ConnectError("injoignable"))

        with self.assertRaises(ApiUnavailableError):
            call(send)

        api_call = ApiCall.objects.get()
        self.assertFalse(api_call.success)
        self.assertEqual(api_call.attempts, 2)
        self.assertIsNone(api_call.http_status)

    def test_missing_key_is_recorded_with_zero_attempt(self, sleep) -> None:
        """Sans clé, l'API n'est pas appelée, mais l'échec est tracé."""
        send = Mock()

        with self.assertRaises(ApiUnavailableError):
            call(send, api_key="")

        send.assert_not_called()
        self.assertEqual(ApiCall.objects.get().attempts, 0)

    def test_cost_error_never_breaks_the_call(self, sleep) -> None:
        """Si le coût est incalculable, l'appel réussit quand même (coût 0)."""
        send = Mock(return_value=response(200))

        result = call(send, cost=Mock(side_effect=KeyError("usage")))

        self.assertEqual(result.status_code, 200)
        self.assertEqual(ApiCall.objects.get().cost_usd, Decimal(0))

    def test_database_error_never_breaks_the_call(self, sleep) -> None:
        """Si l'enregistrement en base échoue, l'appel réussit quand même."""
        send = Mock(return_value=response(200))

        with patch.object(ApiCall.objects, "create", side_effect=DatabaseError):
            result = call(send)

        self.assertEqual(result.status_code, 200)

    def test_each_call_writes_one_structured_log_line(self, sleep) -> None:
        """Chaque appel écrit une ligne de log JSON lisible par un outil."""
        send = Mock(return_value=response(200))

        with self.assertLogs("dreams.services.api", level="INFO") as logs:
            call(send, cost=lambda _response: Decimal("0.5"))

        line = next(message for message in logs.output if "Appel API" in message)
        entry = json.loads(line.split("Appel API ", 1)[1])
        self.assertEqual(entry["service"], "Groq")
        self.assertEqual(entry["task"], "Analyse")
        self.assertTrue(entry["success"])
        self.assertEqual(entry["cost_usd"], "0.500000")
        self.assertIn("duration_ms", entry)


@override_settings(
    GROQ_WHISPER_PRICE_PER_HOUR=Decimal("0.04"),
    GROQ_LLM_PRICE_INPUT_PER_MILLION=Decimal("0.10"),
    GROQ_LLM_PRICE_OUTPUT_PER_MILLION=Decimal("0.50"),
)
class CostEstimateTests(TestCase):
    """Calcul du coût estimé de chaque type d'appel."""

    def test_transcription_cost_depends_on_audio_duration(self) -> None:
        """Une minute d'audio coûte 1/60 du prix horaire."""
        cost = transcription_cost(response(json_data={"duration": 60}))

        self.assertAlmostEqual(cost, Decimal("0.04") / 60)

    def test_short_audio_is_billed_ten_seconds(self) -> None:
        """Un audio de 3 secondes est facturé comme 10 secondes (minimum)."""
        cost = transcription_cost(response(json_data={"duration": 3}))

        self.assertAlmostEqual(cost, Decimal("0.04") * 10 / 3600)

    def test_analysis_cost_depends_on_tokens(self) -> None:
        """Le coût de l'analyse dépend des jetons lus et écrits."""
        usage = {"prompt_tokens": 1_000_000, "completion_tokens": 2_000_000}

        cost = analysis_cost(response(json_data={"usage": usage}))

        self.assertEqual(cost, Decimal("0.10") + 2 * Decimal("0.50"))


class ApiCallAdminTests(TestCase):
    """Consultation des appels et du coût cumulé dans l'admin."""

    def setUp(self) -> None:
        """Connecte un administrateur et crée trois appels."""
        admin = User.objects.create_superuser("admin", "admin@example.com", "mdp")
        self.client.force_login(admin)
        self.url = reverse("admin:dreams_apicall_changelist")
        for service, success, cost in [
            ("Groq", True, "0.001"),
            ("Replicate", True, "0.003"),
            ("Replicate", False, "0"),
        ]:
            ApiCall.objects.create(
                service=service,
                task="Test",
                success=success,
                attempts=1,
                duration_ms=1000,
                cost_usd=Decimal(cost),
            )

    def test_admin_shows_total_estimated_cost(self) -> None:
        """L'admin affiche le coût cumulé, le nombre d'appels et les échecs."""
        response = self.client.get(self.url)

        self.assertContains(response, "Coût estimé : 0,0040 $")
        self.assertContains(response, "3 appels")
        self.assertContains(response, "1 échec (33 %)")

    def test_summary_follows_filters(self) -> None:
        """Le résumé ne compte que les appels filtrés."""
        response = self.client.get(self.url, {"service": "Groq"})

        self.assertContains(response, "Coût estimé : 0,0010 $")
        self.assertContains(response, "1 appel ")

    def test_calls_cannot_be_added_or_changed(self) -> None:
        """Les appels se consultent, mais ne se créent ni ne se modifient."""
        add = self.client.get(reverse("admin:dreams_apicall_add"))

        self.assertEqual(add.status_code, 403)
