"""Unit tests for agentic_chaos.models — no Docker, no network, pure logic."""

from datetime import datetime, timezone, timedelta

import pytest

from agentic_chaos.models import (
    BlastRadius,
    ChallengeResult,
    Episode,
    Fault,
    FaultCategory,
    FaultSpec,
    FaultStatus,
    Baseline,
    Observation,
    Resolution,
    RcaLabel,
    Scenario,
    Severity,
    ESCALATION_SCHEDULES,
)


# -------------------------------------------------------------------------
# FaultSpec
# -------------------------------------------------------------------------

class TestFaultSpec:
    def test_minimal_construction(self):
        fs = FaultSpec(fault_type="container_kill", target="amf")
        assert fs.fault_type == "container_kill"
        assert fs.target == "amf"
        assert fs.params == {}
        assert fs.ttl_seconds == 120

    def test_with_params(self):
        fs = FaultSpec(
            fault_type="network_latency",
            target="pcscf",
            params={"delay_ms": 500, "jitter_ms": 50},
            ttl_seconds=60,
        )
        assert fs.params["delay_ms"] == 500
        assert fs.ttl_seconds == 60

    def test_json_roundtrip(self):
        fs = FaultSpec(fault_type="network_loss", target="upf", params={"loss_pct": 30})
        data = fs.model_dump_json()
        fs2 = FaultSpec.model_validate_json(data)
        assert fs2 == fs


# -------------------------------------------------------------------------
# Fault
# -------------------------------------------------------------------------

class TestFault:
    @pytest.fixture
    def sample_fault(self):
        now = datetime.now(timezone.utc)
        return Fault(
            fault_id="f_001",
            episode_id="ep_test",
            fault_type="network_latency",
            target="pcscf",
            params={"delay_ms": 500},
            mechanism="sudo nsenter -t 123 -n tc qdisc add dev eth0 root netem delay 500ms",
            heal_command="sudo nsenter -t 123 -n tc qdisc del dev eth0 root",
            injected_at=now,
            ttl_seconds=120,
            expires_at=now + timedelta(seconds=120),
        )

    def test_default_status_is_active(self, sample_fault):
        assert sample_fault.status == FaultStatus.ACTIVE

    def test_default_not_verified(self, sample_fault):
        assert sample_fault.verified is False
        assert sample_fault.verification_result == ""

    def test_json_roundtrip(self, sample_fault):
        data = sample_fault.model_dump_json()
        f2 = Fault.model_validate_json(data)
        assert f2.fault_id == sample_fault.fault_id
        assert f2.status == FaultStatus.ACTIVE

    def test_expires_at_is_future(self, sample_fault):
        assert sample_fault.expires_at > sample_fault.injected_at


# -------------------------------------------------------------------------
# Scenario
# -------------------------------------------------------------------------

class TestScenario:
    def test_construction(self):
        s = Scenario(
            name="P-CSCF Latency",
            description="Inject 500ms latency on P-CSCF",
            category=FaultCategory.NETWORK,
            blast_radius=BlastRadius.SINGLE_NF,
            faults=[
                FaultSpec(fault_type="network_latency", target="pcscf",
                          params={"delay_ms": 500}),
            ],
            expected_symptoms=["SIP REGISTER timeout"],
        )
        assert s.name == "P-CSCF Latency"
        assert len(s.faults) == 1
        assert s.escalation is False
        assert s.challenge_mode is False

    def test_compound_scenario(self):
        s = Scenario(
            name="Cascading IMS Failure",
            description="Kill HSS + add latency to S-CSCF",
            category=FaultCategory.COMPOUND,
            blast_radius=BlastRadius.MULTI_NF,
            faults=[
                FaultSpec(fault_type="container_kill", target="pyhss"),
                FaultSpec(fault_type="network_latency", target="scscf",
                          params={"delay_ms": 2000}),
            ],
            expected_symptoms=["Diameter timeout", "IMS registration failure"],
            challenge_mode=True,
        )
        assert len(s.faults) == 2
        assert s.challenge_mode is True

    def test_json_roundtrip(self):
        s = Scenario(
            name="Test",
            description="test",
            category=FaultCategory.CONTAINER,
            blast_radius=BlastRadius.GLOBAL,
            faults=[FaultSpec(fault_type="container_kill", target="mongo")],
        )
        data = s.model_dump_json()
        s2 = Scenario.model_validate_json(data)
        assert s2.name == s.name
        assert s2.faults[0].target == "mongo"


# -------------------------------------------------------------------------
# Baseline / Observation / Resolution
# -------------------------------------------------------------------------

class TestBaseline:
    def test_construction(self):
        b = Baseline(
            timestamp=datetime.now(timezone.utc),
            stack_phase="ready",
            container_status={"amf": "running", "pcscf": "running"},
            metrics={"amf": {"ran_ue": 2}},
        )
        assert b.stack_phase == "ready"
        assert b.container_status["amf"] == "running"


class TestObservation:
    def test_defaults(self):
        o = Observation(
            iteration=1,
            timestamp=datetime.now(timezone.utc),
            elapsed_seconds=5.0,
        )
        assert o.symptoms_detected is False
        assert o.escalation_level == 0
        assert o.metrics_delta == {}
        assert o.log_samples == {}


class TestResolution:
    def test_construction(self):
        r = Resolution(
            healed_at=datetime.now(timezone.utc),
            heal_method="scheduled",
            recovery_time_seconds=12.0,
        )
        assert r.heal_method == "scheduled"


# -------------------------------------------------------------------------
# Episode (full assembly)
# -------------------------------------------------------------------------

class TestEpisode:
    def test_full_episode_construction(self):
        now = datetime.now(timezone.utc)
        scenario = Scenario(
            name="Test",
            description="test",
            category=FaultCategory.NETWORK,
            blast_radius=BlastRadius.SINGLE_NF,
            faults=[FaultSpec(fault_type="network_latency", target="pcscf",
                              params={"delay_ms": 500})],
        )
        baseline = Baseline(
            timestamp=now,
            stack_phase="ready",
            container_status={"pcscf": "running"},
            metrics={"pcscf": {"tmx:active_transactions": 0}},
        )
        fault = Fault(
            fault_id="f_001", episode_id="ep_001",
            fault_type="network_latency", target="pcscf",
            params={"delay_ms": 500},
            mechanism="tc qdisc add ...",
            heal_command="tc qdisc del ...",
            injected_at=now, ttl_seconds=120,
            expires_at=now + timedelta(seconds=120),
            verified=True,
            verification_result="RTT 523ms",
        )
        obs = Observation(
            iteration=1, timestamp=now, elapsed_seconds=5.0,
            symptoms_detected=True,
        )
        resolution = Resolution(
            healed_at=now + timedelta(seconds=60),
            heal_method="scheduled",
            recovery_time_seconds=12.0,
        )
        rca = RcaLabel(
            root_cause="P-CSCF latency causing SIP timeouts",
            affected_components=["pcscf", "icscf"],
            severity=Severity.DEGRADED,
            failure_domain="ims_registration",
            protocol_impact="SIP",
        )

        ep = Episode(
            episode_id="ep_001",
            timestamp=now,
            duration_seconds=63.0,
            scenario=scenario,
            baseline=baseline,
            faults=[fault],
            observations=[obs],
            resolution=resolution,
            rca_label=rca,
        )

        assert ep.schema_version == "1.0"
        assert ep.episode_id == "ep_001"
        assert len(ep.faults) == 1
        assert ep.faults[0].verified is True
        assert ep.resolution.heal_method == "scheduled"
        assert ep.challenge_result is None

    def test_episode_json_roundtrip(self):
        now = datetime.now(timezone.utc)
        ep = Episode(
            episode_id="ep_rt",
            timestamp=now,
            scenario=Scenario(
                name="RT Test", description="roundtrip",
                category=FaultCategory.CONTAINER,
                blast_radius=BlastRadius.SINGLE_NF,
                faults=[FaultSpec(fault_type="container_kill", target="dns")],
            ),
            baseline=Baseline(
                timestamp=now, stack_phase="ready",
                container_status={}, metrics={},
            ),
        )
        data = ep.model_dump_json()
        ep2 = Episode.model_validate_json(data)
        assert ep2.episode_id == "ep_rt"
        assert ep2.scenario.name == "RT Test"


# -------------------------------------------------------------------------
# Escalation schedules
# -------------------------------------------------------------------------

class TestEscalationSchedules:
    def test_all_types_present(self):
        assert "network_latency" in ESCALATION_SCHEDULES
        assert "network_loss" in ESCALATION_SCHEDULES
        assert "network_bandwidth" in ESCALATION_SCHEDULES
        assert "network_jitter" in ESCALATION_SCHEDULES

    def test_schedules_are_monotonic(self):
        """Latency and jitter should increase, bandwidth should decrease."""
        lat = [s["delay_ms"] for s in ESCALATION_SCHEDULES["network_latency"]]
        assert lat == sorted(lat), f"Latency not monotonically increasing: {lat}"

        loss = [s["loss_pct"] for s in ESCALATION_SCHEDULES["network_loss"]]
        assert loss == sorted(loss), f"Loss not monotonically increasing: {loss}"

        bw = [s["rate_kbit"] for s in ESCALATION_SCHEDULES["network_bandwidth"]]
        assert bw == sorted(bw, reverse=True), f"Bandwidth not monotonically decreasing: {bw}"

    def test_each_schedule_has_at_least_3_levels(self):
        for name, schedule in ESCALATION_SCHEDULES.items():
            assert len(schedule) >= 3, f"{name} has only {len(schedule)} levels"


# -------------------------------------------------------------------------
# Enums
# -------------------------------------------------------------------------

class TestEnums:
    def test_fault_category_values(self):
        assert FaultCategory.CONTAINER.value == "container"
        assert FaultCategory.COMPOUND.value == "compound"

    def test_blast_radius_values(self):
        assert BlastRadius.SINGLE_NF.value == "single_nf"
        assert BlastRadius.GLOBAL.value == "global"

    def test_fault_status_values(self):
        assert FaultStatus.ACTIVE.value == "active"
        assert FaultStatus.HEALED.value == "healed"
        assert FaultStatus.EXPIRED.value == "expired"
        assert FaultStatus.FAILED.value == "failed"
