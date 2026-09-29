"""CrewAI-backed dispatch: the ONLY module allowed to import crewai.

All crewai imports happen lazily, inside functions, so importing
`triage_router.dispatch` itself never puts `crewai` into `sys.modules`
until `build_crews()` or `dispatch()` actually runs. This mirrors the
lazy-import discipline `cli.py` already relies on for `--dispatch`.

Only redacted, derived ticket state (via `intake.build_state`) is ever
handed to a crew — never the raw ticket body.
"""
from __future__ import annotations

import os
from typing import Any

from triage_router.intake import build_state
from triage_router.router import RouteDecision

# --- Tunable constants -------------------------------------------------------

MAX_ITER = 3
MAX_RPM = 10  # modest cap; MVP crews make no tool calls, so this is generous

_MODEL = "z-ai/glm-5.3-flash"
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_ROUTES = ("billing", "technical_bug", "escalation", "faq")


def _build_llm() -> Any:
    """Build the shared OpenRouter-backed LLM config for every agent.

    CrewAI's LLM wraps LiteLLM, which expects an OpenRouter-style model id
    prefixed with the provider (`openrouter/...`) plus `OPENROUTER_API_KEY`
    in the environment — LiteLLM reads that env var itself for the
    `openrouter/` provider, so we do not need to pass api_key explicitly,
    but we do so anyway for clarity and to fail fast if it's unset.
    """
    from crewai import LLM

    return LLM(
        model=f"openrouter/{_MODEL}",
        base_url=_OPENROUTER_BASE_URL,
        api_key=os.environ.get("OPENROUTER_API_KEY"),
    )


def _billing_crew() -> Any:  # duplication across the four builders below is
    # intentional: route-specific prose (role/backstory/task), not a factory target.
    from crewai import Agent, Crew, Process, Task

    llm = _build_llm()
    analyst = Agent(
        role="Billing Analyst",
        goal="Assess refund/charge disputes for eligibility and amount",
        backstory=(
            "A meticulous billing specialist who reviews payment and refund "
            "complaints against policy, flags credential/PII exposure, and "
            "never approves a refund outright — only recommends one."
        ),
        allow_delegation=False,
        memory=False,
        max_iter=MAX_ITER,
        max_rpm=MAX_RPM,
        llm=llm,
    )
    task = Task(
        description=(
            "Given the redacted ticket state {ticket_state}, assess the "
            "billing complaint and produce a refund assessment."
        ),
        expected_output=(
            "A refund assessment stating: estimated refund amount (or "
            "'none'), an eligibility verdict (eligible/not eligible/needs "
            "review), and one sentence of justification."
        ),
        agent=analyst,
    )
    return Crew(agents=[analyst], tasks=[task], process=Process.sequential)


def _technical_bug_crew() -> Any:
    from crewai import Agent, Crew, Process, Task

    llm = _build_llm()
    triager = Agent(
        role="Technical Triage Engineer",
        goal="Summarize bug reports and identify the likely affected component",
        backstory=(
            "A backend engineer who reads stack traces and error signals to "
            "narrow down the suspected component and figure out what repro "
            "information is still missing."
        ),
        allow_delegation=False,
        memory=False,
        max_iter=MAX_ITER,
        max_rpm=MAX_RPM,
        llm=llm,
    )
    task = Task(
        description=(
            "Given the redacted ticket state {ticket_state}, produce a "
            "technical triage summary."
        ),
        expected_output=(
            "A triage summary naming the suspected component or subsystem, "
            "a short severity read, and a bullet list of repro questions to "
            "ask the customer."
        ),
        agent=triager,
    )
    return Crew(agents=[triager], tasks=[task], process=Process.sequential)


def _escalation_crew() -> Any:
    from crewai import Agent, Crew, Process, Task

    llm = _build_llm()
    lead = Agent(
        role="Escalation Lead",
        goal="Justify escalation priority and prepare a handoff for humans",
        backstory=(
            "A senior support lead who decides how urgently an escalated "
            "ticket needs human attention and writes concise handoff notes "
            "so the on-call responder can act immediately."
        ),
        allow_delegation=False,
        memory=False,
        max_iter=MAX_ITER,
        max_rpm=MAX_RPM,
        llm=llm,
    )
    task = Task(
        description=(
            "Given the redacted ticket state {ticket_state}, justify the "
            "escalation priority and prepare handoff notes."
        ),
        expected_output=(
            "A priority justification (why this needs escalation now) "
            "followed by handoff notes: who should own it and what context "
            "they need."
        ),
        agent=lead,
    )
    return Crew(agents=[lead], tasks=[task], process=Process.sequential)


def _faq_crew() -> Any:
    from crewai import Agent, Crew, Process, Task

    llm = _build_llm()
    responder = Agent(
        role="FAQ Responder",
        goal="Answer how-to questions directly and point to documentation",
        backstory=(
            "A support responder who answers common how-to questions "
            "concisely and always points the customer at the relevant doc."
        ),
        allow_delegation=False,
        memory=False,
        max_iter=MAX_ITER,
        max_rpm=MAX_RPM,
        llm=llm,
    )
    task = Task(
        description=(
            "Given the redacted ticket state {ticket_state}, answer the "
            "customer's how-to question."
        ),
        expected_output=(
            "A direct answer to the customer's question, followed by a "
            "pointer to the relevant documentation page or section."
        ),
        agent=responder,
    )
    return Crew(agents=[responder], tasks=[task], process=Process.sequential)


_CREW_BUILDERS = {
    "billing": _billing_crew,
    "technical_bug": _technical_bug_crew,
    "escalation": _escalation_crew,
    "faq": _faq_crew,
}


def build_crews() -> dict[str, Any]:
    """Build one crew per route. Each call constructs fresh crews."""
    return {route: builder() for route, builder in _CREW_BUILDERS.items()}


def dispatch(decision: RouteDecision, ticket: dict) -> dict:
    """Dispatch a routed ticket to its route's crew.

    Conforms to cli.Dispatcher: (decision, ticket) -> dict. Never raises,
    across every path: an unknown/missing route is reported as 'skipped',
    and a crew/kickoff failure (litellm and crewai raise a variety of
    exception types) is reported as 'error' with the exception message —
    neither case lets an exception propagate to the caller.
    Only the redacted, derived ticket state (via intake.build_state) is
    ever passed into the crew kickoff input; the raw ticket body never
    leaves this boundary. Only the single crew needed for this route is
    built, not all four.
    """
    route = decision.route
    if route not in _ROUTES:
        return {"status": "skipped", "reason": f"unknown route: {route!r}"}

    crew = _CREW_BUILDERS[route]()

    state = build_state(ticket)
    try:
        result = crew.kickoff(inputs={"ticket_state": state})
    except Exception as exc:  # noqa: BLE001 - litellm/crewai raise heterogeneously
        return {"status": "error", "route": route, "reason": str(exc)}

    return {
        "status": "dispatched",
        "route": route,
        "crew_output": str(result),
    }
