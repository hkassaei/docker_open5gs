"""
Investigation Director — the top-level orchestrator for v2 troubleshooting.

Wires the 4-phase pipeline:
  Phase 0: Triage (deterministic + LLM oversight)
  Phase 1: End-to-End Trace (LlmAgent)
  Phase 2: Strategic Dispatch + Parallel Specialists
  Phase 3: Synthesis (LlmAgent)

Usage:
    from agentic_ops_v2.orchestrator import investigate

    diagnosis = await investigate("UE1 can't call UE2. Both registered.")
"""

from __future__ import annotations

import json
import logging

from google.adk.agents import SequentialAgent, ParallelAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from .agents.triage import TriageAgent
from .agents.tracer import create_tracer_agent
from .agents.dispatcher import DispatchAgent
from .agents.ims_specialist import create_ims_specialist
from .agents.transport_specialist import create_transport_specialist
from .agents.core_specialist import create_core_specialist
from .agents.subscriber_data_specialist import create_subscriber_data_specialist
from .agents.synthesis import create_synthesis_agent

log = logging.getLogger("v2.orchestrator")

# -------------------------------------------------------------------------
# Specialist registry
# -------------------------------------------------------------------------

_SPECIALIST_FACTORIES = {
    "ims": create_ims_specialist,
    "transport": create_transport_specialist,
    "core": create_core_specialist,
    "subscriber_data": create_subscriber_data_specialist,
}


# -------------------------------------------------------------------------
# Pipeline construction
# -------------------------------------------------------------------------

def _create_specialist_parallel(specialist_names: list[str]) -> ParallelAgent:
    """Create a ParallelAgent containing the requested specialists."""
    agents = []
    for name in specialist_names:
        factory = _SPECIALIST_FACTORIES.get(name)
        if factory:
            agents.append(factory())
        else:
            log.warning("Unknown specialist: %s", name)

    if not agents:
        # Fallback: run IMS + transport
        log.warning("No valid specialists — falling back to IMS + transport")
        agents = [create_ims_specialist(), create_transport_specialist()]

    return ParallelAgent(
        name="SpecialistTeam",
        description="Parallel execution of specialist investigation agents.",
        sub_agents=agents,
    )


def create_investigation_director(
    specialist_names: list[str] | None = None,
) -> SequentialAgent:
    """Create the full investigation pipeline.

    Args:
        specialist_names: Which specialists to include. If None, all are included
            and the DispatchAgent decides at runtime which to actually run.
            If provided, only those specialists are wired in.

    Returns:
        A SequentialAgent: triage → trace → dispatch → specialists → synthesis
    """
    # For static specialist selection (testing), wire them directly
    # For dynamic (production), include all and let dispatcher decide
    if specialist_names:
        specialists = _create_specialist_parallel(specialist_names)
    else:
        # Include all specialists — the dispatcher's output in state["dispatch"]
        # guides which ones the LLM actually engages
        specialists = _create_specialist_parallel(list(_SPECIALIST_FACTORIES.keys()))

    return SequentialAgent(
        name="InvestigationDirector",
        description=(
            "Multi-phase troubleshooting pipeline: "
            "triage → trace → dispatch → specialists → synthesis."
        ),
        sub_agents=[
            TriageAgent(),
            create_tracer_agent(),
            DispatchAgent(),
            specialists,
            create_synthesis_agent(),
        ],
    )


# -------------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------------

async def investigate(question: str) -> dict:
    """Run a complete multi-phase investigation.

    Args:
        question: The user's troubleshooting question.

    Returns:
        Dict with keys: triage, trace, dispatch, findings, diagnosis.
    """
    director = create_investigation_director()

    session_service = InMemorySessionService()
    runner = Runner(
        agent=director,
        app_name="troubleshoot_v2",
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name="troubleshoot_v2",
        user_id="operator",
        state={
            "user_question": question,
            "emergency_notices": [],
        },
    )

    log.info("Starting v2 investigation: %s", question[:100])

    events: list[str] = []
    total_tokens = 0
    async for event in runner.run_async(
        user_id="operator",
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=question)],
        ),
    ):
        # Accumulate token usage from every LLM call
        if event.usage_metadata and event.usage_metadata.total_token_count:
            total_tokens += event.usage_metadata.total_token_count

        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    log.info("[%s] %s", event.author, part.text[:200])
                    events.append(f"[{event.author}] {part.text}")

    # Retrieve final state
    final_session = await session_service.get_session(
        app_name="troubleshoot_v2",
        user_id="operator",
        session_id=session.id,
    )

    state = final_session.state
    result = {
        "triage": state.get("triage"),
        "trace": state.get("trace"),
        "dispatch": state.get("dispatch"),
        "emergency_notices": state.get("emergency_notices", []),
        "diagnosis": state.get("diagnosis"),
        "events": events,
    }

    # Collect specialist findings
    findings = {}
    for key in ["finding_ims", "finding_transport", "finding_core", "finding_subscriber_data"]:
        if state.get(key):
            findings[key.replace("finding_", "")] = state[key]
    result["findings"] = findings
    result["total_tokens"] = total_tokens

    log.info("Investigation complete. Total tokens: %d. Diagnosis: %s",
             total_tokens, str(state.get("diagnosis", ""))[:200])
    return result
