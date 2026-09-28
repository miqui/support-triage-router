"""Tests for triage_router.intake: load_tickets, build_state, redact."""
import json
import os
import unittest

from triage_router.intake import build_state, load_tickets, redact

DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "synthetic", "support_tickets_synth_v1.jsonl"
)


def _tickets():
    return load_tickets(DATA_PATH)


def _by_id(ticket_id):
    for t in _tickets():
        if t["ticket_id"] == ticket_id:
            return t
    raise KeyError(ticket_id)


class TestLoadTickets(unittest.TestCase):
    def test_loads_24_records(self):
        tickets = _tickets()
        self.assertEqual(len(tickets), 24)

    def test_ids_sequential(self):
        tickets = _tickets()
        ids = [t["ticket_id"] for t in tickets]
        self.assertEqual(ids, [f"TCK-{i:04d}" for i in range(1, 25)])

    def test_malformed_line_raises_with_line_number(self):
        bad_path = os.path.join(
            os.path.dirname(__file__), "_tmp_malformed.jsonl"
        )
        with open(bad_path, "w", encoding="utf-8") as f:
            f.write('{"ticket_id": "TCK-0001"}\n')
            f.write("not json at all\n")
        try:
            with self.assertRaises(ValueError) as ctx:
                load_tickets(bad_path)
            self.assertIn("2", str(ctx.exception))
        finally:
            os.remove(bad_path)


class TestRedact(unittest.TestCase):
    def test_redacts_api_key_and_password(self):
        text = '"api_key": "***", "password": "hunter2-synth"'
        out, n = redact(text)
        self.assertNotIn("hunter2-synth", out)
        self.assertGreaterEqual(n, 1)

    def test_redacts_sk_style_token(self):
        text = "here is my token: sk-abcdef1234567890ABCDEF"
        out, n = redact(text)
        self.assertNotIn("sk-abcdef1234567890ABCDEF", out)
        self.assertGreaterEqual(n, 1)

    def test_no_false_positive_on_plain_text(self):
        text = "The password reset flow is broken for our users."
        out, n = redact(text)
        # mentions "password" but no assignment/value pattern -> no redaction
        self.assertEqual(n, 0)
        self.assertEqual(out, text)


class TestBuildStateGeneral(unittest.TestCase):
    def test_state_never_includes_expected(self):
        for t in _tickets():
            state = build_state(t)
            self.assertNotIn("expected", state)

    def test_state_never_includes_raw_body(self):
        for t in _tickets():
            state = build_state(t)
            self.assertNotIn("body", state)
            for v in state.values():
                if isinstance(v, str):
                    self.assertNotIn("hunter2-synth", v)

    def test_state_has_expected_top_level_fields(self):
        state = build_state(_by_id("TCK-0001"))
        expected_keys = {
            "subject_len",
            "body_chars",
            "has_json_block",
            "has_yaml_block",
            "has_stack_trace",
            "log_line_count",
            "mentions_error",
            "keyword_hits",
            "customer",
            "channel",
        }
        self.assertTrue(expected_keys.issubset(state.keys()))


class TestTck0009CredsFullyRedacted(unittest.TestCase):
    def test_tck_0009_creds_fully_redacted(self):
        t = _by_id("TCK-0009")
        state = build_state(t)
        blob = json.dumps(state)
        self.assertNotIn("hunter2-synth", blob)
        self.assertTrue(state["has_json_block"])
        self.assertTrue(state["has_stack_trace"])
        self.assertIn("500", state["keyword_hits"])
        self.assertIn("error", state["keyword_hits"])


class TestTck0002Features(unittest.TestCase):
    def test_tck_0002_features(self):
        t = _by_id("TCK-0002")
        state = build_state(t)
        self.assertEqual(state["subject_len"], len("want refund pls"))
        self.assertFalse(state["has_json_block"])
        self.assertFalse(state["has_yaml_block"])
        self.assertFalse(state["has_stack_trace"])
        self.assertIn("refund", state["keyword_hits"])
        self.assertEqual(state["channel"], "web_form")
        self.assertEqual(state["customer"]["tier"], "free")
        self.assertEqual(state["customer"]["id"], "C-2087")


class TestTck0024StateBodyChars(unittest.TestCase):
    def test_tck_0024_state_body_chars_14(self):
        t = _by_id("TCK-0024")
        state = build_state(t)
        self.assertEqual(len("it doesnt work"), 14)
        self.assertEqual(state["body_chars"], 14)
        self.assertEqual(state["log_line_count"], 0)
        self.assertFalse(state["mentions_error"])
        self.assertEqual(state["keyword_hits"], [])


class TestCustomerAccountAge(unittest.TestCase):
    def test_account_age_days_derived(self):
        t = _by_id("TCK-0001")
        state = build_state(t)
        # since 2024-03-11, created_at 2026-09-02 -> positive age in days
        self.assertIsInstance(state["customer"]["account_age_days"], int)
        self.assertGreater(state["customer"]["account_age_days"], 900)


if __name__ == "__main__":
    unittest.main()
