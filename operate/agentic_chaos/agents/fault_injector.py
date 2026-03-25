"""
FaultInjector — executes the Target → Inject → Verify cycle for each fault.

For pre-built scenarios this is deterministic (BaseAgent). Reads the scenario
from session.state["scenario"], iterates through each FaultSpec, dispatches
to the appropriate tool, registers in the fault registry, and verifies.

The safety invariant: a fault is registered in the registry BEFORE the inject
command runs. If injection or verification fails, the fault is healed and
removed from the registry.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from ..fault_registry import FaultRegistry
from ..models import Fault, FaultStatus
from ..tools.docker_tools import (
    docker_get_pid,
    docker_kill,
    docker_pause,
    docker_restart,
    docker_stop,
)
from ..tools.network_tools import (
    inject_bandwidth_limit,
    inject_corruption,
    inject_latency,
    inject_packet_loss,
    inject_partition,
)
from ..tools.verification_tools import (
    verify_container_status,
    verify_latency,
    verify_reachable,
    verify_tc_active,
    verify_tc_with_pid,
    verify_unreachable,
)

log = logging.getLogger("chaos-agent.injector")

# Map fault_type → (inject_function, verify_function)
_CONTAINER_FAULTS = {"container_kill", "container_stop", "container_pause", "container_restart"}
_NETWORK_FAULTS = {
    "network_latency", "network_loss", "network_corruption",
    "network_bandwidth", "network_partition",
}


class FaultInjector(BaseAgent):
    """Deterministic fault injector for pre-built scenarios."""

    name: str = "FaultInjector"
    description: str = (
        "Injects faults defined in the scenario. Each fault follows the "
        "Target → Inject → Verify safety pattern."
    )
    registry: FaultRegistry

    model_config = {"arbitrary_types_allowed": True}

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        scenario = ctx.session.state.get("scenario")
        if not scenario:
            yield Event(
                author=self.name,
                content=types.Content(
                    parts=[types.Part(text="ERROR: No scenario in state")],
                ),
            )
            return

        episode_id = ctx.session.state.get("episode_id", "ep_unknown")
        faults = scenario.get("faults", [])
        injected: list[dict] = []

        for i, spec in enumerate(faults):
            fault_type = spec["fault_type"]
            target = spec["target"]
            params = spec.get("params", {})
            ttl = spec.get("ttl_seconds", scenario.get("ttl_seconds", 120))

            log.info("Injecting fault %d/%d: %s on %s", i + 1, len(faults), fault_type, target)

            try:
                result = await self._inject_one(
                    episode_id=episode_id,
                    fault_type=fault_type,
                    target=target,
                    params=params,
                    ttl_seconds=ttl,
                )
                injected.append(result)
                status = "VERIFIED" if result["verified"] else "UNVERIFIED"
                log.info("  → %s: %s", status, result.get("verification_result", ""))

            except Exception as e:
                log.error("  → FAILED: %s", e)
                injected.append({
                    "fault_type": fault_type,
                    "target": target,
                    "success": False,
                    "error": str(e),
                })

        summary = f"Injected {len([f for f in injected if f.get('success')])} of {len(faults)} faults"

        yield Event(
            author=self.name,
            content=types.Content(parts=[types.Part(text=summary)]),
            actions=EventActions(state_delta={"faults_injected": injected}),
        )

    async def _inject_one(
        self,
        episode_id: str,
        fault_type: str,
        target: str,
        params: dict,
        ttl_seconds: int,
    ) -> dict:
        """Execute the Target → Inject → Verify cycle for a single fault."""
        now = datetime.now(timezone.utc)
        fault_id = f"f_{uuid.uuid4().hex[:8]}"

        # Step 1: Execute the injection and get mechanism + heal_cmd
        inject_result = await self._dispatch_inject(fault_type, target, params)

        if not inject_result["success"]:
            return {
                "fault_id": fault_id,
                "fault_type": fault_type,
                "target": target,
                "success": False,
                "error": inject_result.get("detail", "Injection command failed"),
            }

        mechanism = inject_result["mechanism"]
        heal_cmd = inject_result["heal_cmd"]

        # Step 2: Register in the fault registry
        fault = Fault(
            fault_id=fault_id,
            episode_id=episode_id,
            fault_type=fault_type,
            target=target,
            params=params,
            mechanism=mechanism,
            heal_command=heal_cmd,
            injected_at=now,
            ttl_seconds=ttl_seconds,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        await self.registry.register_fault(fault)

        # Step 3: Verify the injection took effect
        verify_result = await self._dispatch_verify(fault_type, target, params, inject_result)

        if verify_result.get("verified", False):
            await self.registry.mark_verified(
                fault_id, result=verify_result.get("detail", "")
            )
            return {
                "fault_id": fault_id,
                "fault_type": fault_type,
                "target": target,
                "params": params,
                "mechanism": mechanism,
                "heal_command": heal_cmd,
                "injected_at": now.isoformat(),
                "ttl_seconds": ttl_seconds,
                "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(),
                "success": True,
                "verified": True,
                "verification_result": verify_result.get("detail", ""),
            }
        else:
            # Verification failed — heal and remove
            log.warning("Verification failed for %s on %s — healing", fault_type, target)
            await self.registry._execute_heal(heal_cmd)
            await self.registry.remove_fault(fault_id)
            return {
                "fault_id": fault_id,
                "fault_type": fault_type,
                "target": target,
                "success": True,
                "verified": False,
                "verification_result": verify_result.get("detail", ""),
            }

    # -----------------------------------------------------------------
    # Dispatch to the right tool based on fault_type
    # -----------------------------------------------------------------

    async def _dispatch_inject(self, fault_type: str, target: str, params: dict) -> dict:
        """Route to the correct injection tool."""
        if fault_type == "container_kill":
            return await docker_kill(target)
        elif fault_type == "container_stop":
            return await docker_stop(target, timeout=params.get("timeout", 0))
        elif fault_type == "container_pause":
            return await docker_pause(target)
        elif fault_type == "container_restart":
            return await docker_restart(target)
        elif fault_type == "network_latency":
            return await inject_latency(
                target, params["delay_ms"], params.get("jitter_ms", 0)
            )
        elif fault_type == "network_loss":
            return await inject_packet_loss(target, params["loss_pct"])
        elif fault_type == "network_corruption":
            return await inject_corruption(target, params["corrupt_pct"])
        elif fault_type == "network_bandwidth":
            return await inject_bandwidth_limit(target, params["rate_kbit"])
        elif fault_type == "network_partition":
            return await inject_partition(target, params["target_ip"])
        else:
            return {"success": False, "detail": f"Unknown fault type: {fault_type}"}

    async def _dispatch_verify(
        self, fault_type: str, target: str, params: dict, inject_result: dict
    ) -> dict:
        """Route to the correct verification tool."""
        if fault_type in ("container_kill", "container_stop"):
            return await verify_container_status(target, "exited")
        elif fault_type == "container_pause":
            return await verify_container_status(target, "paused")
        elif fault_type == "container_restart":
            return await verify_container_status(target, "running")
        elif fault_type in _NETWORK_FAULTS - {"network_partition"}:
            # Reuse the PID from injection to avoid race conditions.
            # verify_tc_* returns {"active": bool}, normalize to {"verified": bool}
            pid = inject_result.get("pid")
            if pid:
                r = await verify_tc_with_pid(pid)
            else:
                r = await verify_tc_active(target)
            return {"verified": r.get("active", False), "detail": r.get("detail", "")}
        elif fault_type == "network_partition":
            target_ip = params.get("target_ip", "")
            if target_ip:
                r = await verify_unreachable(target, target_ip)
                return {"verified": r["unreachable"], "detail": r["detail"]}
            return await verify_tc_active(target)
        else:
            return {"verified": False, "detail": f"No verifier for {fault_type}"}

    async def _run_live_impl(self, ctx):
        raise NotImplementedError
