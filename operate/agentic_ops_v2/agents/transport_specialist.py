"""
Phase 2 Specialist: Transport — UDP/TCP transport layer checks.

Checks for transport mismatches (e.g., P-CSCF sending TCP, UE listening UDP).
Uses Gemini Flash — the checks are simple and targeted.
"""

from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

from .. import tools

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "transport_specialist.md"


def create_transport_specialist() -> LlmAgent:
    """Create the Transport Specialist agent."""
    return LlmAgent(
        name="TransportSpecialist",
        model="gemini-2.5-flash",
        instruction=_PROMPT_PATH.read_text(),
        description="Checks transport-layer issues: UDP vs TCP mismatches, listener state, MTU settings.",
        output_key="finding_transport",
        tools=[
            tools.read_running_config,
            tools.check_process_listeners,
            tools.run_kamcmd,
        ],
    )
