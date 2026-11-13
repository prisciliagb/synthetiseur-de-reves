"""Tests de l'analyse du rêve : émotion et prompt d'image.

Groq n'est jamais appelé pour de vrai : `httpx.post` est remplacé par un faux
(« mock ») qui renvoie la réponse voulue.
"""

import json
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, TestCase, override_settings

from .models import Dream
from .services.analysis import (
    GROQ_CHAT_URL,
    AnalysisError,
    DreamAnalysis,
    analyze_dream,
    parse_analysis,
)


def llm_response(content: str, status_code: int = 200) -> httpx.Response:
    """Fabrique une fausse réponse du LLM de Groq.

    Args:
        content: Le texte écrit par le LLM.
        status_code: Code HTTP de la réponse.

    Returns:
        La réponse HTTP simulée.
    """
    request = httpx.Request("POST", GROQ_CHAT_URL)
    body = {"choices": [{"message": {"content": content}}]}
    return httpx.Response(status_code, json=body, request=request)


class ParseAnalysisTests(SimpleTestCase):
    """Validation de la réponse JSON du LLM."""

    def test_valid_answer_is_kept(self) -> None:
        """Une réponse correcte est gardée telle quelle."""
        analysis = parse_analysis(
            json.dumps(
                {
                    "emotion": "strange",
                    "confidence": 0.82,
                    "image_prompt": "  A floating city at night.  ",
                }
            )
        )

        self.assertEqual(
            analysis, DreamAnalysis("strange", 0.82, "A floating city at night.")
        )

    def test_every_emotion_of_the_list_is_accepted(self) -> None:
        """Toutes les émotions de la liste fixe sont acceptées."""
        for emotion in Dream.Emotion.values:
            with self.subTest(emotion=emotion):
                analysis = parse_analysis(json.dumps({"emotion": emotion}))

                self.assertEqual(analysis.emotion, emotion)

    def test_unknown_emotion_becomes_neutral(self) -> None:
        """Une émotion hors de la liste devient « neutre », sans confiance."""
        analysis = parse_analysis(
            json.dumps({"emotion": "joie intense", "confidence": 0.9})
        )

        self.assertEqual(analysis.emotion, Dream.Emotion.NEUTRAL)
        self.assertIsNone(analysis.confidence)

    def test_missing_emotion_becomes_neutral(self) -> None:
        """Une réponse sans émotion donne « neutre »."""
        analysis = parse_analysis(json.dumps({"image_prompt": "A cat."}))

        self.assertEqual(analysis.emotion, Dream.Emotion.NEUTRAL)
        self.assertEqual(analysis.image_prompt, "A cat.")

    def test_invalid_json_becomes_neutral(self) -> None:
        """Un texte qui n'est pas du JSON donne « neutre »."""
        for content in ("Ce rêve est joyeux !", "", "[1, 2]", "null"):
            with self.subTest(content=content):
                analysis = parse_analysis(content)

                self.assertEqual(analysis, DreamAnalysis("neutral", None, ""))

    def test_confidence_is_kept_between_0_and_1(self) -> None:
        """Une confiance hors de [0, 1] est ramenée dans les bornes."""
        for value, expected in ((1.7, 1.0), (-0.2, 0.0), (1, 1.0)):
            with self.subTest(value=value):
                analysis = parse_analysis(
                    json.dumps({"emotion": "happy", "confidence": value})
                )

                self.assertEqual(analysis.confidence, expected)

    def test_invalid_confidence_is_ignored(self) -> None:
        """Une confiance qui n'est pas un nombre devient None."""
        for value in ("élevée", None, True, [0.5]):
            with self.subTest(value=value):
                analysis = parse_analysis(
                    json.dumps({"emotion": "happy", "confidence": value})
                )

                self.assertIsNone(analysis.confidence)

    def test_image_prompt_must_be_text(self) -> None:
        """Un prompt d'image qui n'est pas du texte est ignoré."""
        analysis = parse_analysis(
            json.dumps({"emotion": "sad", "image_prompt": {"scene": "rain"}})
        )

        self.assertEqual(analysis.image_prompt, "")


@override_settings(GROQ_API_KEY="cle-de-test", GROQ_MAX_ATTEMPTS=3)
@patch("dreams.services.api.time.sleep")
@patch("dreams.services.analysis.httpx.post")
class AnalyzeDreamTests(TestCase):
    """Tests du service `analyze_dream()`."""

    def test_one_call_gives_emotion_and_image_prompt(self, post, sleep) -> None:
        """Un seul appel au LLM donne l'émotion et le prompt d'image."""
        post.return_value = llm_response(
            json.dumps(
                {
                    "emotion": "scary",
                    "confidence": 0.7,
                    "image_prompt": "A dark forest chasing a child.",
                }
            )
        )

        analysis = analyze_dream("Une forêt sombre me poursuivait.")

        self.assertEqual(post.call_count, 1)
        self.assertEqual(
            analysis, DreamAnalysis("scary", 0.7, "A dark forest chasing a child.")
        )

    def test_sends_dream_in_json_mode_with_api_key(self, post, sleep) -> None:
        """L'appel envoie le rêve, demande du JSON et a un délai maximal."""
        post.return_value = llm_response('{"emotion": "happy"}')

        analyze_dream("Je volais.")

        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer cle-de-test")
        self.assertEqual(kwargs["json"]["response_format"], {"type": "json_object"})
        self.assertEqual(kwargs["json"]["messages"][-1]["content"], "Je volais.")
        self.assertIn("timeout", kwargs)

    def test_prompt_lists_every_emotion_and_asks_english(self, post, sleep) -> None:
        """Les consignes listent toutes les émotions et demandent l'anglais."""
        post.return_value = llm_response('{"emotion": "happy"}')

        analyze_dream("Je volais.")

        system = post.call_args.kwargs["json"]["messages"][0]["content"]
        for emotion in Dream.Emotion.values:
            self.assertIn(f'"{emotion}"', system)
        self.assertIn("ANGLAIS", system)

    def test_retries_when_groq_is_overloaded(self, post, sleep) -> None:
        """Une surcharge temporaire de Groq est retentée."""
        post.side_effect = [
            llm_response("", status_code=503),
            llm_response('{"emotion": "sad"}'),
        ]

        self.assertEqual(analyze_dream("Je pleurais.").emotion, "sad")
        self.assertEqual(post.call_count, 2)

    def test_retries_after_timeout(self, post, sleep) -> None:
        """Après un délai dépassé, une nouvelle tentative est faite."""
        post.side_effect = [
            httpx.ReadTimeout("trop long"),
            llm_response('{"emotion": "scary"}'),
        ]

        self.assertEqual(analyze_dream("Je fuyais.").emotion, "scary")
        self.assertEqual(post.call_count, 2)

    def test_quota_exceeded_raises_analysis_error(self, post, sleep) -> None:
        """Quota dépassé (429 à chaque essai) : une AnalysisError est levée."""
        post.return_value = llm_response("", status_code=429)

        with self.assertRaises(AnalysisError):
            analyze_dream("Je volais.")

        self.assertEqual(post.call_count, 3)

    def test_groq_unavailable_raises_analysis_error(self, post, sleep) -> None:
        """Si Groq reste injoignable, une AnalysisError est levée."""
        post.side_effect = httpx.ConnectError("injoignable")

        with self.assertRaises(AnalysisError):
            analyze_dream("Je volais.")

    def test_unreadable_groq_response_becomes_neutral(self, post, sleep) -> None:
        """Une réponse de Groq sans le texte du LLM donne « neutre »."""
        post.return_value = httpx.Response(
            200, json={"inattendu": True}, request=httpx.Request("POST", "x")
        )

        self.assertEqual(analyze_dream("Je volais.").emotion, "neutral")
