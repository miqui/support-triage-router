"""Ticket intake: JSONL loading, redaction, and state derivation.

Redaction runs before any body-derived content leaves this module: build_state
never embeds raw body text, only counts/flags derived from the redacted body.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

_KEYWORDS = [
    "refund",
    "charge",
    "invoice",
    "payment",
    "crash",
    "500",
    "error",
    "how do i",
    "sla",
    "urgent",
]

# Matches assignment-style credential fields, e.g.:
#   api_key: "xyz"   apikey="xyz"   "password": "xyz"   Bearer xyz   token=xyz
_CRED_ASSIGNMENT_RE = re.compile(
    r"""(?ix)
    (
        (?:"(?:api_key|apikey|token|password|secret|bearer)"\s*:\s*"[^"]*")
        |
        (?:\b(?:api_key|apikey|token|password|secret)\b\s*[:=]\s*"[^"]*")
        |
        (?:\b(?:api_key|apikey|token|password|secret)\b\s*[:=]\s*'[^']*')
        |
        (?:\b(?:api_key|apikey|token|password|secret)\b\s*[:=]\s*\S+)
        |
        (?:\bbearer\s+\S+)
    )
    """
)

# sk-... style secret tokens (e.g. OpenAI-style keys) standalone in text.
_SK_TOKEN_RE = re.compile(r"\bsk-[A-Za-z0-9]{8,}\b")

_JSON_FENCE_RE = re.compile(r"```json", re.IGNORECASE)
_YAML_FENCE_RE = re.compile(r"```yaml", re.IGNORECASE)
# Intentionally broad: matches Traceback/Exception markers, stack-frame
# lines, trace-JSON fields, and internal service-call patterns.
_STACK_TRACE_RE = re.compile(
    r"(Traceback|Exception|at [a-zA-Z_][\w.]*\.[A-Za-z_]\w*\("
    r"|\"trace\"\s*:|\b[A-Z]\w*(?:Service|Pool|Client|Handler)\.\w+\s*->)"
)


def load_tickets(path: str) -> list[dict]:
    """Read a JSONL file of tickets. Raises ValueError with the line number
    on a malformed line."""
    tickets: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                tickets.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Malformed JSON on line {lineno} of {path}: {exc}"
                ) from exc
    return tickets


def redact(text: str) -> tuple[str, int]:
    """Redact credential-like substrings. Returns (redacted_text, count)."""
    count = 0

    def _sub(m: re.Match) -> str:
        nonlocal count
        count += 1
        return "***"

    redacted = _CRED_ASSIGNMENT_RE.sub(_sub, text)
    redacted = _SK_TOKEN_RE.sub(_sub, redacted)
    return redacted, count


def _account_age_days(since: str, created_at: str) -> int | None:
    try:
        since_dt = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=UTC)
        created_dt = datetime.fromisoformat(created_at)
        return (created_dt - since_dt).days
    except (TypeError, ValueError):
        return None


def build_state(ticket: dict[str, Any]) -> dict[str, Any]:
    """Derive router state from a ticket. Never includes `expected`, and
    never embeds raw (unredacted) body text."""
    subject = ticket.get("subject", "")
    body = ticket.get("body", "")

    redacted_subject, _ = redact(subject)
    redacted_body, _ = redact(body)

    combined = f"{redacted_subject}\n{redacted_body}"
    combined_lower = combined.lower()

    has_json_block = bool(_JSON_FENCE_RE.search(redacted_body))
    has_yaml_block = bool(_YAML_FENCE_RE.search(redacted_body))
    has_stack_trace = bool(_STACK_TRACE_RE.search(redacted_body))
    log_line_count = sum(
        1
        for ln in redacted_body.splitlines()
        if _STACK_TRACE_RE.search(ln) or ln.strip().startswith(("at ", "File "))
    )
    mentions_error = "error" in combined_lower or "exception" in combined_lower

    keyword_hits = [kw for kw in _KEYWORDS if kw in combined_lower]

    customer = ticket.get("customer", {})
    since = customer.get("since")
    created_at = ticket.get("created_at")
    account_age_days = None
    if since and created_at:
        account_age_days = _account_age_days(since, created_at)

    return {
        "subject_len": len(subject),
        "body_chars": len(body),
        "has_json_block": has_json_block,
        "has_yaml_block": has_yaml_block,
        "has_stack_trace": has_stack_trace,
        "log_line_count": log_line_count,
        "mentions_error": mentions_error,
        "keyword_hits": keyword_hits,
        "customer": {
            "id": customer.get("id"),
            "tier": customer.get("tier"),
            "account_age_days": account_age_days,
        },
        "channel": ticket.get("channel"),
    }
