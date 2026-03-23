"""
Investigation Director — the top-level orchestrator for v2 troubleshooting.

Wires the 4-phase pipeline:
  Phase 0: Triage (LlmAgent — Gemini Flash with metrics tools)
  Phase 1: End-to-End Trace (LlmAgent)
  Phase 2: Strategic Dispatch (LlmAgent) + Parallel Specialists
  Phase 3: Synthesis (LlmAgent)

Usage:
    from agentic_ops_v2.orchestrator import investigate

    diagnosis = await investigate("UE1 can't call UE2. Both registered.")
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path

from google.adk.agents import SequentialAgent, ParallelAgent
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
            create_triage_agent(),
            create_tracer_agent(),
            create_dispatch_agent(),
            specialists,
            create_synthesis_agent(),
        ],
    )


# -------------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------------

async def investigate(question: str, on_event=None) -> dict:
    """Run a complete multi-phase investigation with per-agent tracing.

    Args:
        question: The user's troubleshooting question.
        on_event: Optional async callback ``f(event_dict)`` invoked for each
            trace event so the caller (e.g. WebSocket handler) can stream
            live progress. Event dicts have a ``"type"`` key — one of
            ``"phase_start"``, ``"phase_complete"``, ``"tool_call"``,
            ``"tool_result"``, ``"text"``.

    Returns:
        Dict with keys: triage, trace, dispatch, findings, diagnosis,
        total_tokens, investigation_trace.
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

    # --- Per-agent trace collection ---
    run_start = time.time()
    events_text: list[str] = []
    total_tokens = 0

    # Track per-agent phases: agent_name → PhaseTrace
    phase_map: dict[str, PhaseTrace] = {}
    invocation_order: list[str] = []

    # Agents that are orchestration containers, not real agents
    _SKIP_AUTHORS = {"InvestigationDirector", "SpecialistTeam", "user"}

    async def _emit(evt_dict: dict) -> None:
        if on_event:
            try:
                await on_event(evt_dict)
            except Exception:
                log.debug("on_event callback failed", exc_info=True)

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

        # Skip orchestration wrapper agents
        if author in _SKIP_AUTHORS:
            continue

        # Lazily create PhaseTrace on first event from this agent
        if author and author not in phase_map:
            phase_map[author] = PhaseTrace(agent_name=author, started_at=ts)
            invocation_order.append(author)
            log.info("Phase started: %s", author)
            await _emit({"type": "phase_start", "agent": author})

        phase = phase_map.get(author)

        # --- Token accounting ---
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
            total_tokens += total_evt

        # --- Tool call & result tracking ---
        if event.content and event.content.parts:
            for part in event.content.parts:
                # Function calls (tool invocations)
                fc = getattr(part, "function_call", None)
                if fc and phase:
                    args_str = json.dumps(fc.args, default=str)[:200] if fc.args else ""
                    tc = ToolCallTrace(
                        name=fc.name,
                        args=args_str,
                        timestamp=ts,
                    )
                    phase.tool_calls.append(tc)
                    await _emit({
                        "type": "tool_call",
                        "agent": author,
                        "name": fc.name,
                        "args": args_str,
                    })

                # Function responses (tool results)
                fr = getattr(part, "function_response", None)
                if fr and phase and phase.tool_calls:
                    result_text = json.dumps(fr.response, default=str) if fr.response else ""
                    # Attach result size to the most recent matching tool call
                    for tc in reversed(phase.tool_calls):
                        if tc.name == fr.name and tc.result_size == 0:
                            tc.result_size = len(result_text)
                            break
                    preview = result_text[:200]
                    await _emit({
                        "type": "tool_result",
                        "agent": author,
                        "name": fr.name,
                        "preview": preview,
                    })

                # Text output
                if part.text:
                    log.info("[%s] %s", author, part.text[:200])
                    events_text.append(f"[{author}] {part.text}")
                    if phase:
                        if not phase.output_summary:
                            phase.output_summary = part.text[:500]
                    await _emit({
                        "type": "text",
                        "agent": author,
                        "content": part.text[:300],
                    })

        # --- State delta tracking ---
        if event.actions and event.actions.state_delta and phase:
            keys = list(event.actions.state_delta.keys())
            for k in keys:
                if k not in phase.state_keys_written:
                    phase.state_keys_written.append(k)

    # --- Finalize phase timings ---
    run_end = time.time()
    ordered_phases: list[PhaseTrace] = []
    for name in invocation_order:
        p = phase_map[name]
        p.finished_at = run_end  # best-effort; refined below
        ordered_phases.append(p)

    # Infer per-phase end times: phase N ends when phase N+1 starts
    for i in range(len(ordered_phases) - 1):
        ordered_phases[i].finished_at = ordered_phases[i + 1].started_at
    if ordered_phases:
        ordered_phases[-1].finished_at = run_end

    # Compute durations
    total_breakdown = TokenBreakdown()
    for p in ordered_phases:
        p.duration_ms = int((p.finished_at - p.started_at) * 1000)
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
        phases=ordered_phases,
        invocation_chain=invocation_order,
    )

    log.info(
        "Investigation trace: %d agents, %d total tokens, %d ms",
        len(ordered_phases),
        total_breakdown.total,
        trace_obj.duration_ms,
    )
    for p in ordered_phases:
        log.info(
            "  %-30s %6d ms  %7d tokens  %d tool calls  %d LLM calls",
            p.agent_name,
            p.duration_ms,
            p.tokens.total,
            len(p.tool_calls),
            p.llm_calls,
        )

    # --- Retrieve final state ---
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
        "events": events_text,
    }

    # Collect specialist findings
    findings = {}
    for key in ["finding_ims", "finding_transport", "finding_core", "finding_subscriber_data"]:
        if state.get(key):
            findings[key.replace("finding_", "")] = state[key]
    result["findings"] = findings
    result["total_tokens"] = total_tokens
    result["investigation_trace"] = trace_obj.model_dump()

    # --- Persist trace to disk ---
    _persist_run(result)

    log.info("Investigation complete. Total tokens: %d. Diagnosis: %s",
             total_tokens, str(state.get("diagnosis", ""))[:200])
    return result


def _persist_run(result: dict) -> None:
    """Save the full investigation result as JSON to docs/agent_logs/."""
    try:
        logs_dir = Path(__file__).resolve().parents[0] / "docs" / "agent_logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = logs_dir / f"run_{ts}.json"
        with open(path, "w") as f:
            json.dump(result, f, indent=2, default=str)
        log.info("Trace persisted to %s", path)
    except Exception:
        log.warning("Failed to persist trace", exc_info=True)
