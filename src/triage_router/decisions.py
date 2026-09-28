"""Deterministic decision provider producing real-API-shaped answers.

DecisionProvider is the interface the real TypeSafe Jev / OpenRouter-backed
provider will implement. FakeDecisionProvider is a pure, seedless keyword and
heuristic mapping from intake state to the same answers shape the real API
returns under `response.answers`: no randomness, no time, no filesystem or
network access.
"""
from __future__ import annotations

import logging
import math
import os
import time
from typing import Any, Protocol, Self

import httpx

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """Raised when the real decision-provider backend call fails.

    Always carries the originating ticket id (best-effort, defensively
    extracted from state) so failures can be correlated back to a ticket
    without ever including request payload, headers, or the API key.
    """

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


# --- Real API-backed decision provider --------------------------------------

_JEV_URL = "https://openrouter.ai/api/alpha/decisions"
_JEV_MODEL = "typesafe/jev-1.13"
_MAX_RETRIES = 2
_BACKOFF_SECONDS = (0.5, 1.0)
_VALID_PRIORITIES = {"low", "medium", "high", "critical"}

_ROUTE_CRITERIA = {
    "billing": (
        "Ticket concerns payments, refunds, charges, or invoices — see "
        "`ticket.keyword_hits` for billing-adjacent keywords such as "
        "refund/charge/invoice/payment."
    ),
    "technical_bug": (
        "Ticket reports an application error, crash, or malfunction — see "
        "`ticket.has_stack_trace`, `ticket.has_json_block`, "
        "`ticket.has_yaml_block`, and `ticket.mentions_error`."
    ),
    "escalation": (
        "Ticket expresses urgency, SLA risk, or demands escalation — see "
        "`ticket.keyword_hits` for sla/urgent markers."
    ),
    "faq": (
        "Ticket is a general how-to or informational question with no "
        "billing, bug, or urgency signal — see `ticket.subject_len` and "
        "`ticket.body_chars` for low-signal short tickets."
    ),
}

_SEVERITY_CRITERIA = [
    {"what": "low", "signals": ["no risk keywords", "routine request"]},
    {"what": "medium", "signals": ["multiple keyword hits", "possible impact"]},
    {"what": "high", "signals": ["stack trace or error evidence", "urgency language"]},
    {
        "what": "critical",
        "signals": ["escalation markers", "churn/SLA risk", "credential exposure evidence"],
    },
]

_NOUL_CRITERIA = {
    "is_churn_risk": {
        "true": {
            "what": "customer shows signs of churn/SLA risk",
            "examples": ["`ticket.keyword_hits` contains sla or urgent"],
        },
        "false": {"what": "no churn or SLA risk signal present"},
    },
    "is_payment_issue": {
        "true": {
            "what": "ticket is about a payment, charge, refund, or invoice",
            "examples": ["`ticket.keyword_hits` contains refund/charge/invoice/payment"],
        },
        "false": {"what": "ticket is not about a payment issue"},
    },
    "is_credential_exposure": {
        "true": {
            "what": "ticket contains exposed, unredacted credentials",
            "not_for": "stack traces or JSON/YAML blocks alone are not evidence",
        },
        "false": {"what": "no unredacted credential exposure present"},
    },
    "is_urgent_deadline": {
        "true": {
            "what": "ticket references an urgent deadline or SLA breach risk",
            "examples": ["`ticket.keyword_hits` contains sla or urgent"],
        },
        "false": {"what": "no urgent deadline referenced"},
    },
    "is_how_to_question": {
        "true": {
            "what": "ticket is a how-to / informational question",
            "examples": ["`ticket.keyword_hits` contains 'how do i'"],
        },
        "false": {"what": "ticket is not a how-to question"},
    },
}


class OpenRouterJevProvider:
    """DecisionProvider backed by the real OpenRouter TypeSafe Jev API.

    Builds the exact Jev question/criteria contract from intake state and
    sends a single POST per decide() call, with limited retry on
    connect/timeout errors only (never on 4xx). The API key is read from
    the environment at call time so it is never hardcoded or persisted.
    """

    SEVERITY_LEGEND = _SEVERITY_LEGEND

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=10.0)
        # Only close a client we created ourselves; a caller-injected client
        # is owned by the caller and must outlive/be closed by them.
        self._owns_client = client is None

    def close(self) -> None:
        """Release the underlying httpx.Client, but only if self-created."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @staticmethod
    def _extract_ticket_id(state: dict) -> str:
        """Best-effort, defensive extraction of a ticket id from state.

        The known build_state() layout has no top-level ticket id, so this
        checks the plausible key shapes in priority order and falls back to
        a placeholder rather than raising.
        """
        if not isinstance(state, dict):
            return "unknown"
        ticket = state.get("ticket")
        if isinstance(ticket, dict) and ticket.get("id"):
            return str(ticket["id"])
        for key in ("ticket_id", "id"):
            value = state.get(key)
            if value:
                return str(value)
        customer = state.get("customer")
        if isinstance(customer, dict) and customer.get("id"):
            return f"customer:{customer['id']}"
        return "unknown"

    def decide(self, state: dict) -> dict:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise KeyError(
                "OPENROUTER_API_KEY is not set in the environment. "
                "Source it (e.g. `export OPENROUTER_API_KEY=...`) before "
                "using OpenRouterJevProvider."
            )

        payload = {
            "model": _JEV_MODEL,
            "state": state,
            "questions": self._build_questions(),
        }
        headers = {"Authorization": f"Bearer {api_key}"}

        ticket_id = self._extract_ticket_id(state)
        try:
            response = self._post_with_retry(payload, headers)
            response.raise_for_status()
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as exc:
            raise ProviderError(
                f"OpenRouterJevProvider call failed for ticket={ticket_id}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        return self.parse_answers(response.json())

    def _post_with_retry(self, payload: dict, headers: dict) -> httpx.Response:
        attempt = 0
        while True:
            try:
                return self._client.post(_JEV_URL, json=payload, headers=headers)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                # ConnectTimeout is a subclass of TimeoutException, so it is
                # already covered here; keep the tuple minimal.
                if attempt >= _MAX_RETRIES:
                    raise
                logger.warning(
                    "OpenRouterJevProvider retry attempt %d/%d after %s",
                    attempt + 1,
                    _MAX_RETRIES,
                    type(exc).__name__,
                )
                time.sleep(_BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)])
                attempt += 1

    @staticmethod
    def _build_questions() -> dict:
        return {
            "route": {
                "type": "choice",
                "instructions": (
                    "Classify the ticket's route based on `ticket.keyword_hits`, "
                    "`ticket.has_stack_trace`, `ticket.mentions_error`, "
                    "`ticket.subject_len`, and `ticket.body_chars`."
                ),
                "criteria": dict(_ROUTE_CRITERIA),
            },
            "severity": {
                "type": "score",
                "instructions": (
                    "Score overall severity 0-1 based on `ticket.keyword_hits`, "
                    "`ticket.has_stack_trace`, and escalation signals."
                ),
                "criteria": [dict(level) for level in _SEVERITY_CRITERIA],
            },
            **{
                name: {
                    "type": "noul",
                    "instructions": (
                        f"Answer whether {name.replace('_', ' ')} applies, based on "
                        "`ticket.keyword_hits` and related state fields."
                    ),
                    "criteria": {k: dict(v) for k, v in crit.items()},
                }
                for name, crit in _NOUL_CRITERIA.items()
            },
        }

    def parse_answers(self, response_json: dict) -> dict:
        """Defensively parse `response.answers` into an answers dict.

        Any missing/malformed field fails only that question (represented
        by omission), never raises. Severity->priority conversion uses only
        the legend label-matching rule: no arithmetic fallback.
        """
        answers = response_json.get("answers")
        if not isinstance(answers, dict):
            return {}

        result: dict[str, Any] = {}

        route = answers.get("route")
        if isinstance(route, dict) and "value" in route and "confidence" in route:
            result["route"] = {
                "value": route["value"],
                "confidence": route["confidence"],
            }

        severity = self._parse_severity(answers.get("severity"))
        if severity is not None:
            result["severity"] = severity

        for name in _NOUL_CRITERIA:
            noul = answers.get(name)
            if isinstance(noul, dict) and "value" in noul and "confidence" in noul:
                result[name] = {
                    "value": noul["value"],
                    "confidence": noul["confidence"],
                }

        return result

    def _parse_severity(self, severity: Any) -> dict | None:
        if not isinstance(severity, dict) or "score" not in severity:
            return None
        score = severity["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            return None

        bucket = min(4, math.floor(score * 5))
        bucket_key = str(int(bucket))
        legend = self.SEVERITY_LEGEND
        if isinstance(legend, list):
            if bucket >= len(legend):
                return None
            level = legend[bucket]
        elif isinstance(legend, dict):
            level = legend.get(bucket_key)
        else:
            return None

        if not isinstance(level, dict):
            return None
        label = level.get("what")
        if label not in _VALID_PRIORITIES:
            return None

        return {"score": score, "priority": label}
