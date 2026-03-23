"""
Phase 2 Specialist: IMS — SIP/Diameter/Kamailio analysis.

Investigates P-CSCF, I-CSCF, S-CSCF, and PyHSS around the failure point.
Uses Gemini Pro for protocol-level reasoning about SIP and Diameter.
"""

from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

from .. import tools

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "ims_specialist.md"


def create_ims_specialist() -> LlmAgent:
    """Create the IMS Specialist agent."""
    return LlmAgent(
        name="IMSSpecialist",
        model="gemini-2.5-pro",
        instruction=_PROMPT_PATH.read_text(),
        description="Investigates IMS/SIP signaling failures in P-CSCF, I-CSCF, S-CSCF, and PyHSS.",
        output_key="finding_ims",
        tools=[
            tools.run_kamcmd,
            tools.read_running_config,
        ],
    )
