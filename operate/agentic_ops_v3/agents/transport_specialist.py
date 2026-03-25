"""Phase 2 Specialist: Transport — UDP/TCP transport layer checks."""

from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .. import tools

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "transport_specialist.md"


def create_transport_specialist() -> LlmAgent:
    return LlmAgent(
        name="TransportSpecialist",
        model="gemini-2.5-flash",
        instruction=_PROMPT_PATH.read_text(),
        description="Checks transport-layer issues: UDP vs TCP mismatches, listener state, MTU settings.",
        output_key="finding_transport",
        tools=[
            tools.check_tc_rules,
            tools.measure_rtt,
            tools.read_running_config,
            tools.check_process_listeners,
            tools.run_kamcmd,
        ],
    )
