"""
Healer — reverses all active faults and captures post-heal metrics.

No LLM needed — purely deterministic. Reads active faults from the SQLite
registry, executes each heal command, verifies, and captures post-heal metrics.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from ..fault_registry import FaultRegistry
from ..tools.observation_tools import snapshot_metrics

log = logging.getLogger("chaos-agent.healer")


class Healer(BaseAgent):
    """Heals all active faults and captures post-heal state."""

    name: str = "Healer"
    description: str = "Reverses all active faults via the registry and captures post-heal metrics."
    registry: FaultRegistry

    model_config = {"arbitrary_types_allowed": True}

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        healed_at = datetime.now(timezone.utc)

        # Heal all active faults
        count = await self.registry.heal_all(method="scheduled")
        log.info("Healed %d active faults", count)

        # Capture post-heal metrics
        post_heal_metrics = await snapshot_metrics()

        # Compute recovery time (from first fault injection to now)
        faults_injected = ctx.session.state.get("faults_injected", [])
        recovery_time = 0.0
        if faults_injected:
            first_inject = min(
                (f.get("injected_at", "") for f in faults_injected if f.get("success")),
                default="",
            )
            if first_inject:
                try:
                    inject_dt = datetime.fromisoformat(first_inject)
                    recovery_time = (healed_at - inject_dt).total_seconds()
                except (ValueError, TypeError):
                    pass

        resolution = {
            "healed_at": healed_at.isoformat(),
            "heal_method": "scheduled",
            "post_heal_metrics": post_heal_metrics,
            "recovery_time_seconds": recovery_time,
            "faults_healed": count,
        }

        msg = f"Healed {count} faults. Recovery time: {recovery_time:.1f}s"

        yield Event(
            author=self.name,
            content=types.Content(parts=[types.Part(text=msg)]),
            actions=EventActions(state_delta={"resolution": resolution}),
        )

    async def _run_live_impl(self, ctx):
        raise NotImplementedError
