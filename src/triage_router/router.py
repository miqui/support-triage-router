"""Router composition: combine provider answers into a RouteDecision.

Composes route/severity/noul answers produced by a DecisionProvider into a
single triage decision, applying a pinned confidence rule and a confidence
gate that decides whether a ticket may be auto-dispatched or must be routed
to a human reviewer.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from triage_router.decisions import DecisionProvider, ProviderError
from triage_router.intake import build_state

# --- Tunable constants -------------------------------------------------------

CONFIDENCE_GATE = 0.70
# (No severity weight here: disposition is driven entirely by the confidence
# gate and the credential-exposure rule; severity only maps to priority.)
NOUL_SIGNAL_WEIGHTS = {
    "is_churn_risk": 0.15,
    "is_payment_issue": 0.10,
    "is_credential_exposure": 0.25,
    "is_urgent_deadline": 0.15,
}
# NOTE: is_how_to_question is intentionally unweighted here — it only informs
# the provider's own faq route selection and carries no separate weight in
# this composition.
CREDENTIAL_EXPOSURE_FORCES_REVIEW = True

_VALID_ROUTES = {"billing", "technical_bug", "escalation", "faq"}
_VALID_PRIORITIES = {"low", "medium", "high", "critical"}

_SEVERITY_LABEL_TO_PRIORITY = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "critical": "critical",
}


@dataclass
class RouteDecision:
    ticket_id: str
    route: str | None
    priority: str | None
    confidence: float | None
    disposition: str
    reasons: list[str] = field(default_factory=list)


def _priority_from_severity(severity: dict | None) -> tuple[str | None, str | None]:
    """Return (priority, failure_reason). Mirrors decisions.parse_answers'
    legend label-matching rule: bucket=min(4, floor(score*5)), label must be
    one of low|medium|high|critical. No arithmetic fallback."""
    if not isinstance(severity, dict) or "score" not in severity or "legend" not in severity:
        return None, "severity answer missing or malformed"

    score = severity["score"]
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None, "severity score is not numeric"

    legend = severity["legend"]
    bucket = min(4, math.floor(score * 5))
    # Guard against out-of-range scores (negative or > 1.0): a malformed
    # bucket must fail loudly, never silently wrap via negative indexing.
    if bucket < 0 or bucket > 4:
        return None, "severity score out of bounds for bucket calculation"
    bucket_key = str(int(bucket))

    if isinstance(legend, list):
        if bucket >= len(legend):
            return None, "severity legend has no entry for bucket"
        level = legend[bucket]
    elif isinstance(legend, dict):
        level = legend.get(bucket_key)
    else:
        return None, "severity legend is malformed"

    if not isinstance(level, dict):
        return None, "severity legend entry is malformed"

    label = level.get("what")
    if label not in _VALID_PRIORITIES:
        return None, "severity legend label is not a valid priority"

    return label, None


def _extract_confidences(answers: dict) -> list[tuple[str, float]]:
    """Collect (question_name, confidence) for every answered question that
    carries a confidence value (route + all noul questions)."""
    confidences: list[tuple[str, float]] = []

    route = answers.get("route")
    if isinstance(route, dict) and isinstance(route.get("confidence"), (int, float)):
        confidences.append(("route", float(route["confidence"])))

    for name in NOUL_SIGNAL_WEIGHTS:
        noul = answers.get(name)
        if isinstance(noul, dict) and isinstance(noul.get("confidence"), (int, float)):
            confidences.append((name, float(noul["confidence"])))

    # is_how_to_question is unweighted but still answered/confidence-bearing;
    # include it in the "any answered question" confidence pool per spec.
    how_to = answers.get("is_how_to_question")
    if isinstance(how_to, dict) and isinstance(how_to.get("confidence"), (int, float)):
        confidences.append(("is_how_to_question", float(how_to["confidence"])))

    return confidences


def route_ticket(ticket: dict, provider: DecisionProvider) -> RouteDecision:
    """Build state, call the provider, and compose the final RouteDecision.

    Never reads ticket['expected'] — build_state already strips it, and this
    function only ever consumes the state dict and the provider's answers.

    Batch contract: this function always returns exactly one RouteDecision
    per ticket and never raises. Any ProviderError raised by the provider is
    caught and converted into a 'review' disposition so a batch of tickets
    can be processed without one bad provider call aborting the run.
    """
    ticket_id = ticket.get("ticket_id", "unknown")
    reasons: list[str] = []

    state = build_state(ticket)
    try:
        answers = provider.decide(state)
    except ProviderError as exc:
        return RouteDecision(
            ticket_id=ticket_id,
            route=None,
            priority=None,
            confidence=None,
            disposition="review",
            reasons=[f"provider error: {exc}"],
        )

    # --- route --------------------------------------------------------------
    route_answer = answers.get("route")
    route_value: str | None = None
    route_confidence: float | None = None
    route_missing_or_invalid = False
    if isinstance(route_answer, dict) and route_answer.get("value") in _VALID_ROUTES:
        route_value = route_answer["value"]
        conf = route_answer.get("confidence")
        if isinstance(conf, (int, float)):
            route_confidence = float(conf)
    else:
        route_missing_or_invalid = True
        reasons.append("route answer missing or invalid")

    # --- priority (from severity) --------------------------------------------
    priority, severity_failure_reason = _priority_from_severity(answers.get("severity"))
    if severity_failure_reason is not None:
        reasons.append(severity_failure_reason)

    # --- confidence (pinned rule) --------------------------------------------
    confidences = _extract_confidences(answers)
    if route_confidence is not None:
        confidence: float | None = route_confidence
    elif confidences:
        confidence = min(c for _, c in confidences)
    else:
        confidence = None

    no_confidence_available = confidence is None
    if no_confidence_available:
        reasons.append("no confidence available from any answered question")

    # --- credential exposure forced-review signal ----------------------------
    credential_forces_review = False
    credential_answer = answers.get("is_credential_exposure")
    if isinstance(credential_answer, dict):
        cred_value = credential_answer.get("value")
        if (
            CREDENTIAL_EXPOSURE_FORCES_REVIEW
            and isinstance(cred_value, (int, float))
            and cred_value >= 0.5
        ):
            credential_forces_review = True
            reasons.append("credential exposure signal forces review")

    # --- disposition ----------------------------------------------------------
    low_confidence = confidence is not None and confidence < CONFIDENCE_GATE
    if low_confidence:
        reasons.append(
            f"low confidence ({confidence:.2f}) below gate ({CONFIDENCE_GATE:.2f})"
        )

    requires_review = (
        low_confidence
        or credential_forces_review
        or route_missing_or_invalid
        or no_confidence_available
    )
    disposition = "review" if requires_review else "dispatch"
    if not requires_review:
        reasons.append("all checks passed")

    return RouteDecision(
        ticket_id=ticket_id,
        route=route_value,
        priority=priority,
        confidence=confidence,
        disposition=disposition,
        reasons=reasons,
    )
