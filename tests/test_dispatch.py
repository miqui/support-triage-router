"""Tests for triage_router.dispatch: crew construction and dispatch routing.

No live LLM/network calls: kickoff is monkeypatched everywhere. crewai must
never be imported eagerly at dispatch.py module scope.
"""
from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from triage_router.router import RouteDecision

_SECRET = "hunter2-synth"

_TICKET = {
    "ticket_id": "TCK-0001",
    "subject": "Refund needed",
    "body": f"Please refund me. token={_SECRET} thanks",
    "customer": {"id": "c1", "tier": "gold", "since": "2020-01-01"},
    "created_at": "2024-01-01T00:00:00+00:00",
    "channel": "email",
    "expected": {"route": "billing"},
}


def _decision(route: str) -> RouteDecision:
    return RouteDecision(
        ticket_id="TCK-0001",
        route=route,
        priority="medium",
        confidence=0.9,
        disposition="dispatch",
        reasons=["all checks passed"],
    )


class TestLazyImportInvariant(unittest.TestCase):
    def test_importing_dispatch_module_does_not_import_crewai(self):
        for mod in list(sys.modules):
            if mod == "crewai" or mod.startswith("crewai."):
                del sys.modules[mod]
        sys.modules.pop("triage_router.dispatch", None)

        import triage_router.dispatch  # noqa: F401

        self.assertNotIn("crewai", sys.modules)


@patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-or-fake-for-construction-only"})
class TestBuildCrews(unittest.TestCase):
    def test_build_crews_returns_all_four_routes(self):
        from triage_router.dispatch import build_crews

        crews = build_crews()
        self.assertEqual(set(crews.keys()), {"billing", "technical_bug", "escalation", "faq"})

    def test_each_crew_is_sequential_with_capped_narrow_agents(self):
        from crewai import Process

        from triage_router.dispatch import MAX_ITER, MAX_RPM, build_crews

        crews = build_crews()
        for route, crew in crews.items():
            self.assertEqual(crew.process, Process.sequential, route)
            self.assertTrue(1 <= len(crew.agents) <= 2, route)
            for agent in crew.agents:
                self.assertFalse(agent.allow_delegation, route)
                self.assertEqual(agent.max_iter, MAX_ITER, route)
                self.assertEqual(agent.max_rpm, MAX_RPM, route)
            self.assertEqual(len(crew.tasks), len(crew.agents), route)
            for task in crew.tasks:
                self.assertTrue(task.expected_output, route)


class TestDispatchRouting(unittest.TestCase):
    def _run_with_stub(self, route: str) -> dict:
        from triage_router import dispatch as dispatch_module

        captured = {}

        class _StubCrew:
            def kickoff(self, inputs=None):
                captured["inputs"] = inputs
                return f"stub-output-for-{route}"

        with patch.dict(
            dispatch_module._CREW_BUILDERS, {route: lambda: _StubCrew()}
        ):
            result = dispatch_module.dispatch(_decision(route), _TICKET)
        return result, captured

    def test_dispatch_routes_to_correct_crew_billing(self):
        result, _ = self._run_with_stub("billing")
        self.assertEqual(result["status"], "dispatched")
        self.assertEqual(result["route"], "billing")
        self.assertEqual(result["crew_output"], "stub-output-for-billing")

    def test_dispatch_routes_to_correct_crew_technical_bug(self):
        result, _ = self._run_with_stub("technical_bug")
        self.assertEqual(result["route"], "technical_bug")
        self.assertEqual(result["crew_output"], "stub-output-for-technical_bug")

    def test_dispatch_routes_to_correct_crew_escalation(self):
        result, _ = self._run_with_stub("escalation")
        self.assertEqual(result["route"], "escalation")
        self.assertEqual(result["crew_output"], "stub-output-for-escalation")

    def test_dispatch_routes_to_correct_crew_faq(self):
        result, _ = self._run_with_stub("faq")
        self.assertEqual(result["route"], "faq")
        self.assertEqual(result["crew_output"], "stub-output-for-faq")

    def test_dispatch_input_is_redacted_never_raw_body_or_secret(self):
        _, captured = self._run_with_stub("billing")
        inputs_str = str(captured["inputs"])
        self.assertNotIn(_SECRET, inputs_str)
        self.assertNotIn(_TICKET["body"], inputs_str)

    def test_unknown_route_is_skipped_never_raises(self):
        from triage_router.dispatch import dispatch

        result = dispatch(_decision("not_a_real_route"), _TICKET)
        self.assertEqual(result["status"], "skipped")
        self.assertIn("reason", result)

    def test_none_route_is_skipped_never_raises(self):
        from triage_router.dispatch import dispatch

        result = dispatch(_decision(None), _TICKET)
        self.assertEqual(result["status"], "skipped")

    def test_kickoff_raises_is_reported_as_error_never_raises(self):
        from triage_router import dispatch as dispatch_module

        class _RaisingCrew:
            def kickoff(self, inputs=None):
                raise RuntimeError("litellm: upstream 500")

        with patch.dict(
            dispatch_module._CREW_BUILDERS, {"billing": lambda: _RaisingCrew()}
        ):
            result = dispatch_module.dispatch(_decision("billing"), _TICKET)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["route"], "billing")
        self.assertIn("reason", result)
        self.assertIn("upstream 500", result["reason"])


if __name__ == "__main__":
    unittest.main()
