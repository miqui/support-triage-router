"""Deterministic decision provider producing real-API-shaped answers.

DecisionProvider is the interface the real TypeSafe Jev / OpenRouter-backed
provider will implement. FakeDecisionProvider is a pure, seedless keyword and
heuristic mapping from intake state to the same answers shape the real API
returns under `response.answers`: no randomness, no time, no filesystem or
network access.
"""
from __future__ import annotations

from typing import Any, Protocol

# --- Route keyword sets -----------------------------------------------------

_BILLING_KEYWORDS = {"refund", "charge", "invoice", "payment"}
_BUG_KEYWORDS = {"crash", "500", "error"}
_ESCALATION_KEYWORDS = {"sla", "urgent"}
_FAQ_KEYWORDS = {"how do i"}

# --- Confidence thresholds ---------------------------------------------------
# NOTE: the fake provider only ever emits this discrete set (0.85/0.6/0.3);
# the real backend returns continuous confidence values, so downstream code
# must not assume the value space is limited to these three constants.

_HIGH_CONFIDENCE = 0.85
_MEDIUM_CONFIDENCE = 0.6
_LOW_CONFIDENCE = 0.3

_FEW_KEYWORD_HITS = 2

# --- Severity legend (5-bucket, mirrors real API contract) ------------------

_SEVERITY_LEGEND = {
    "0": {"what": "low", "signals": ["no risk keywords", "routine request"]},
    "1": {"what": "low", "signals": ["single mild signal", "no urgency markers"]},
    "2": {"what": "medium", "signals": ["multiple keyword hits", "possible impact"]},
    "3": {"what": "high", "signals": ["stack trace or error evidence", "urgency language"]},
    "4": {
        "what": "critical",
        "signals": ["escalation markers", "churn/SLA risk", "credential exposure evidence"],
    },
}


class DecisionProvider(Protocol):
    """Interface a decision-making backend (real or fake) must implement."""

    def decide(self, state: dict) -> dict: ...


def _noul(value: float, confidence: float) -> dict[str, float]:
    """Build a Jev noul: a boolean/probability-style question answer."""
    return {"value": float(value), "confidence": float(confidence)}


class FakeDecisionProvider:
    """Deterministic, pure keyword+heuristic decision provider.

    A pure function of the intake state dict: identical input always yields
    an identical (bit-for-bit equal) output dict. Used to exercise the
    downstream pipeline without any network calls to a real LLM backend.
    """

    def decide(self, state: dict) -> dict:
        keyword_hits = set(state.get("keyword_hits", []))
        has_stack_trace = bool(state.get("has_stack_trace"))
        has_json_block = bool(state.get("has_json_block"))
        has_yaml_block = bool(state.get("has_yaml_block"))
        mentions_error = bool(state.get("mentions_error"))
        subject_len = state.get("subject_len", 0)
        body_chars = state.get("body_chars", 0)

        billing_hits = keyword_hits & _BILLING_KEYWORDS
        bug_hits = keyword_hits & _BUG_KEYWORDS
        escalation_hits = keyword_hits & _ESCALATION_KEYWORDS
        faq_hits = keyword_hits & _FAQ_KEYWORDS

        structural_bug_evidence = has_stack_trace or has_json_block or has_yaml_block

        route_value, route_confidence = self._route(
            billing_hits=billing_hits,
            bug_hits=bug_hits,
            escalation_hits=escalation_hits,
            faq_hits=faq_hits,
            structural_bug_evidence=structural_bug_evidence,
            mentions_error=mentions_error,
            subject_len=subject_len,
            body_chars=body_chars,
        )

        severity_score = self._severity_score(
            bug_hits=bug_hits,
            escalation_hits=escalation_hits,
            structural_bug_evidence=structural_bug_evidence,
            keyword_hits=keyword_hits,
        )

        return {
            "route": {"value": route_value, "confidence": route_confidence},
            "severity": {
                "score": severity_score,
                "legend": _SEVERITY_LEGEND,
            },
            "is_churn_risk": _noul(
                *self._churn_risk(escalation_hits, keyword_hits)
            ),
            "is_payment_issue": _noul(
                1.0 if billing_hits else 0.0,
                _HIGH_CONFIDENCE if billing_hits else _LOW_CONFIDENCE,
            ),
            "is_credential_exposure": _noul(
                *self._credential_exposure(state)
            ),
            "is_urgent_deadline": _noul(
                1.0 if escalation_hits else 0.0,
                _HIGH_CONFIDENCE if escalation_hits else _LOW_CONFIDENCE,
            ),
            "is_how_to_question": _noul(
                1.0 if (faq_hits or route_value == "faq") else 0.0,
                _MEDIUM_CONFIDENCE if (faq_hits or route_value == "faq") else _LOW_CONFIDENCE,
            ),
        }

    @staticmethod
    def _route(
        *,
        billing_hits: set,
        bug_hits: set,
        escalation_hits: set,
        faq_hits: set,
        structural_bug_evidence: bool,
        mentions_error: bool,
        subject_len: int,
        body_chars: int,
    ) -> tuple[str, float]:
        # Escalation takes priority when urgency/SLA markers co-occur with
        # any other strong signal, or appear alone with clear intent.
        if escalation_hits and (billing_hits or bug_hits or len(escalation_hits) >= 2):
            return "escalation", _HIGH_CONFIDENCE
        if escalation_hits:
            return "escalation", _MEDIUM_CONFIDENCE

        if billing_hits:
            confidence = _HIGH_CONFIDENCE if len(billing_hits) >= _FEW_KEYWORD_HITS else _MEDIUM_CONFIDENCE
            return "billing", confidence

        if bug_hits or (structural_bug_evidence and mentions_error):
            confidence = _HIGH_CONFIDENCE if (bug_hits and structural_bug_evidence) else _MEDIUM_CONFIDENCE
            return "technical_bug", confidence

        if structural_bug_evidence or mentions_error:
            return "technical_bug", _MEDIUM_CONFIDENCE

        if faq_hits:
            return "faq", _MEDIUM_CONFIDENCE

        # No signal at all: very short, uninformative tickets. Insufficient
        # information to route confidently, so default to faq with low
        # confidence (the confidence-gate case, e.g. TCK-0024).
        if subject_len + body_chars < 40:
            return "faq", _LOW_CONFIDENCE

        return "faq", _MEDIUM_CONFIDENCE

    @staticmethod
    def _severity_score(
        *, bug_hits: set, escalation_hits: set, structural_bug_evidence: bool, keyword_hits: set
    ) -> float:
        score = 0.1
        if keyword_hits:
            score += 0.15 * min(len(keyword_hits), 3)
        if bug_hits:
            score += 0.2
        if structural_bug_evidence:
            score += 0.2
        if escalation_hits:
            score += 0.35
        return round(min(score, 1.0), 4)

    @staticmethod
    def _churn_risk(escalation_hits: set, keyword_hits: set) -> tuple[float, float]:
        if "sla" in keyword_hits or ("urgent" in keyword_hits and escalation_hits):
            return 1.0, _HIGH_CONFIDENCE
        if escalation_hits:
            return 0.6, _MEDIUM_CONFIDENCE
        return 0.0, _LOW_CONFIDENCE

    @staticmethod
    def _credential_exposure(state: dict[str, Any]) -> tuple[float, float]:
        # Redaction already runs upstream in intake.build_state; state never
        # carries raw credential tokens. Only flag on explicit exposure
        # signals that intake surfaces itself (none currently exist), never
        # on stack-trace/JSON structure alone (e.g. TCK-0009 post-redaction).
        if state.get("has_unredacted_credentials"):
            return 1.0, _HIGH_CONFIDENCE
        return 0.0, _HIGH_CONFIDENCE
