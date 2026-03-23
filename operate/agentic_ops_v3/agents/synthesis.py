"""Phase 3: Synthesis Agent — produces final diagnosis from all findings."""

from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "synthesis.md"


def create_synthesis_agent() -> LlmAgent:
    return LlmAgent(
        name="SynthesisAgent",
        model="gemini-2.5-pro",
        instruction=_PROMPT_PATH.read_text(),
        description="Synthesizes all findings into a final diagnosis for a NOC engineer.",
        output_key="diagnosis",
        tools=[],
    )
