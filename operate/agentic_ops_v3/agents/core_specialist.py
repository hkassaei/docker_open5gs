"""Phase 2 Specialist: Core NF — 5G core network function analysis."""

from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .. import tools

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "core_specialist.md"


def create_core_specialist() -> LlmAgent:
    return LlmAgent(
        name="CoreSpecialist",
        model="gemini-2.5-pro",
        instruction=_PROMPT_PATH.read_text(),
        description="Investigates 5G core NF failures: AMF, SMF, UPF, PFCP, GTP-U.",
        output_key="finding_core",
        tools=[
            tools.read_running_config,
        ],
    )
