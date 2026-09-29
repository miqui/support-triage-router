"""Tests for triage_router.router: composition, confidence gate, RouteDecision."""
import copy
import os
import unittest

from triage_router.decisions import FakeDecisionProvider, ProviderError
from triage_router.intake import load_tickets
from triage_router.router import (
    CONFIDENCE_GATE,
    CREDENTIAL_EXPOSURE_FORCES_REVIEW,
    RouteDecision,
    route_ticket,
)

DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "synthetic", "support_tickets_synth_v1.jsonl"
)


def _ticket_by_id(ticket_id: str) -> dict:
    for ticket in load_tickets(DATA_PATH):
        if ticket["ticket_id"] == ticket_id:
            return ticket
    raise KeyError(ticket_id)


class TestRouteDecisionShape(unittest.TestCase):
    def test_route_decision_fields(self):
        decision = RouteDecision(
            ticket_id="TCK-x",
            route="billing",
            priority="low",
            confidence=0.9,
            disposition="dispatch",
            reasons=["ok"],
        )
        self.assertEqual(decision.ticket_id, "TCK-x")
        self.assertEqual(decision.route, "billing")
        self.assertEqual(decision.priority, "low")
        self.assertEqual(decision.confidence, 0.9)
        self.assertEqual(decision.disposition, "dispatch")
        self.assertEqual(decision.reasons, ["ok"])


class TestRouteTicketClearBilling(unittest.TestCase):
    """A synthetic clear-billing ticket ('TCK-0002-ish') should dispatch."""

    def test_clear_billing_dispatches(self):
        ticket = {
            "ticket_id": "TCK-0002-ish",
            "created_at": "2026-09-03T09:45:11Z",
            "channel": "web_form",
            "customer": {"id": "C-2087", "tier": "free", "since": "2025-01-20"},
            "subject": "refund request",
            "body": "you charged me twice for the same invoice, please refund",
        }
        decision = route_ticket(ticket, FakeDecisionProvider())
        self.assertEqual(decision.ticket_id, "TCK-0002-ish")
        self.assertEqual(decision.route, "billing")
        self.assertEqual(decision.disposition, "dispatch")
        self.assertGreaterEqual(decision.confidence, CONFIDENCE_GATE)


class TestRouteTicketVagueLowConfidence(unittest.TestCase):
    def test_TCK_0024_vague_reviews_with_low_confidence_reason(self):
        ticket = _ticket_by_id("TCK-0024")
        decision = route_ticket(ticket, FakeDecisionProvider())
        self.assertEqual(decision.ticket_id, "TCK-0024")
        self.assertEqual(decision.disposition, "review")
        self.assertLess(decision.confidence, CONFIDENCE_GATE)
        self.assertTrue(
            any("confidence" in r.lower() for r in decision.reasons),
            decision.reasons,
        )


class TestRouteTicketRedactionProof(unittest.TestCase):
    def test_TCK_0009_fake_creds_post_redaction_dispatches_without_credential_trigger(self):
        ticket = _ticket_by_id("TCK-0009")
        decision = route_ticket(ticket, FakeDecisionProvider())
        self.assertEqual(decision.ticket_id, "TCK-0009")
        self.assertEqual(decision.route, "technical_bug")
        self.assertEqual(decision.disposition, "dispatch")
        self.assertFalse(
            any("credential" in r.lower() for r in decision.reasons),
            decision.reasons,
        )

    def test_synthetic_unredacted_state_forces_review(self):
        """A state with has_unredacted_credentials=True (bypassing intake's
        redaction, e.g. a hand-built state) must force review via the
        credential-exposure signal, even when route confidence is high."""
        state = {
            "keyword_hits": ["refund", "charge"],
            "has_stack_trace": False,
            "has_json_block": False,
            "has_yaml_block": False,
            "mentions_error": False,
            "subject_len": 20,
            "body_chars": 20,
            "has_unredacted_credentials": True,
        }
        provider = FakeDecisionProvider()
        answers = provider.decide(state)
        self.assertGreaterEqual(answers["is_credential_exposure"]["value"], 0.5)
        self.assertGreaterEqual(answers["route"]["confidence"], CONFIDENCE_GATE)

        class _StateProvider:
            def decide(self, _state: dict) -> dict:
                return answers

        ticket = {"ticket_id": "TCK-synthetic-unredacted", "subject": "x", "body": "y"}
        decision = route_ticket(ticket, _StateProvider())
        self.assertEqual(decision.disposition, "review")
        self.assertTrue(CREDENTIAL_EXPOSURE_FORCES_REVIEW)
        self.assertTrue(
            any("credential" in r.lower() for r in decision.reasons),
            decision.reasons,
        )


class TestRouteTicketAmbiguousStillDispatched(unittest.TestCase):
    def test_TCK_0003_ambiguous_dispatched_with_reasons_recorded(self):
        ticket = _ticket_by_id("TCK-0003")
        decision = route_ticket(ticket, FakeDecisionProvider())
        self.assertEqual(decision.ticket_id, "TCK-0003")
        self.assertEqual(decision.disposition, "dispatch")
        self.assertTrue(decision.reasons)


class TestRouteTicketNeverReadsExpected(unittest.TestCase):
    def test_decision_identical_with_expected_present_or_stripped(self):
        ticket = _ticket_by_id("TCK-0001")
        ticket_with_expected = copy.deepcopy(ticket)
        self.assertIn("expected", ticket_with_expected)

        ticket_without_expected = copy.deepcopy(ticket)
        ticket_without_expected.pop("expected", None)
        self.assertNotIn("expected", ticket_without_expected)

        decision_with = route_ticket(ticket_with_expected, FakeDecisionProvider())
        decision_without = route_ticket(ticket_without_expected, FakeDecisionProvider())

        self.assertEqual(decision_with, decision_without)


class TestRouteTicketAllDatasetTickets(unittest.TestCase):
    def test_every_ticket_decides_without_exception(self):
        tickets = load_tickets(DATA_PATH)
        self.assertEqual(len(tickets), 24)
        provider = FakeDecisionProvider()
        dispositions = {"dispatch": 0, "review": 0}
        for ticket in tickets:
            with self.subTest(ticket_id=ticket["ticket_id"]):
                decision = route_ticket(ticket, provider)
                self.assertEqual(decision.ticket_id, ticket["ticket_id"])
                self.assertIn(decision.disposition, ("dispatch", "review"))
                self.assertTrue(decision.reasons)
                dispositions[decision.disposition] += 1
        self.assertEqual(sum(dispositions.values()), 24)


class TestRouteTicketProviderError(unittest.TestCase):
    """Batch contract: never propagate an exception; one RouteDecision always."""

    def test_provider_error_routes_to_review_with_reason(self):
        class _FailingProvider:
            def decide(self, _state: dict) -> dict:
                raise ProviderError("upstream timed out")

        ticket = {"ticket_id": "TCK-error-1", "subject": "x", "body": "y"}
        decision = route_ticket(ticket, _FailingProvider())
        self.assertEqual(decision.ticket_id, "TCK-error-1")
        self.assertEqual(decision.disposition, "review")
        self.assertIsNone(decision.route)
        self.assertIsNone(decision.priority)
        self.assertIsNone(decision.confidence)
        self.assertTrue(
            any("provider error" in r.lower() and "upstream timed out" in r for r in decision.reasons),
            decision.reasons,
        )


class TestRouteTicketEmptyAnswers(unittest.TestCase):
    def test_empty_answers_reviews_via_no_confidence_rule(self):
        class _EmptyProvider:
            def decide(self, _state: dict) -> dict:
                return {}

        ticket = {"ticket_id": "TCK-empty-1", "subject": "x", "body": "y"}
        decision = route_ticket(ticket, _EmptyProvider())
        self.assertEqual(decision.disposition, "review")
        self.assertIsNone(decision.confidence)
        self.assertTrue(
            any("no confidence available" in r.lower() for r in decision.reasons),
            decision.reasons,
        )


class TestCredentialExposureBoundary(unittest.TestCase):
    def test_credential_exposure_exactly_half_forces_review(self):
        answers = {
            "route": {"value": "billing", "confidence": 0.95},
            "is_credential_exposure": {"value": 0.5, "confidence": 0.9},
        }

        class _StateProvider:
            def decide(self, _state: dict) -> dict:
                return answers

        ticket = {"ticket_id": "TCK-cred-boundary", "subject": "x", "body": "y"}
        decision = route_ticket(ticket, _StateProvider())
        self.assertEqual(decision.disposition, "review")
        self.assertTrue(
            any("credential" in r.lower() for r in decision.reasons),
            decision.reasons,
        )


class TestSeverityBucketGuard(unittest.TestCase):
    def _decide_with_severity(self, severity: dict) -> RouteDecision:
        answers = {
            "route": {"value": "billing", "confidence": 0.95},
            "severity": severity,
        }

        class _StateProvider:
            def decide(self, _state: dict) -> dict:
                return answers

        ticket = {"ticket_id": "TCK-severity-guard", "subject": "x", "body": "y"}
        return route_ticket(ticket, _StateProvider())

    def test_negative_score_fails_severity_without_negative_indexing(self):
        legend = [
            {"what": "low"},
            {"what": "medium"},
            {"what": "high"},
            {"what": "critical"},
            {"what": "critical"},
        ]
        decision = self._decide_with_severity({"score": -0.4, "legend": legend})
        self.assertIsNone(decision.priority)
        self.assertTrue(
            any("out of bounds" in r.lower() for r in decision.reasons),
            decision.reasons,
        )

    def test_score_over_one_still_bounded_by_bucket_clamp(self):
        legend = [
            {"what": "low"},
            {"what": "medium"},
            {"what": "high"},
            {"what": "critical"},
            {"what": "critical"},
        ]
        decision = self._decide_with_severity({"score": 1.4, "legend": legend})
        self.assertEqual(decision.priority, "critical")


if __name__ == "__main__":
    unittest.main()
