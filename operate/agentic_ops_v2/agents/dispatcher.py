"""
Phase 2 Router: Strategic Dispatch — LLM-driven specialist selection.

Reads the triage report and trace result from session state, then uses
Gemini Flash to decide which specialist agents to dispatch.
"""

from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "dispatcher.md"


def create_dispatch_agent() -> LlmAgent:
    """Create the Phase 2 Dispatch agent."""
    return LlmAgent(
        name="DispatchAgent",
        model="gemini-2.5-flash",
        instruction=_PROMPT_PATH.read_text(),
        description="Decides which specialist agents to dispatch based on triage and trace findings.",
        output_key="dispatch",
        tools=[],
    )
