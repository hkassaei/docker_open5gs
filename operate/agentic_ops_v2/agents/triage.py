"""
Phase 0: Triage Agent — deterministic metrics collection + LLM oversight.

Always runs first. Produces a TriageReport that gates all subsequent phases.
Step 1: Deterministic metrics collection (no LLM)
Step 2: Deterministic classification
Step 3: LLM oversight if no anomaly found but user reports a problem
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from .. import tools

log = logging.getLogger("v2.triage")


class TriageAgent(BaseAgent):
    """Phase 0: collect metrics, classify health, LLM oversight for gray failures."""

    name: str = "TriageAgent"
    description: str = "Collects stack metrics and produces a structured health report."

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        log.info("Phase 0: Triage — collecting metrics...")

        # Step 1: Deterministic metrics collection
        env_config, net_status, nf_metrics = await asyncio.gather(
            tools.read_env_config(),
            tools.get_network_status(),
            tools.get_nf_metrics(),
        )

        # Parse network status
        try:
            status_data = json.loads(net_status)
        except (json.JSONDecodeError, TypeError):
            status_data = {"phase": "unknown", "containers": {}}

        stack_phase = status_data.get("phase", "unknown")

        # Step 2: Deterministic classification
        anomalies = []
        data_plane_status = "healthy"
        control_plane_status = "healthy"
        ims_status = "healthy"

        # Check for data plane issues in metrics text.
        # IMPORTANT: GTP packets = 0 is NORMAL when no data traffic is flowing
        # (UEs registered but no active calls/sessions generating traffic).
        # Only flag as "dead" if sessions > 0 AND packets = 0 — that means
        # sessions exist but no user-plane traffic is flowing.
        gtp_in_zero = False
        gtp_out_zero = False
        has_sessions = False

        for line in nf_metrics.splitlines():
            if "gtp_indatapktn3upf" in line and "= 0" in line:
                gtp_in_zero = True
            if "gtp_outdatapktn3upf" in line and "= 0" in line:
                gtp_out_zero = True
            if "upf_sessionnbr" in line:
                try:
                    val = float(line.split("=")[1].strip())
                    if val > 0:
                        has_sessions = True
                except (IndexError, ValueError):
                    pass

        if gtp_in_zero and gtp_out_zero and has_sessions:
            anomalies.append("GTP packets = 0 but UPF has active sessions (data plane not forwarding)")
            data_plane_status = "dead"
        elif gtp_in_zero and gtp_out_zero:
            # Zero packets with no sessions is normal idle state — NOT an anomaly
            pass

        # Check IMS stats
        if "registered_contacts" in nf_metrics:
            for line in nf_metrics.splitlines():
                if "registered_contacts" in line and "= 0" in line:
                    anomalies.append("P-CSCF registered contacts = 0")
                    ims_status = "degraded"

        # Check container status
        containers = status_data.get("containers", {})
        down = [c for c, s in containers.items() if s != "running"]
        if down:
            anomalies.append(f"Containers down: {', '.join(down)}")
            if any(c in down for c in ["amf", "smf", "upf"]):
                control_plane_status = "down"
            if any(c in down for c in ["pcscf", "icscf", "scscf", "pyhss"]):
                ims_status = "down"

        # Determine recommended next phase
        if data_plane_status == "dead":
            recommended = "data_plane_probe"
        elif ims_status == "down":
            recommended = "ims_analysis"
        else:
            recommended = "end_to_end_trace"

        # Step 3: LLM Oversight for gray failures
        llm_override = None
        if not anomalies and stack_phase in ("ready", "partial"):
            # Metrics look healthy but user is reporting a problem — ask LLM
            log.info("No anomalies detected — invoking LLM oversight for gray failures")
            llm_override = await self._llm_oversight(nf_metrics, stack_phase)

        triage = {
            "stack_phase": stack_phase,
            "data_plane_status": data_plane_status,
            "control_plane_status": control_plane_status,
            "ims_status": ims_status,
            "anomalies": anomalies,
            "metrics_summary": {"raw": nf_metrics[:2000]},  # Compact summary
            "recommended_next_phase": recommended,
        }

        if llm_override:
            triage["llm_oversight"] = llm_override
            # If LLM suggested specialists, note it in anomalies
            if llm_override.get("specialists"):
                triage["anomalies"].append(
                    f"LLM oversight suggests: {', '.join(llm_override['specialists'])}"
                )

        summary = (
            f"Phase={stack_phase}, DataPlane={data_plane_status}, "
            f"IMS={ims_status}, Anomalies={len(anomalies)}, "
            f"Next={recommended}"
        )
        log.info("Triage: %s", summary)

        yield Event(
            author=self.name,
            content=types.Content(parts=[types.Part(text=f"Triage complete: {summary}")]),
            actions=EventActions(state_delta={
                "triage": triage,
                "env_config": env_config,
            }),
        )

    async def _llm_oversight(self, metrics_text: str, phase: str) -> dict | None:
        """Ask a fast LLM if the healthy-looking metrics hide a subtle problem."""
        try:
            from google.genai import Client

            client = Client(vertexai=True)
            prompt = (
                f"The user reports a network problem, but the stack phase is '{phase}' "
                f"and no obvious metric anomalies were detected.\n\n"
                f"Metrics summary:\n{metrics_text[:1500]}\n\n"
                f"Which specialist agents should we dispatch to investigate? "
                f"Options: ims, transport, core, subscriber_data.\n"
                f"Respond with JSON: {{\"specialists\": [\"ims\", \"transport\"], "
                f"\"rationale\": \"reason\"}}"
            )

            response = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            text = response.text.strip()

            # Parse JSON from response (may be wrapped in markdown code block)
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            return json.loads(text)
        except Exception as e:
            log.warning("LLM oversight failed: %s", e)
            return None

    async def _run_live_impl(self, ctx):
        raise NotImplementedError
