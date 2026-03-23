"""Phase 2 Specialist: IMS — SIP/Diameter/Kamailio analysis."""

from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .. import tools

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "ims_specialist.md"


def create_ims_specialist() -> LlmAgent:
    return LlmAgent(
        name="IMSSpecialist",
        model="gemini-2.5-pro",
        instruction=_PROMPT_PATH.read_text(),
        description="Investigates IMS/SIP signaling failures.",
        output_key="finding_ims",
        tools=[
            tools.run_kamcmd,
            tools.read_running_config,
        ],
    )
