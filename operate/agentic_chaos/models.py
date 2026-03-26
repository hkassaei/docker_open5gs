"""
Pydantic models for the Agentic Chaos Monkey platform.

FaultSpec    — what to inject (intent)
Fault        — what was injected (record, stored in registry)
Baseline     — pre-fault metrics + status snapshot
Observation  — single poll iteration during symptom observation
Episode      — complete chaos episode: scenario → baseline → faults → observations → resolution
Scenario     — a named, reusable fault injection plan
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


# -------------------------------------------------------------------------
# Enums
# -------------------------------------------------------------------------

class FaultCategory(str, Enum):
    CONTAINER = "container"
    NETWORK = "network"
    APPLICATION = "application"
    COMPOUND = "compound"


class BlastRadius(str, Enum):
    SINGLE_NF = "single_nf"
    MULTI_NF = "multi_nf"
    GLOBAL = "global"


class FaultStatus(str, Enum):
    ACTIVE = "active"
    HEALED = "healed"
    EXPIRED = "expired"
    FAILED = "failed"


class Severity(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


# -------------------------------------------------------------------------
# Fault models
# -------------------------------------------------------------------------

class FaultSpec(BaseModel):
    """Intent: what fault to inject. Part of a Scenario definition."""

    fault_type: str
    """e.g. 'container_kill', 'network_latency', 'network_partition',
    'config_corruption', 'subscriber_deletion'."""

    target: str
    """Container name (e.g. 'pcscf', 'amf', 'mongo')."""

    params: dict = Field(default_factory=dict)
    """Type-specific parameters. Examples:
    - network_latency: {"delay_ms": 500, "jitter_ms": 50}
    - network_loss: {"loss_pct": 30}
    - network_partition: {"target_ip": "172.22.0.20"}
    - container_kill: {} (no extra params)
    """

    ttl_seconds: int = 120
    """Maximum fault lifetime. Safety net — auto-healed after this."""


class Fault(BaseModel):
    """Record: what was actually injected. Stored in the fault registry."""

    fault_id: str
    episode_id: str
    fault_type: str
    target: str
    params: dict = Field(default_factory=dict)
    mechanism: str
    """Exact command used to inject (for audit trail)."""

    heal_command: str
    """Exact command to reverse the fault."""

    injected_at: datetime
    ttl_seconds: int
    expires_at: datetime
    status: FaultStatus = FaultStatus.ACTIVE
    verified: bool = False
    verification_result: str = ""


# -------------------------------------------------------------------------
# Observation models
# -------------------------------------------------------------------------

class Baseline(BaseModel):
    """Pre-fault snapshot of the stack's health."""

    timestamp: datetime
    stack_phase: str
    """'ready', 'partial', or 'down'."""

    container_status: dict[str, str]
    """Container name → 'running'/'exited'/'absent'."""

    metrics: dict[str, dict]
    """Node ID → metrics dict (from MetricsCollector.collect())."""


class Observation(BaseModel):
    """A single symptom-observation poll iteration."""

    iteration: int
    timestamp: datetime
    elapsed_seconds: float
    metrics_delta: dict[str, dict] = Field(default_factory=dict)
    """Node ID → {metric_name: {baseline, current, delta}}."""

    log_samples: dict[str, list[str]] = Field(default_factory=dict)
    """Container → recent notable log lines."""

    symptoms_detected: bool = False
    escalation_level: int = 0


class Resolution(BaseModel):
    """How and when faults were healed."""

    healed_at: datetime
    heal_method: str
    """'scheduled', 'ttl_expired', 'emergency_shutdown', 'manual'."""

    post_heal_metrics: dict[str, dict] = Field(default_factory=dict)
    recovery_time_seconds: float = 0.0


class RcaLabel(BaseModel):
    """Ground-truth label for the injected fault — used as training signal."""

    root_cause: str
    affected_components: list[str]
    severity: Severity
    failure_domain: str
    """e.g. 'ims_registration', 'data_plane', '5g_attach', 'voice_call'."""

    protocol_impact: str
    """e.g. 'SIP', 'Diameter', 'GTP-U', 'NGAP', 'PFCP'."""


class ChallengeResult(BaseModel):
    """Scoring output when Challenge Mode evaluates the RCA agent."""

    rca_agent_model: str
    diagnosis_summary: str
    root_cause_correct: bool
    component_overlap: float
    """Jaccard similarity of affected_components vs ground truth."""

    severity_correct: bool
    time_to_diagnosis_seconds: float


# -------------------------------------------------------------------------
# Episode (the primary output product)
# -------------------------------------------------------------------------

class Episode(BaseModel):
    """A complete chaos episode — the primary output product of the platform."""

    schema_version: str = "1.0"
    episode_id: str
    timestamp: datetime
    duration_seconds: float = 0.0

    scenario: Scenario
    baseline: Baseline
    faults: list[Fault] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    resolution: Resolution | None = None
    rca_label: RcaLabel | None = None
    challenge_result: ChallengeResult | None = None


# -------------------------------------------------------------------------
# Scenario (reusable fault injection plan)
# -------------------------------------------------------------------------

class Scenario(BaseModel):
    """A named, reusable fault injection plan."""

    name: str
    description: str
    category: FaultCategory
    blast_radius: BlastRadius
    faults: list[FaultSpec]
    expected_symptoms: list[str] = Field(default_factory=list)
    escalation: bool = False
    """Enable adaptive escalation (Boiling Frog)?"""

    challenge_mode: bool = False
    """Run RCA agent after observation and score its diagnosis?"""

    requires_active_call: bool = False
    """Establish a VoNR call between UE1 and UE2 before fault injection?
    Required for data plane scenarios where traffic must be flowing."""

    observation_window_seconds: int = 30
    ttl_seconds: int = 120


# -------------------------------------------------------------------------
# Escalation schedules — not a model, just lookup constants
# -------------------------------------------------------------------------

ESCALATION_SCHEDULES: dict[str, list[dict]] = {
    "network_latency": [
        {"delay_ms": 100},
        {"delay_ms": 250},
        {"delay_ms": 500},
        {"delay_ms": 2000},
    ],
    "network_loss": [
        {"loss_pct": 5},
        {"loss_pct": 15},
        {"loss_pct": 30},
        {"loss_pct": 50},
    ],
    "network_bandwidth": [
        {"rate_kbit": 1000},
        {"rate_kbit": 500},
        {"rate_kbit": 100},
        {"rate_kbit": 10},
    ],
    "network_jitter": [
        {"jitter_ms": 20},
        {"jitter_ms": 50},
        {"jitter_ms": 100},
        {"jitter_ms": 500},
    ],
}
