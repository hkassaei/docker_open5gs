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


# -------------------------------------------------------------------------
# Investigation Trace (observability)
# -------------------------------------------------------------------------

class TokenBreakdown(BaseModel):
    """Token usage split by category for a single agent."""

    prompt: int = 0
    """Input tokens (context sent to the LLM)."""

    completion: int = 0
    """Output tokens (LLM response)."""

    thinking: int = 0
    """Reasoning/thinking tokens (Gemini extended thinking)."""

    total: int = 0
    """Sum of all token types."""


class ToolCallTrace(BaseModel):
    """Record of a single tool invocation by an agent."""

    name: str
    """Tool function name, e.g. 'read_container_logs'."""

    args: str = ""
    """Stringified arguments (truncated for display)."""

    result_size: int = 0
    """Character count of the tool's return value."""

    timestamp: float = 0.0


class PhaseTrace(BaseModel):
    """Observability record for one agent's execution within the pipeline."""

    agent_name: str
    """The agent that ran, e.g. 'TriageAgent', 'IMSSpecialist'."""

    started_at: float = 0.0
    finished_at: float = 0.0

    duration_ms: int = 0
    """Wall-clock duration in milliseconds."""

    tokens: TokenBreakdown = Field(default_factory=TokenBreakdown)

    tool_calls: list[ToolCallTrace] = Field(default_factory=list)

    llm_calls: int = 0
    """Number of LLM round-trips this agent made."""

    output_summary: str = ""
    """First 500 chars of the agent's text output."""

    state_keys_written: list[str] = Field(default_factory=list)
    """Session state keys this agent wrote to."""


class InvestigationTrace(BaseModel):
    """Full observability trace for a multi-agent investigation run."""

    question: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    duration_ms: int = 0

    total_tokens: TokenBreakdown = Field(default_factory=TokenBreakdown)

    phases: list[PhaseTrace] = Field(default_factory=list)
    """Ordered list of agent executions."""

    invocation_chain: list[str] = Field(default_factory=list)
    """Ordered agent names as they were invoked."""
