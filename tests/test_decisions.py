"""Tests for triage_router.decisions: DecisionProvider, FakeDecisionProvider."""
import os
import socket
import unittest
from unittest import mock

import httpx

from triage_router.decisions import (
    FakeDecisionProvider,
    OpenRouterJevProvider,
    ProviderError,
)
from triage_router.intake import build_state, load_tickets

DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "synthetic", "support_tickets_synth_v1.jsonl"
)

ROUTE_ENUM = {"billing", "technical_bug", "escalation", "faq"}
LEGEND_KEYS = {"0", "1", "2", "3", "4"}
NOUL_QUESTIONS = [
    "is_churn_risk",
    "is_payment_issue",
    "is_credential_exposure",
    "is_urgent_deadline",
    "is_how_to_question",
]


def _states():
    tickets = load_tickets(DATA_PATH)
    return {t["ticket_id"]: build_state(t) for t in tickets}


class TestFakeDecisionProviderShape(unittest.TestCase):
    def setUp(self):
        self.provider = FakeDecisionProvider()
        self.states = _states()

    def test_loads_24_states(self):
        self.assertEqual(len(self.states), 24)

    def test_no_expected_leaks_into_state(self):
        for state in self.states.values():
            self.assertNotIn("expected", state)

    def test_all_states_produce_valid_answers(self):
        for ticket_id, state in self.states.items():
            answers = self.provider.decide(state)
            with self.subTest(ticket_id=ticket_id):
                self._assert_valid_shape(answers)

    def _assert_valid_shape(self, answers):
        self.assertIn("route", answers)
        self.assertIn(answers["route"]["value"], ROUTE_ENUM)
        conf = answers["route"]["confidence"]
        self.assertIsInstance(conf, float)
        self.assertGreaterEqual(conf, 0.0)
        self.assertLessEqual(conf, 1.0)

        self.assertIn("severity", answers)
        score = answers["severity"]["score"]
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
        legend = answers["severity"]["legend"]
        self.assertEqual(set(legend.keys()), LEGEND_KEYS)
        for entry in legend.values():
            self.assertIn("what", entry)
            self.assertIn("signals", entry)
            self.assertIsInstance(entry["signals"], list)

        for q in NOUL_QUESTIONS:
            self.assertIn(q, answers)
            val = answers[q]["value"]
            conf_q = answers[q]["confidence"]
            self.assertIsInstance(val, float)
            self.assertIsInstance(conf_q, float)
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 1.0)
            self.assertGreaterEqual(conf_q, 0.0)
            self.assertLessEqual(conf_q, 1.0)

    def test_deterministic_bit_for_bit(self):
        for ticket_id, state in self.states.items():
            with self.subTest(ticket_id=ticket_id):
                a = self.provider.decide(state)
                b = self.provider.decide(state)
                self.assertEqual(a, b)

    def test_deterministic_across_provider_instances(self):
        p2 = FakeDecisionProvider()
        for state in self.states.values():
            self.assertEqual(self.provider.decide(state), p2.decide(state))

    def test_tck_0024_low_confidence(self):
        state = self.states["TCK-0024"]
        answers = self.provider.decide(state)
        self.assertLessEqual(answers["route"]["confidence"], 0.4)

    def test_tck_0009_not_flagged_credential_exposure(self):
        state = self.states["TCK-0009"]
        answers = self.provider.decide(state)
        self.assertLess(answers["is_credential_exposure"]["value"], 0.5)

    def test_tck_0009_routes_technical_bug(self):
        state = self.states["TCK-0009"]
        answers = self.provider.decide(state)
        self.assertEqual(answers["route"]["value"], "technical_bug")
        self.assertGreaterEqual(answers["route"]["confidence"], 0.75)

    def test_tck_0001_routes_billing_with_high_confidence(self):
        state = self.states["TCK-0001"]
        answers = self.provider.decide(state)
        self.assertEqual(answers["route"]["value"], "billing")
        self.assertGreaterEqual(answers["route"]["confidence"], 0.75)

    def test_empty_state_is_defensive(self):
        answers = self.provider.decide({})
        self._assert_valid_shape(answers)


class _NoNetwork(unittest.TestCase):
    """Base class that trips loudly if any test tries a real socket connect."""

    def setUp(self):
        patcher = mock.patch.object(
            socket.socket,
            "connect",
            side_effect=AssertionError("real network call attempted in test"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class TestOpenRouterJevProviderRequest(_NoNetwork):
    def setUp(self):
        super().setUp()
        self.env_patcher = mock.patch.dict(
            os.environ, {"OPENROUTER_API_KEY": "test-fake-token-value-not-real"}
        )
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)
        self.state = {
            "keyword_hits": ["refund", "charge"],
            "has_stack_trace": True,
            "subject_len": 12,
            "body_chars": 300,
        }

    def _make_provider(self, handler):
        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        return OpenRouterJevProvider(client=client)

    def test_posts_to_expected_url_with_auth_header(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["request"] = request
            return httpx.Response(200, json={"answers": {}})

        provider = self._make_provider(handler)
        provider.decide(self.state)

        request = captured["request"]
        self.assertEqual(str(request.url), "https://openrouter.ai/api/alpha/decisions")
        self.assertEqual(request.method, "POST")
        auth = request.headers.get("authorization")
        self.assertIsNotNone(auth)
        self.assertTrue(auth.startswith("Bearer "))
        # Token value is never asserted literally; only structural presence.

    def test_payload_shape_contract(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = httpx_json(request)
            return httpx.Response(200, json={"answers": {}})

        provider = self._make_provider(handler)
        provider.decide(self.state)

        payload = captured["payload"]
        self.assertEqual(payload["model"], "typesafe/jev-1.13")
        self.assertEqual(payload["state"], self.state)
        questions = payload["questions"]

        # route: choice question, instructions not text, criteria is a record
        route_q = questions["route"]
        self.assertEqual(route_q["type"], "choice")
        self.assertIn("instructions", route_q)
        self.assertNotIn("text", route_q)
        self.assertIsInstance(route_q["criteria"], dict)
        self.assertNotIn("options", route_q)
        self.assertEqual(
            set(route_q["criteria"].keys()),
            {"billing", "technical_bug", "escalation", "faq"},
        )
        for desc in route_q["criteria"].values():
            self.assertIsInstance(desc, str)

        # severity: score question, criteria is an array of 4-ish level objs
        severity_q = questions["severity"]
        self.assertEqual(severity_q["type"], "score")
        self.assertIn("instructions", severity_q)
        self.assertIsInstance(severity_q["criteria"], list)
        for level in severity_q["criteria"]:
            self.assertIn("what", level)

        # noul questions: type noul, criteria is a record with true/false
        for name in [
            "is_churn_risk",
            "is_payment_issue",
            "is_credential_exposure",
            "is_urgent_deadline",
            "is_how_to_question",
        ]:
            q = questions[name]
            self.assertEqual(q["type"], "noul")
            self.assertIn("instructions", q)
            self.assertNotIn("text", q)
            self.assertIsInstance(q["criteria"], dict)
            self.assertEqual(set(q["criteria"].keys()), {"true", "false"})
            for entry in q["criteria"].values():
                self.assertIn("what", entry)

    def test_missing_api_key_raises_clear_error(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            transport = httpx.MockTransport(
                lambda r: httpx.Response(200, json={"answers": {}})
            )
            provider = OpenRouterJevProvider(client=httpx.Client(transport=transport))
            with self.assertRaises(ProviderError) as ctx:
                provider.decide(self.state)
            self.assertIn("OPENROUTER_API_KEY", str(ctx.exception))

    def test_retries_on_connect_error_then_succeeds(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise httpx.ConnectError("boom", request=request)
            return httpx.Response(200, json={"answers": {}})

        provider = self._make_provider(handler)
        with mock.patch("time.sleep", return_value=None):
            result = provider.decide(self.state)
        self.assertEqual(attempts["n"], 3)
        self.assertEqual(result, {})

    def test_does_not_retry_on_4xx(self):
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            return httpx.Response(400, json={"error": "bad request"})

        provider = self._make_provider(handler)
        with self.assertRaises(ProviderError) as ctx:
            provider.decide(self.state)
        self.assertEqual(attempts["n"], 1)
        self.assertIsInstance(ctx.exception.__cause__, httpx.HTTPStatusError)
        self.assertIn("unknown", str(ctx.exception))

    def test_4xx_error_names_ticket_id(self):
        state = dict(self.state)
        state["ticket"] = {"id": "TCK-0042"}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "bad request"})

        provider = self._make_provider(handler)
        with self.assertRaises(ProviderError) as ctx:
            provider.decide(state)
        self.assertIn("TCK-0042", str(ctx.exception))
        self.assertNotIn("test-fake-token-value-not-real", str(ctx.exception))

    def test_exhausts_retries_and_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timeout", request=request)

        state = dict(self.state)
        state["ticket"] = {"id": "TCK-0099"}

        provider = self._make_provider(handler)
        with mock.patch("time.sleep", return_value=None), self.assertRaises(ProviderError) as ctx:
            provider.decide(state)
        self.assertIsInstance(ctx.exception.__cause__, httpx.ConnectTimeout)
        self.assertIn("TCK-0099", str(ctx.exception))
        self.assertNotIn("test-fake-token-value-not-real", str(ctx.exception))

    def test_retry_logs_warning_without_sensitive_data(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        provider = self._make_provider(handler)
        with mock.patch("time.sleep", return_value=None), \
                self.assertLogs("triage_router.decisions", level="WARNING") as log_ctx, \
                self.assertRaises(ProviderError):
            provider.decide(self.state)
        joined = "\n".join(log_ctx.output)
        self.assertIn("attempt", joined.lower())
        self.assertNotIn("test-fake-token-value-not-real", joined)
        self.assertNotIn("Authorization", joined)

    def test_injected_client_is_not_closed_by_close(self):
        client = httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"answers": {}})
        ))
        provider = OpenRouterJevProvider(client=client)
        provider.close()
        self.assertFalse(client.is_closed)
        client.close()

    def test_self_created_client_is_closed_by_close(self):
        provider = OpenRouterJevProvider()
        provider.close()
        self.assertTrue(provider._client.is_closed)

    def test_context_manager_closes_self_created_client_only(self):
        with OpenRouterJevProvider() as provider:
            pass
        self.assertTrue(provider._client.is_closed)

        client = httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"answers": {}})
        ))
        with OpenRouterJevProvider(client=client):
            pass
        self.assertFalse(client.is_closed)
        client.close()


def httpx_json(request: httpx.Request) -> dict:
    import json

    return json.loads(request.content.decode("utf-8"))


class TestOpenRouterJevProviderParseAnswers(unittest.TestCase):
    def setUp(self):
        transport = httpx.MockTransport(
            lambda r: httpx.Response(200, json={"answers": {}})
        )
        self.provider = OpenRouterJevProvider(client=httpx.Client(transport=transport))

    def test_parses_good_response(self):
        response = {
            "answers": {
                "route": {"value": "billing", "confidence": 0.9},
                "severity": {"score": 0.85},
                "is_churn_risk": {"value": 1.0, "confidence": 0.8},
                "is_payment_issue": {"value": 1.0, "confidence": 0.9},
                "is_credential_exposure": {"value": 0.0, "confidence": 0.9},
                "is_urgent_deadline": {"value": 0.0, "confidence": 0.3},
                "is_how_to_question": {"value": 0.0, "confidence": 0.3},
            }
        }
        result = self.provider.parse_answers(response)
        self.assertEqual(result["route"]["value"], "billing")
        # score 0.85 -> bucket = min(4, floor(0.85*5)) = min(4,4) = 4 -> critical
        self.assertEqual(result["severity"]["priority"], "critical")
        self.assertEqual(result["is_churn_risk"]["value"], 1.0)

    def test_missing_answer_field_is_failed_only_for_that_question(self):
        response = {
            "answers": {
                "route": {"value": "billing", "confidence": 0.9},
                # severity missing entirely
                "is_churn_risk": {"value": 1.0, "confidence": 0.8},
            }
        }
        result = self.provider.parse_answers(response)
        self.assertEqual(result["route"]["value"], "billing")
        self.assertIsNone(result.get("severity"))
        self.assertEqual(result["is_churn_risk"]["value"], 1.0)

    def test_score_five_bucket_legend_correct_priority(self):
        for score, expected in [(0.05, "low"), (0.25, "low"), (0.45, "medium"),
                                 (0.65, "high"), (0.95, "critical")]:
            response = {"answers": {"severity": {"score": score}}}
            result = self.provider.parse_answers(response)
            with self.subTest(score=score):
                self.assertEqual(result["severity"]["priority"], expected)

    def test_malformed_legend_label_yields_failed_severity(self):
        # Monkeypatch the legend lookup indirectly: use a score whose bucket
        # would map outside the allowed label set by corrupting the provider
        # legend for this instance.
        original_legend = self.provider.SEVERITY_LEGEND
        try:
            self.provider.SEVERITY_LEGEND = {
                "0": {"what": "not-a-real-label"},
                "1": {"what": "not-a-real-label"},
                "2": {"what": "not-a-real-label"},
                "3": {"what": "not-a-real-label"},
                "4": {"what": "not-a-real-label"},
            }
            response = {"answers": {"severity": {"score": 0.5}}}
            result = self.provider.parse_answers(response)
            self.assertIsNone(result.get("severity"))
        finally:
            self.provider.SEVERITY_LEGEND = original_legend

    def test_malformed_score_type_yields_failed_severity(self):
        response = {"answers": {"severity": {"score": "not-a-number"}}}
        result = self.provider.parse_answers(response)
        self.assertIsNone(result.get("severity"))

    def test_missing_answers_key_entirely_is_defensive(self):
        result = self.provider.parse_answers({})
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
