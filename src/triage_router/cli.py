"""Triage CLI: `triage run` and `triage eval` subcommands.

Dispatcher seam: the run command uses an injectable dispatcher. By default
it is a no-op dispatcher that only records the intended route without
constructing any crew — real dispatch is opt-in via --dispatch and imports
the dispatch module lazily, INSIDE the run handler, so `import triage_router
.cli` never pulls in crewai.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import asdict
from typing import Protocol

from triage_router.decisions import (
    DecisionProvider,
    FakeDecisionProvider,
    OpenRouterJevProvider,
)
from triage_router.eval import evaluate, format_report
from triage_router.intake import load_tickets
from triage_router.router import RouteDecision, route_ticket

_DECISION_FIELDS = ("route", "priority", "confidence", "disposition", "reasons")
_DEFAULT_TICKETS_PATH = "data/synthetic/support_tickets_synth_v1.jsonl"


class Dispatcher(Protocol):
    """Interface a dispatch callable must implement.

    Task 8's dispatch.py must expose a callable matching this exact
    signature: a positional `decision` (a RouteDecision) and `ticket`
    (the raw ticket dict) returning a dict. `_noop_dispatch` below is the
    reference no-op implementation; the real crewai-backed
    `dispatch.dispatch` function is imported lazily and used as a drop-in
    replacement via --dispatch.
    """

    def __call__(self, decision: RouteDecision, ticket: dict) -> dict: ...


def _noop_dispatch(decision: RouteDecision, ticket: dict) -> dict:
    """Default dispatcher: record the intended route, build nothing."""
    return {"status": "noop", "route": decision.route}


def _decision_to_record(decision: RouteDecision) -> dict:
    """Serialize only ticket_id + RouteDecision fields. No raw ticket data."""
    record = {"ticket_id": decision.ticket_id}
    payload = asdict(decision)
    for field_name in _DECISION_FIELDS:
        record[field_name] = payload[field_name]
    return record


def _build_provider(name: str) -> DecisionProvider:
    if name == "fake":
        return FakeDecisionProvider()
    if name == "live":
        return OpenRouterJevProvider()
    raise ValueError(f"unknown provider: {name}")


def _run_command(args: argparse.Namespace) -> int:
    if args.provider == "live" and not os.environ.get("OPENROUTER_API_KEY"):
        print(
            "error: --provider live requires OPENROUTER_API_KEY to be set in "
            "the environment. Source it (e.g. `export "
            "OPENROUTER_API_KEY=...`) before running.",
            file=sys.stderr,
        )
        return 1

    provider = _build_provider(args.provider)

    dispatcher = _noop_dispatch
    if args.dispatch:
        try:
            from .dispatch import dispatch as dispatcher
        except ImportError as exc:
            print(
                "error: --dispatch requires the crewai-backed dispatch module, "
                f"which could not be imported: {exc}",
                file=sys.stderr,
            )
            return 1

    tickets = load_tickets(args.tickets)

    decisions: list[RouteDecision] = []
    dispatch_results: list[dict] = []
    for ticket in tickets:
        decision = route_ticket(ticket, provider)
        decisions.append(decision)
        dispatch_results.append(dispatcher(decision, ticket))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            for decision in decisions:
                f.write(json.dumps(_decision_to_record(decision)))
                f.write("\n")

    route_counts = Counter(d.route for d in decisions)
    disposition_counts = Counter(d.disposition for d in decisions)

    print(f"processed {len(decisions)} tickets")
    print("counts by route:")
    for route, count in sorted(route_counts.items(), key=lambda kv: (kv[0] or "", kv[1])):
        print(f"  {route}: {count}")
    print("counts by disposition:")
    for disposition, count in sorted(disposition_counts.items()):
        print(f"  {disposition}: {count}")
    print(
        f"dispatch: {disposition_counts.get('dispatch', 0)}  "
        f"review: {disposition_counts.get('review', 0)}"
    )

    return 0


def _load_decisions(path: str) -> list[dict]:
    decisions: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                decisions.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"malformed JSONL at line {lineno} of {path}: {exc}") from exc
    return decisions


def _eval_command(args: argparse.Namespace) -> int:
    try:
        tickets = load_tickets(args.tickets)
    except FileNotFoundError:
        print(f"triage eval: tickets file not found: {args.tickets}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"triage eval: {exc}", file=sys.stderr)
        return 1

    try:
        decisions = _load_decisions(args.decisions)
    except FileNotFoundError:
        print(f"triage eval: decisions file not found: {args.decisions}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"triage eval: {exc}", file=sys.stderr)
        return 1

    try:
        report = evaluate(tickets, decisions)
    except ValueError as exc:
        print(f"triage eval: {exc}", file=sys.stderr)
        return 1

    print(format_report(report))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="triage")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Route a batch of tickets")
    run_parser.add_argument("--tickets", required=True, help="Path to tickets JSONL")
    run_parser.add_argument(
        "--provider", choices=("fake", "live"), default="fake", help="Decision provider"
    )
    run_parser.add_argument("--out", default=None, help="Path to write decisions JSONL")
    run_parser.add_argument(
        "--dispatch",
        action="store_true",
        help="Actually dispatch decisions via the crewai-backed dispatcher",
    )
    run_parser.set_defaults(func=_run_command)

    eval_parser = subparsers.add_parser("eval", help="Score a decisions JSONL")
    eval_parser.add_argument("--decisions", required=True, help="Path to decisions JSONL")
    eval_parser.add_argument(
        "--tickets",
        default=_DEFAULT_TICKETS_PATH,
        help="Path to tickets JSONL with `expected` labels (default: synthetic dataset)",
    )
    eval_parser.set_defaults(func=_eval_command)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    exit_code = args.func(args)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
