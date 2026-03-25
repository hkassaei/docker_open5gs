"""
BaselineCollector — captures a pre-fault snapshot of the stack.

No LLM needed — purely deterministic. Calls observation tools to capture
metrics, container statuses, and stack phase. Writes result to
session.state["baseline"].
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from ..tools.observation_tools import (
    determine_phase,
    snapshot_container_status,
    snapshot_metrics,
)

log = logging.getLogger("chaos-agent.baseline")

_BASELINE_TIMEOUT = 20  # seconds for entire baseline capture


class BaselineCollector(BaseAgent):
    """Captures pre-fault metrics + container status snapshot."""

    name: str = "BaselineCollector"
    description: str = "Captures a baseline snapshot of the stack before fault injection."

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        log.info("Capturing baseline snapshot...")

        metrics = await snapshot_metrics()
        try:
            statuses = await asyncio.wait_for(
                snapshot_container_status(), timeout=_BASELINE_TIMEOUT
            )
        except asyncio.TimeoutError:
            log.warning("Container status snapshot timed out")
            statuses = {}
        phase = determine_phase(statuses)

        baseline = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stack_phase": phase,
            "container_status": statuses,
            "metrics": metrics,
        }

        nf_count = len([s for s in statuses.values() if s == "running"])
        metric_count = len(metrics)

        yield Event(
            author=self.name,
            content=types.Content(
                parts=[types.Part(text=(
                    f"Baseline captured: phase={phase}, "
                    f"{nf_count} containers running, "
                    f"{metric_count} NFs with metrics"
                ))],
            ),
            actions=EventActions(state_delta={"baseline": baseline}),
        )

    async def _run_live_impl(self, ctx):
        raise NotImplementedError
