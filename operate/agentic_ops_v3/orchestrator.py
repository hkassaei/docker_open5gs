"""
Investigation Director v3 — context-isolated multi-agent pipeline.

Each phase runs in its own ADK session with a fresh conversation history.
Only structured state (output_key values) flows between phases — no raw
tool outputs or LLM reasoning from prior phases leak into downstream agents.

Pipeline:
  Phase 0: Triage      → Session A → state["triage"]
  Phase 1: Tracer      → Session B → state["trace"]
  Phase 2: Dispatch    → Session C → state["dispatch"]
  Phase 2b: Specialists → Session D → state["finding_*"]
  Phase 3: Synthesis   → Session E → state["diagnosis"]

Usage:
    from agentic_ops_v3.orchestrator import investigate
    result = await investigate("UE1 can't call UE2. Both registered.")
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from google.adk.agents import ParallelAgent
from google.adk.agents.base_agent import BaseAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from .agents.triage import create_triage_agent
from .agents.tracer import create_tracer_agent
from .agents.dispatcher import create_dispatch_agent
from .agents.ims_specialist import create_ims_specialist
from .agents.transport_specialist import create_transport_specialist
from .agents.core_specialist import create_core_specialist
from .agents.subscriber_data_specialist import create_subscriber_data_specialist
from .agents.synthesis import create_synthesis_agent
from .models import (
    InvestigationTrace,
    PhaseTrace,
    TokenBreakdown,
    ToolCallTrace,
)

log = logging.getLogger("v3.orchestrator")

# -------------------------------------------------------------------------
# Specialist registry
# -------------------------------------------------------------------------

_SPECIALIST_FACTORIES = {
    "ims": create_ims_specialist,
    "transport": create_transport_specialist,
    "core": create_core_specialist,
    "subscriber_data": create_subscriber_data_specialist,
}

_VALID_SPECIALISTS = frozenset(_SPECIALIST_FACTORIES.keys())


# -------------------------------------------------------------------------
# Dispatch output parsing
# -------------------------------------------------------------------------

def _parse_dispatch_output(dispatch_text: str) -> list[str]:
    """Extract specialist names from the dispatcher's free-text output.

    Strategy:
      1. Look for a structured 'DISPATCH: name1, name2' line.
      2. Fallback: keyword scan for specialist names in the text.
      3. Ultimate fallback: ["ims", "transport"].
    """
    # Primary: structured DISPATCH line
    match = re.search(r"DISPATCH:\s*(.+)", dispatch_text, re.IGNORECASE)
    if match:
        names = [n.strip().lower() for n in match.group(1).split(",")]
        valid = [n for n in names if n in _VALID_SPECIALISTS]
        if valid:
            return valid

    # Fallback: keyword scan
    text_lower = dispatch_text.lower()
    found = [name for name in _VALID_SPECIALISTS if name in text_lower]
    if found:
        return found

    log.warning("Could not parse dispatch output, falling back to ims + transport")
    return ["ims", "transport"]


# -------------------------------------------------------------------------
# Session-per-phase execution
# -------------------------------------------------------------------------

async def _run_phase(
    agent: BaseAgent,
    state: dict[str, Any],
    question: str,
    session_service: InMemorySessionService,
    on_event=None,
) -> tuple[dict[str, Any], list[PhaseTrace]]:
    """Run one agent in an isolated session, return updated state + traces.

    Creates a fresh session seeded with ``state``, runs the agent, and returns
    the merged state (input state + any new output_key values). The conversation
    history from this phase does NOT carry over to the next phase.
    """
    runner = Runner(
        agent=agent,
        app_name="troubleshoot_v3",
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name="troubleshoot_v3",
        user_id="operator",
        state=dict(state),  # copy to avoid mutation
    )

    phase_map: dict[str, PhaseTrace] = {}
    _SKIP = {"InvestigationDirector", "SpecialistTeam", "user"}

    async for event in runner.run_async(
        user_id="operator",
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=question)],
        ),
    ):
        author = event.author or ""
        ts = event.timestamp if hasattr(event, "timestamp") and event.timestamp else time.time()

        if author in _SKIP:
            continue

        # Lazily create PhaseTrace
        if author and author not in phase_map:
            phase_map[author] = PhaseTrace(agent_name=author, started_at=ts)
            log.info("  Phase started: %s", author)
            if on_event:
                try:
                    await on_event({"type": "phase_start", "agent": author})
                except Exception:
                    pass

        phase = phase_map.get(author)

        # Token accounting
        um = event.usage_metadata
        if um and phase:
            prompt = getattr(um, "prompt_token_count", 0) or 0
            completion = getattr(um, "candidates_token_count", 0) or 0
            thinking = getattr(um, "thoughts_token_count", 0) or 0
            total_evt = getattr(um, "total_token_count", 0) or 0
            phase.tokens.prompt += prompt
            phase.tokens.completion += completion
            phase.tokens.thinking += thinking
            phase.tokens.total += total_evt
            phase.llm_calls += 1

        # Tool call & result tracking + event streaming
        if event.content and event.content.parts:
            for part in event.content.parts:
                fc = getattr(part, "function_call", None)
                if fc and phase:
                    args_str = json.dumps(fc.args, default=str)[:200] if fc.args else ""
                    phase.tool_calls.append(ToolCallTrace(
                        name=fc.name, args=args_str, timestamp=ts,
                    ))
                    if on_event:
                        try:
                            await on_event({
                                "type": "tool_call", "agent": author,
                                "name": fc.name, "args": args_str,
                            })
                        except Exception:
                            pass

                fr = getattr(part, "function_response", None)
                if fr and phase and phase.tool_calls:
                    result_text = json.dumps(fr.response, default=str) if fr.response else ""
                    for tc in reversed(phase.tool_calls):
                        if tc.name == fr.name and tc.result_size == 0:
                            tc.result_size = len(result_text)
                            break
                    if on_event:
                        try:
                            await on_event({
                                "type": "tool_result", "agent": author,
                                "name": fr.name, "preview": result_text[:200],
                            })
                        except Exception:
                            pass

                if part.text and phase:
                    if not phase.output_summary:
                        phase.output_summary = part.text[:500]
                    if on_event:
                        try:
                            await on_event({
                                "type": "text", "agent": author,
                                "content": part.text[:300],
                            })
                        except Exception:
                            pass

        # State delta tracking
        if event.actions and event.actions.state_delta and phase:
            for k in event.actions.state_delta:
                if k not in phase.state_keys_written:
                    phase.state_keys_written.append(k)

    # Read final state and merge with input
    final_session = await session_service.get_session(
        app_name="troubleshoot_v3",
        user_id="operator",
        session_id=session.id,
    )
    updated_state = {**state, **final_session.state}

    # Finalize traces
    now = time.time()
    traces = list(phase_map.values())
    for t in traces:
        t.finished_at = now
        t.duration_ms = int((t.finished_at - t.started_at) * 1000)

    return updated_state, traces


# -------------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------------

async def investigate(question: str, on_event=None) -> dict:
    """Run a context-isolated multi-phase investigation.

    Each phase runs in its own ADK session. Only structured state flows
    between phases — no conversation history leaks.
    """
    session_service = InMemorySessionService()
    state: dict[str, Any] = {"user_question": question}
    all_phases: list[PhaseTrace] = []
    invocation_order: list[str] = []
    run_start = time.time()

    log.info("Starting v3 investigation: %s", question[:100])

    # Phase 0: Triage
    state, traces = await _run_phase(
        create_triage_agent(), state, question, session_service, on_event)
    all_phases.extend(traces)
    invocation_order.extend(t.agent_name for t in traces)

    # Phase 1: End-to-End Trace
    state, traces = await _run_phase(
        create_tracer_agent(), state, question, session_service, on_event)
    all_phases.extend(traces)
    invocation_order.extend(t.agent_name for t in traces)

    # Phase 2: Dispatch
    state, traces = await _run_phase(
        create_dispatch_agent(), state, question, session_service, on_event)
    all_phases.extend(traces)
    invocation_order.extend(t.agent_name for t in traces)

    # Phase 2b: Dynamic specialist selection
    selected = _parse_dispatch_output(state.get("dispatch", ""))
    log.info("Dispatching specialists: %s", selected)

    specialist_agents = []
    for name in selected:
        factory = _SPECIALIST_FACTORIES.get(name)
        if factory:
            specialist_agents.append(factory())
    if not specialist_agents:
        log.warning("No valid specialists — falling back to IMS + transport")
        specialist_agents = [create_ims_specialist(), create_transport_specialist()]

    specialist_team = ParallelAgent(
        name="SpecialistTeam",
        description="Parallel execution of selected specialist agents.",
        sub_agents=specialist_agents,
    )
    state, traces = await _run_phase(
        specialist_team, state, question, session_service, on_event)
    all_phases.extend(traces)
    invocation_order.extend(t.agent_name for t in traces)

    # Phase 3: Synthesis
    state, traces = await _run_phase(
        create_synthesis_agent(), state, question, session_service, on_event)
    all_phases.extend(traces)
    invocation_order.extend(t.agent_name for t in traces)

    # --- Build investigation trace ---
    run_end = time.time()
    total_breakdown = TokenBreakdown()
    for p in all_phases:
        total_breakdown.prompt += p.tokens.prompt
        total_breakdown.completion += p.tokens.completion
        total_breakdown.thinking += p.tokens.thinking
        total_breakdown.total += p.tokens.total

    trace_obj = InvestigationTrace(
        question=question[:200],
        started_at=run_start,
        finished_at=run_end,
        duration_ms=int((run_end - run_start) * 1000),
        total_tokens=total_breakdown,
        phases=all_phases,
        invocation_chain=invocation_order,
    )

    log.info("Investigation trace: %d agents, %d total tokens, %d ms",
             len(all_phases), total_breakdown.total, trace_obj.duration_ms)
    for p in all_phases:
        log.info("  %-30s %6d ms  %7d tokens  %d tool calls  %d LLM calls",
                 p.agent_name, p.duration_ms, p.tokens.total,
                 len(p.tool_calls), p.llm_calls)

    # --- Assemble result ---
    findings = {}
    for key in ["finding_ims", "finding_transport", "finding_core", "finding_subscriber_data"]:
        if state.get(key):
            findings[key.replace("finding_", "")] = state[key]

    result = {
        "triage": state.get("triage"),
        "trace": state.get("trace"),
        "dispatch": state.get("dispatch"),
        "findings": findings,
        "diagnosis": state.get("diagnosis"),
        "events": [f"[{p.agent_name}] {p.output_summary}" for p in all_phases if p.output_summary],
        "total_tokens": total_breakdown.total,
        "investigation_trace": trace_obj.model_dump(),
    }

    _persist_run(result)

    log.info("Investigation complete. Total tokens: %d. Diagnosis: %s",
             total_breakdown.total, str(state.get("diagnosis", ""))[:200])
    return result


def _persist_run(result: dict) -> None:
    """Save the full investigation result as JSON to docs/agent_logs/."""
    try:
        logs_dir = Path(__file__).resolve().parent / "docs" / "agent_logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = logs_dir / f"run_{ts}.json"
        with open(path, "w") as f:
            json.dump(result, f, indent=2, default=str)
        log.info("Trace persisted to %s", path)
    except Exception:
        log.warning("Failed to persist trace", exc_info=True)
