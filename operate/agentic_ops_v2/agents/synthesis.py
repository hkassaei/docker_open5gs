"""
Phase 3: Synthesis Agent — merges findings into final Diagnosis.

Receives structured outputs from all previous phases, fact-checks specialist
interpretations against raw evidence context, and produces the final
Diagnosis (v1-compatible for GUI integration).
"""

from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "synthesis.md"


def create_synthesis_agent() -> LlmAgent:
    """Create the Phase 3 Synthesis agent."""
    return LlmAgent(
        name="SynthesisAgent",
        model="gemini-2.5-pro",
        instruction=_PROMPT_PATH.read_text(),
        description=(
            "Synthesizes triage, trace, and specialist findings into a final "
            "Diagnosis. Fact-checks specialist interpretations against raw evidence."
        ),
        output_key="diagnosis",
        tools=[],  # No tools — reasoning only
    )
