"""
SymptomObserver — polls metrics and logs at intervals to detect fault symptoms.

Implemented as a LoopAgent containing a SymptomPoller BaseAgent. Each iteration:
1. Captures current metrics and recent logs
2. Computes delta against baseline
3. Checks if significant changes detected
4. If symptoms found → escalate (exit loop)
5. If max iterations reached → exit loop

The observation history is accumulated in session.state["observations"].
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator

from google.adk.agents import LoopAgent
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from ..tools._common import LOG_CONTAINERS
from ..tools.observation_tools import (
    compute_metrics_delta,
    snapshot_logs,
    snapshot_metrics,
)

log = logging.getLogger("chaos-agent.observer")

_OBSERVATION_TIMEOUT = 15  # seconds per poll iteration


class SymptomPoller(BaseAgent):
    """Single poll iteration: capture metrics, compute delta, check for symptoms."""

    name: str = "SymptomPoller"
    description: str = "Polls metrics and logs, detects symptoms by comparing to baseline."
    poll_interval_seconds: float = 5.0

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        # Wait for poll interval (except on first iteration)
        observations = ctx.session.state.get("observations", [])
        if observations:
            await asyncio.sleep(self.poll_interval_seconds)

        baseline = ctx.session.state.get("baseline", {})
        baseline_metrics = baseline.get("metrics", {})
        baseline_ts = baseline.get("timestamp", "")
        start_time = datetime.fromisoformat(baseline_ts) if baseline_ts else datetime.now(timezone.utc)

        iteration = len(observations) + 1
        now = datetime.now(timezone.utc)
        elapsed = (now - start_time).total_seconds()

        log.info("Symptom poll iteration %d (elapsed: %.1fs)", iteration, elapsed)

        # Capture current state (with timeouts — targets may be unreachable during chaos)
        try:
            current_metrics = await asyncio.wait_for(
                snapshot_metrics(), timeout=_OBSERVATION_TIMEOUT
            )
        except asyncio.TimeoutError:
            log.warning("Metrics snapshot timed out during observation")
            current_metrics = {}

        try:
            current_logs = await asyncio.wait_for(
                snapshot_logs(containers=LOG_CONTAINERS, tail=20),
                timeout=_OBSERVATION_TIMEOUT,
            )
        except asyncio.TimeoutError:
            log.warning("Log snapshot timed out during observation")
            current_logs = {}

        # Compute delta
        delta = compute_metrics_delta(baseline_metrics, current_metrics)

        # Filter logs to notable lines (errors, warnings, state changes)
        notable_logs = _filter_notable_logs(current_logs)

        # Detect symptoms: any metric changed OR notable log lines appeared
        symptoms_detected = bool(delta) or bool(notable_logs)

        observation = {
            "iteration": iteration,
            "timestamp": now.isoformat(),
            "elapsed_seconds": elapsed,
            "metrics_delta": delta,
            "log_samples": notable_logs,
            "symptoms_detected": symptoms_detected,
            "escalation_level": ctx.session.state.get("escalation_level", 0),
        }

        observations = list(observations)  # Copy
        observations.append(observation)

        state_update = {
            "observations": observations,
            "symptoms_detected": symptoms_detected,
        }

        if symptoms_detected:
            changed_nodes = list(delta.keys())
            log_nodes = [k for k, v in notable_logs.items() if v]
            msg = (
                f"Iteration {iteration}: SYMPTOMS DETECTED. "
                f"Metric changes in: {changed_nodes}. "
                f"Notable logs from: {log_nodes}."
            )
            log.info("  → %s", msg)

            yield Event(
                author=self.name,
                content=types.Content(parts=[types.Part(text=msg)]),
                actions=EventActions(
                    state_delta=state_update,
                    escalate=True,  # Exit the LoopAgent
                ),
            )
        else:
            msg = f"Iteration {iteration}: No symptoms detected yet (elapsed: {elapsed:.0f}s)"
            log.info("  → %s", msg)

            yield Event(
                author=self.name,
                content=types.Content(parts=[types.Part(text=msg)]),
                actions=EventActions(state_delta=state_update),
            )

    async def _run_live_impl(self, ctx):
        raise NotImplementedError


def create_symptom_observer(
    max_iterations: int = 6,
    poll_interval_seconds: float = 5.0,
    registry=None,
) -> LoopAgent:
    """Factory: create a SymptomObserver LoopAgent.

    When a registry is provided, adaptive escalation is enabled: if no symptoms
    are detected, the EscalationChecker will heal the current fault and re-inject
    at a higher severity level (the "Boiling Frog" pattern).

    Args:
        max_iterations: Max poll cycles before giving up.
        poll_interval_seconds: Seconds between polls.
        registry: FaultRegistry for escalation. If None, escalation is disabled.

    Returns:
        A LoopAgent wrapping SymptomPoller (+ optional EscalationChecker).
    """
    poller = SymptomPoller(poll_interval_seconds=poll_interval_seconds)

    sub_agents = [poller]

    if registry is not None:
        from .escalation import EscalationChecker
        sub_agents.append(EscalationChecker(registry=registry))

    return LoopAgent(
        name="SymptomObserver",
        description=(
            "Polls metrics and logs at intervals to detect symptoms caused by "
            "injected faults. Exits when symptoms are detected, max escalation "
            "level reached, or max iterations exhausted."
        ),
        max_iterations=max_iterations,
        sub_agents=sub_agents,
    )


def _filter_notable_logs(logs: dict[str, list[str]]) -> dict[str, list[str]]:
    """Filter log lines to only notable ones (errors, warnings, state changes)."""
    notable: dict[str, list[str]] = {}
    keywords = (
        "error", "fail", "timeout", "refused", "unreachable", "reset",
        "lost", "drop", "reject", "abort", "crash", "fatal", "panic",
        "408", "500", "503",  # SIP/HTTP error codes
    )

    for container, lines in logs.items():
        filtered = []
        for line in lines:
            lower = line.lower()
            if any(kw in lower for kw in keywords):
                # Skip known false positives
                if "allow:" in lower or "unrecognised option" in lower:
                    continue
                filtered.append(line)
        if filtered:
            notable[container] = filtered

    return notable
