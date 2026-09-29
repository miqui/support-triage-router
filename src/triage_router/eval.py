"""Eval harness: score RouteDecision records against expected ticket labels.

Scoring targets (all computed directly against ground-truth `expected`
fields on each ticket, never inferred from `ambiguity`):

* route accuracy: decision.route == expected.route
* priority accuracy: decision.priority == expected.priority (a review
  decision with priority None counts as a miss, and is additionally
  tallied under `priority_none_review_count`)
* review-queue accuracy: decision.disposition == "review" iff
  expected.requires_human is true. This is scored directly against
  requires_human; `ambiguity` is surfaced only as a secondary diagnostic
  breakdown below, never as the scoring target itself. A ticket may be
  ambiguous yet expected to dispatch (e.g. TCK-0003), or ambiguous and
  expected to require a human (e.g. TCK-0016) — both are handled
  correctly by keying off requires_human.

Diagnostics: per-`ambiguity`-bucket counts of dispatch vs review
decisions and their review accuracy, for informational breakdown only.
"""
from __future__ import annotations

_AMBIGUITY_BUCKETS = ("clear", "ambiguous", "insufficient_info")


def _safe_div(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def evaluate(tickets: list[dict], decisions: list[dict]) -> dict:
    """Score `decisions` (dicts or RouteDecision-like objects with
    ticket_id/route/priority/disposition) against `tickets` (each with an
    `expected` dict). Matches by ticket_id.

    Join validation (fail loud rather than silently mis-scoring):

    * Duplicate `ticket_id` values across `tickets` raise ValueError naming
      the duplicated id -- silent last-wins would hide a bad input file.
    * A ticket lacking the `expected` key raises ValueError naming the
      ticket id -- scoring without ground truth is an eval-input error,
      not a silent 0.
    * A decision whose `ticket_id` has no matching ticket is not an error:
      it is counted and surfaced as `unmatched_decisions` in the report,
      and excluded from all accuracy scoring (computed only over the
      matched set).
    * Empty `tickets`/`decisions` is valid: returns an all-zero report.

    Returns a report dict with total, route_correct/accuracy,
    priority_correct/accuracy, priority_none_review_count, review_correct
    /accuracy, unmatched_decisions, and ambiguity_diagnostics keyed by
    bucket name.
    """
    expected_by_id: dict[str, dict] = {}
    for t in tickets:
        ticket_id = t["ticket_id"]
        if ticket_id in expected_by_id:
            raise ValueError(f"duplicate ticket_id in tickets: {ticket_id!r}")
        if "expected" not in t:
            raise ValueError(f"ticket {ticket_id!r} is missing required 'expected' field")
        expected_by_id[ticket_id] = t["expected"]

    total = 0
    route_correct = 0
    priority_correct = 0
    priority_none_review_count = 0
    review_correct = 0
    unmatched_decisions = 0

    diagnostics: dict[str, dict[str, int]] = {
        bucket: {"total": 0, "dispatch": 0, "review": 0, "review_correct": 0}
        for bucket in _AMBIGUITY_BUCKETS
    }

    for decision in decisions:
        ticket_id = decision.get("ticket_id") if isinstance(decision, dict) else getattr(
            decision, "ticket_id", None
        )
        if ticket_id not in expected_by_id:
            unmatched_decisions += 1
            continue
        expected = expected_by_id[ticket_id]

        d_route = decision.get("route") if isinstance(decision, dict) else decision.route
        d_priority = (
            decision.get("priority") if isinstance(decision, dict) else decision.priority
        )
        d_disposition = (
            decision.get("disposition")
            if isinstance(decision, dict)
            else decision.disposition
        )

        total += 1

        if d_route == expected.get("route"):
            route_correct += 1

        if d_disposition == "review" and d_priority is None:
            priority_none_review_count += 1
        if d_priority == expected.get("priority"):
            priority_correct += 1

        requires_human = bool(expected.get("requires_human"))
        is_review = d_disposition == "review"
        review_is_correct = is_review == requires_human
        if review_is_correct:
            review_correct += 1

        bucket = expected.get("ambiguity")
        if bucket in diagnostics:
            diagnostics[bucket]["total"] += 1
            if is_review:
                diagnostics[bucket]["review"] += 1
            else:
                diagnostics[bucket]["dispatch"] += 1
            if review_is_correct:
                diagnostics[bucket]["review_correct"] += 1

    return {
        "total": total,
        "route_correct": route_correct,
        "route_accuracy": _safe_div(route_correct, total),
        "priority_correct": priority_correct,
        "priority_accuracy": _safe_div(priority_correct, total),
        "priority_none_review_count": priority_none_review_count,
        "review_correct": review_correct,
        "review_accuracy": _safe_div(review_correct, total),
        "unmatched_decisions": unmatched_decisions,
        "ambiguity_diagnostics": diagnostics,
    }


def format_report(report: dict) -> str:
    """Render a plain-text, Slack/print-friendly report."""
    lines = []
    total = report["total"]
    lines.append(f"eval report ({total} tickets scored)")

    labels = ("route accuracy:", "priority accuracy:", "review accuracy:")
    width = max(len(label) for label in labels)

    lines.append(
        f"  {labels[0]:<{width}} {report['route_correct']}/{total} "
        f"({report['route_accuracy'] * 100:.1f}%)"
    )
    lines.append(
        f"  {labels[1]:<{width}} {report['priority_correct']}/{total} "
        f"({report['priority_accuracy'] * 100:.1f}%)"
        f"  [none-priority reviews: {report['priority_none_review_count']}]"
    )
    lines.append(
        f"  {labels[2]:<{width}} {report['review_correct']}/{total} "
        f"({report['review_accuracy'] * 100:.1f}%) "
        "(vs expected.requires_human)"
    )
    lines.append(f"  unmatched decisions: {report['unmatched_decisions']}")
    lines.append("  ambiguity diagnostics (informational, not scoring target):")
    for bucket in _AMBIGUITY_BUCKETS:
        diag = report["ambiguity_diagnostics"].get(bucket)
        if not diag:
            continue
        bucket_total = diag["total"]
        if bucket_total == 0:
            continue
        acc = _safe_div(diag["review_correct"], bucket_total) * 100
        lines.append(
            f"    {bucket}: total={bucket_total} dispatch={diag['dispatch']} "
            f"review={diag['review']} review_correct={diag['review_correct']} "
            f"({acc:.1f}%)"
        )
    return "\n".join(lines)
