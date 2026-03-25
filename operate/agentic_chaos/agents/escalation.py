"""
EscalationChecker — decides whether to escalate fault severity or exit the observation loop.

Runs after SymptomPoller inside the LoopAgent. Implements the "Boiling Frog" pattern:
  - If symptoms detected → exit loop (escalate event)
  - If no symptoms and escalation enabled → heal current fault, re-inject at next level
  - If max escalation level reached → exit loop

Escalation schedules define parameter progressions per fault type:
  network_latency: 100ms → 250ms → 500ms → 2000ms
  network_loss:    5% → 15% → 30% → 50%
  etc.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
import uuid
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from ..fault_registry import FaultRegistry
from ..models import ESCALATION_SCHEDULES, Fault
from ..tools.network_tools import (
    clear_tc_rules,
    inject_bandwidth_limit,
    inject_latency,
    inject_packet_loss,
)

log = logging.getLogger("chaos-agent.escalation")


class EscalationChecker(BaseAgent):
    """Checks symptoms and escalates fault severity if needed."""

    name: str = "EscalationChecker"
    description: str = "Escalates fault severity when no symptoms are detected."
    registry: FaultRegistry

    model_config = {"arbitrary_types_allowed": True}

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        symptoms_detected = ctx.session.state.get("symptoms_detected", False)
        scenario = ctx.session.state.get("scenario", {})
        escalation_enabled = scenario.get("escalation", False)
        current_level = ctx.session.state.get("escalation_level", 0)

        # If symptoms detected → exit loop
        if symptoms_detected:
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text=f"Symptoms detected at escalation level {current_level} — stopping observation")],
                ),
                actions=EventActions(escalate=True),
            )
            return

        # If escalation not enabled → just continue the loop (LoopAgent handles max_iterations)
        if not escalation_enabled:
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text="No symptoms yet, continuing observation...")],
                ),
            )
            return

        # Find escalatable faults in the scenario
        faults = scenario.get("faults", [])
        escalatable = [
            f for f in faults
            if f.get("fault_type") in ESCALATION_SCHEDULES
        ]

        if not escalatable:
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text="No escalatable fault types in this scenario")],
                ),
            )
            return

        # Check if we've reached max escalation
        for fault_spec in escalatable:
            schedule = ESCALATION_SCHEDULES.get(fault_spec["fault_type"], [])
            next_level = current_level + 1
            if next_level >= len(schedule):
                log.info("Max escalation level reached (%d) for %s",
                         current_level, fault_spec["fault_type"])
                yield Event(
                    author=self.name,
                    content=types.Content(
                        parts=[types.Part(text=(
                            f"Max escalation level reached ({current_level}) "
                            f"for {fault_spec['fault_type']} — no symptoms detected at any level"
                        ))],
                    ),
                    actions=EventActions(escalate=True),
                )
                return

        # Escalate: heal current faults, re-inject at next level
        next_level = current_level + 1
        log.info("Escalating from level %d to %d", current_level, next_level)

        # Heal all active faults
        await self.registry.heal_all(method="escalation")

        # Re-inject each escalatable fault at the new level
        episode_id = ctx.session.state.get("episode_id", "ep_unknown")
        faults_injected = list(ctx.session.state.get("faults_injected", []))

        for fault_spec in escalatable:
            schedule = ESCALATION_SCHEDULES[fault_spec["fault_type"]]
            new_params = {**fault_spec.get("params", {}), **schedule[next_level]}

            result = await self._reinject(
                episode_id=episode_id,
                fault_type=fault_spec["fault_type"],
                target=fault_spec["target"],
                params=new_params,
                ttl_seconds=fault_spec.get("ttl_seconds", 120),
            )

            if result:
                faults_injected.append(result)
                log.info("  Escalated %s on %s to level %d: %s",
                         fault_spec["fault_type"], fault_spec["target"],
                         next_level, new_params)

        param_summary = ", ".join(
            f"{k}={v}" for f in escalatable
            for k, v in ESCALATION_SCHEDULES[f["fault_type"]][next_level].items()
        )
        msg = f"Escalated to level {next_level}: {param_summary}"

        yield Event(
            author=self.name,
            content=types.Content(parts=[types.Part(text=msg)]),
            actions=EventActions(state_delta={
                "escalation_level": next_level,
                "faults_injected": faults_injected,
            }),
        )

    async def _reinject(
        self,
        episode_id: str,
        fault_type: str,
        target: str,
        params: dict,
        ttl_seconds: int,
    ) -> dict | None:
        """Re-inject a fault at a new escalation level."""
        try:
            # First clear any existing tc rules on this target
            await clear_tc_rules(target)

            # Inject at new level
            if fault_type == "network_latency":
                result = await inject_latency(
                    target, params["delay_ms"], params.get("jitter_ms", 0)
                )
            elif fault_type == "network_loss":
                result = await inject_packet_loss(target, params["loss_pct"])
            elif fault_type == "network_bandwidth":
                result = await inject_bandwidth_limit(target, params["rate_kbit"])
            else:
                log.warning("No escalation handler for %s", fault_type)
                return None

            if not result.get("success"):
                log.warning("Escalation re-inject failed: %s", result.get("detail"))
                return None

            # Register in fault registry
            now = datetime.now(timezone.utc)
            fault = Fault(
                fault_id=f"f_{uuid.uuid4().hex[:8]}",
                episode_id=episode_id,
                fault_type=fault_type,
                target=target,
                params=params,
                mechanism=result["mechanism"],
                heal_command=result["heal_cmd"],
                injected_at=now,
                ttl_seconds=ttl_seconds,
                expires_at=now + timedelta(seconds=ttl_seconds),
                verified=True,
                verification_result="escalation re-inject",
            )
            await self.registry.register_fault(fault)

            return {
                "fault_id": fault.fault_id,
                "fault_type": fault_type,
                "target": target,
                "params": params,
                "mechanism": result["mechanism"],
                "heal_command": result["heal_cmd"],
                "injected_at": now.isoformat(),
                "ttl_seconds": ttl_seconds,
                "success": True,
                "verified": True,
                "verification_result": f"escalation level {params}",
            }

        except Exception as e:
            log.error("Escalation re-inject error: %s", e)
            return None

    async def _run_live_impl(self, ctx):
        raise NotImplementedError
