"""Phase 2: Strategic Dispatch — LLM-driven specialist selection."""

from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "dispatcher.md"


def create_dispatch_agent() -> LlmAgent:
    return LlmAgent(
        name="DispatchAgent",
        model="gemini-2.5-flash",
        instruction=_PROMPT_PATH.read_text(),
        description="Decides which specialist agents to dispatch based on triage and trace findings.",
        output_key="dispatch",
        tools=[],
    )
