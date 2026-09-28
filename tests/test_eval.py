"""Tests for eval.py: scoring decisions against expected labels."""
from __future__ import annotations

import unittest

from triage_router.eval import evaluate, format_report


def _ticket(ticket_id, route, priority, requires_human, ambiguity):
    return {
        "ticket_id": ticket_id,
        "expected": {
            "route": route,
            "priority": priority,
            "requires_human": requires_human,
            "ambiguity": ambiguity,
        },
    }


def _decision(ticket_id, route, priority, disposition):
    return {
        "ticket_id": ticket_id,
        "route": route,
        "priority": priority,
        "disposition": disposition,
    }


class TestEvaluatePerfect(unittest.TestCase):
    def setUp(self):
        self.tickets = [
            _ticket("TCK-0001", "billing", "high", False, "clear"),
            _ticket("TCK-0002", "technical_bug", "critical", True, "clear"),
            _ticket("TCK-0003", "billing", "high", False, "ambiguous"),
        ]

    def test_perfect_decisions_score_100_percent(self):
        decisions = [
            _decision("TCK-0001", "billing", "high", "dispatch"),
            _decision("TCK-0002", "technical_bug", "critical", "review"),
            _decision("TCK-0003", "billing", "high", "dispatch"),
        ]
        report = evaluate(self.tickets, decisions)
        self.assertEqual(report["total"], 3)
        self.assertEqual(report["route_correct"], 3)
        self.assertEqual(report["route_accuracy"], 1.0)
        self.assertEqual(report["priority_correct"], 3)
        self.assertEqual(report["priority_accuracy"], 1.0)
        self.assertEqual(report["review_correct"], 3)
        self.assertEqual(report["review_accuracy"], 1.0)


class TestEvaluateGarbage(unittest.TestCase):
    def setUp(self):
        self.tickets = [
            _ticket("TCK-0001", "billing", "high", False, "clear"),
            _ticket("TCK-0002", "technical_bug", "critical", True, "clear"),
            _ticket("TCK-0003", "billing", "high", False, "ambiguous"),
        ]

    def test_garbage_decisions_score_low_no_exception(self):
        decisions = [
            _decision("TCK-0001", "faq", "low", "review"),
            _decision("TCK-0002", "faq", "low", "dispatch"),
            _decision("TCK-0003", "faq", "low", "review"),
        ]
        report = evaluate(self.tickets, decisions)
        self.assertEqual(report["total"], 3)
        self.assertEqual(report["route_correct"], 0)
        self.assertEqual(report["route_accuracy"], 0.0)
        self.assertEqual(report["priority_correct"], 0)
        self.assertEqual(report["priority_accuracy"], 0.0)
        self.assertEqual(report["review_correct"], 0)
        self.assertEqual(report["review_accuracy"], 0.0)

    def test_review_decision_with_none_priority_counts_as_miss(self):
        tickets = [_ticket("TCK-0001", "billing", "high", True, "clear")]
        decisions = [_decision("TCK-0001", None, None, "review")]
        report = evaluate(tickets, decisions)
        self.assertEqual(report["priority_correct"], 0)
        self.assertEqual(report["priority_accuracy"], 0.0)
        # separate none-priority-review count
        self.assertEqual(report["priority_none_review_count"], 1)


class TestRequiresHumanDirectScoring(unittest.TestCase):
    """TCK-0003 is ambiguous but expected dispatch; TCK-0016 is ambiguous and
    expected review. Scoring must key off requires_human directly, never
    off ambiguity."""

    def setUp(self):
        self.tickets = [
            _ticket("TCK-0003", "billing", "high", False, "ambiguous"),
            _ticket("TCK-0016", "escalation", "critical", True, "ambiguous"),
        ]

    def test_dispatch_on_tck0003_counts_correct(self):
        decisions = [
            _decision("TCK-0003", "billing", "high", "dispatch"),
            _decision("TCK-0016", "escalation", "critical", "review"),
        ]
        report = evaluate(self.tickets, decisions)
        self.assertEqual(report["review_correct"], 2)
        self.assertEqual(report["review_accuracy"], 1.0)

    def test_review_on_tck0003_counts_incorrect(self):
        decisions = [
            _decision("TCK-0003", "billing", "high", "review"),
            _decision("TCK-0016", "escalation", "critical", "review"),
        ]
        report = evaluate(self.tickets, decisions)
        self.assertEqual(report["review_correct"], 1)
        self.assertEqual(report["review_accuracy"], 0.5)


class TestAmbiguityDiagnostics(unittest.TestCase):
    def test_per_bucket_diagnostic_counts(self):
        tickets = [
            _ticket("TCK-0001", "billing", "high", False, "clear"),
            _ticket("TCK-0002", "technical_bug", "critical", True, "clear"),
            _ticket("TCK-0003", "billing", "high", False, "ambiguous"),
            _ticket("TCK-0004", "faq", "low", False, "insufficient_info"),
        ]
        decisions = [
            _decision("TCK-0001", "billing", "high", "dispatch"),
            _decision("TCK-0002", "technical_bug", "critical", "review"),
            _decision("TCK-0003", "billing", "high", "review"),
            _decision("TCK-0004", "faq", "low", "dispatch"),
        ]
        report = evaluate(tickets, decisions)
        diag = report["ambiguity_diagnostics"]
        self.assertEqual(diag["clear"]["total"], 2)
        self.assertEqual(diag["clear"]["dispatch"], 1)
        self.assertEqual(diag["clear"]["review"], 1)
        self.assertEqual(diag["clear"]["review_correct"], 2)
        self.assertEqual(diag["ambiguous"]["total"], 1)
        self.assertEqual(diag["ambiguous"]["dispatch"], 0)
        self.assertEqual(diag["ambiguous"]["review"], 1)
        self.assertEqual(diag["ambiguous"]["review_correct"], 0)
        self.assertEqual(diag["insufficient_info"]["total"], 1)
        self.assertEqual(diag["insufficient_info"]["dispatch"], 1)
        self.assertEqual(diag["insufficient_info"]["review_correct"], 1)


class TestFormatReport(unittest.TestCase):
    def test_format_report_contains_accuracy_lines(self):
        tickets = [_ticket("TCK-0001", "billing", "high", False, "clear")]
        decisions = [_decision("TCK-0001", "billing", "high", "dispatch")]
        report = evaluate(tickets, decisions)
        text = format_report(report)
        self.assertIn("route accuracy", text.lower())
        self.assertIn("priority accuracy", text.lower())
        self.assertIn("review accuracy", text.lower())
        self.assertIn("100.0%", text)


if __name__ == "__main__":
    unittest.main()
