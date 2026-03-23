"""Phase 2 Specialist: Subscriber Data — provisioning and database checks."""

from __future__ import annotations
from pathlib import Path
from google.adk.agents import LlmAgent
from .. import tools

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "subscriber_data_specialist.md"


def create_subscriber_data_specialist() -> LlmAgent:
    return LlmAgent(
        name="SubscriberDataSpecialist",
        model="gemini-2.5-flash",
        instruction=_PROMPT_PATH.read_text(),
        description="Checks subscriber provisioning in MongoDB (5G) and PyHSS (IMS).",
        output_key="finding_subscriber_data",
        tools=[
            tools.query_subscriber,
        ],
    )
