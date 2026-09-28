"""Tests for triage_router.decisions: DecisionProvider, FakeDecisionProvider."""
import os
import unittest

from triage_router.decisions import FakeDecisionProvider
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


if __name__ == "__main__":
    unittest.main()
