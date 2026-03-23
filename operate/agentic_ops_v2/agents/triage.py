"""
Phase 0: Triage Agent — LLM-driven stack health assessment.

Always runs first. Uses Gemini Flash with metrics/status tools to assess
stack health, identify anomalies, and recommend next investigation phases.
"""

from __future__ import annotations

from pathlib import Path

from google.adk.agents import LlmAgent

from .. import tools

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "triage.md"


def create_triage_agent() -> LlmAgent:
    """Create the Phase 0 Triage agent."""
    return LlmAgent(
        name="TriageAgent",
        model="gemini-2.5-flash",
        instruction=_PROMPT_PATH.read_text(),
        description="Collects stack metrics, assesses health, and recommends next investigation phases.",
        output_key="triage",
        tools=[
            tools.get_network_status,
            tools.get_nf_metrics,
            tools.read_env_config,
            tools.query_prometheus,
        ],
    )
