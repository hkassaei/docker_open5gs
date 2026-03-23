"""Phase 1: End-to-End Trace Agent — traces Call-ID across all containers."""

from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .. import tools

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "tracer.md"


def create_tracer_agent() -> LlmAgent:
    return LlmAgent(
        name="EndToEndTracer",
        model="gemini-2.5-flash",
        instruction=_PROMPT_PATH.read_text(),
        description="Traces a SIP Call-ID across all containers to find where the request stopped.",
        output_key="trace",
        tools=[
            tools.read_container_logs,
            tools.search_logs,
        ],
    )
