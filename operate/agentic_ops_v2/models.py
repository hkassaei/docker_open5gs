"""
Data models for the v2 multi-agent troubleshooting system.

Each model corresponds to a phase output:
  Phase 0 → TriageReport
  Phase 1 → TraceResult
  Phase 2 → SubDiagnosis (per specialist)
  Phase 3 → Diagnosis (final, backward-compatible with v1)
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# -------------------------------------------------------------------------
# Phase 0: Triage
# -------------------------------------------------------------------------

class TriageReport(BaseModel):
    """Phase 0 output — structured health overview of the entire stack."""

    stack_phase: str
    """'ready' / 'partial' / 'down'."""

    data_plane_status: str
    """'healthy' / 'degraded' / 'dead'."""

    control_plane_status: str
    """'healthy' / 'degraded' / 'down'."""

    ims_status: str
    """'healthy' / 'degraded' / 'down'."""

    anomalies: list[str] = Field(default_factory=list)
    """Detected anomalies, e.g. ['GTP packets = 0', 'P-CSCF 0 registered contacts']."""

    metrics_summary: dict = Field(default_factory=dict)
    """Compact metrics keyed by NF name."""

    recommended_next_phase: str = "end_to_end_trace"
    """'end_to_end_trace' / 'data_plane_probe' / 'ims_analysis'."""


# -------------------------------------------------------------------------
# Phase 1: End-to-End Trace
# -------------------------------------------------------------------------

class TraceResult(BaseModel):
    """Phase 1 output — where the request stopped across the stack."""

    call_id: str
    """SIP Call-ID or transaction identifier extracted from UE logs."""

    request_type: str
    """'INVITE' / 'REGISTER' / 'BYE' / etc."""

    nodes_that_saw_it: list[str] = Field(default_factory=list)
    """Containers where the Call-ID appeared in logs."""

    nodes_that_did_not: list[str] = Field(default_factory=list)
    """Containers that should have seen the Call-ID but didn't."""

    failure_point: str = ""
    """Where the request stopped, e.g. 'between pcscf and e2e_ue2'."""

    error_messages: dict[str, str] = Field(default_factory=dict)
    """Container → error message found in logs for this Call-ID."""

    originating_ue: str = ""
    """Container name of the caller, e.g. 'e2e_ue1'."""

    terminating_ue: str = ""
    """Container name of the callee, e.g. 'e2e_ue2'."""


# -------------------------------------------------------------------------
# Phase 2: Specialist Findings
# -------------------------------------------------------------------------

class SubDiagnosis(BaseModel):
    """Phase 2 output — one specialist's finding with evidence."""

    specialist: str
    """'ims' / 'core' / 'transport' / 'subscriber_data'."""

    finding: str
    """One-line finding."""

    evidence: list[str] = Field(default_factory=list)
    """Specific log lines or config values supporting the finding."""

    raw_evidence_context: str = ""
    """10-20 raw log lines or full config block that led to the finding.
    Allows the Synthesis Agent to fact-check the specialist's interpretation."""

    root_cause_candidate: str = ""
    """Proposed root cause."""

    disconfirm_check: str = ""
    """What was checked to verify — what evidence would disprove this finding."""

    confidence: str = "low"
    """'high' / 'medium' / 'low'."""


# -------------------------------------------------------------------------
# Phase 3: Final Diagnosis (v1-compatible)
# -------------------------------------------------------------------------

class TimelineEvent(BaseModel):
    """A single event in the cross-container investigation timeline."""

    timestamp: str
    """Timestamp as it appeared in the logs."""

    container: str
    """Which container produced this event."""

    event: str
    """What happened, in plain English."""


class Diagnosis(BaseModel):
    """Final structured diagnosis — same schema as v1 for GUI compatibility."""

    summary: str
    """One-line summary of the issue."""

    timeline: list[TimelineEvent] = Field(default_factory=list)
    """Chronological events across containers that tell the story."""

    root_cause: str
    """What went wrong and why."""

    affected_components: list[str] = Field(default_factory=list)
    """Which containers/components are involved."""

    recommendation: str
    """What to do about it — actionable steps."""

    confidence: str = "low"
    """'high' / 'medium' / 'low'."""

    explanation: str = ""
    """Plain-English explanation geared toward a NOC engineer."""
