"""
Pydantic models and dependency types for the Telecom Troubleshooting Agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Agent dependencies — injected into every tool via RunContext
# ---------------------------------------------------------------------------

@dataclass
class AgentDeps:
    """Shared dependencies available to all agent tools."""

    repo_root: Path
    """Path to the docker_open5gs repository root."""

    env: dict[str, str]
    """Merged environment variables from .env and e2e.env."""

    all_containers: list[str] = field(default_factory=lambda: [
        "mongo", "nrf", "scp", "ausf", "udr", "udm", "amf", "smf", "upf",
        "pcf", "dns", "mysql", "pyhss", "icscf", "scscf", "pcscf", "rtpengine",
        "nr_gnb", "e2e_ue1", "e2e_ue2",
    ])
    """All known container names in the stack."""

    pyhss_api: str = "http://localhost:8080"
    """PyHSS REST API base URL."""


# ---------------------------------------------------------------------------
# Structured output — what the agent produces
# ---------------------------------------------------------------------------

class TimelineEvent(BaseModel):
    """A single event in the cross-container investigation timeline."""

    timestamp: str
    """Timestamp as it appeared in the logs (not normalized)."""

    container: str
    """Which container produced this event."""

    event: str
    """What happened, in plain English."""


class Diagnosis(BaseModel):
    """Structured diagnosis produced by the agent."""

    summary: str
    """One-line summary of the issue."""

    timeline: list[TimelineEvent]
    """Chronological events across containers that tell the story."""

    root_cause: str
    """What went wrong and why."""

    affected_components: list[str]
    """Which containers/components are involved."""

    recommendation: str
    """What to do about it — actionable steps."""

    confidence: str
    """'high', 'medium', or 'low'."""

    explanation: str
    """Plain-English educational explanation for a telecom learner."""
