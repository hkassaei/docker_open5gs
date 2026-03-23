"""Unit tests for v2 data models — no Docker, no LLM needed."""

import sys
sys.path.insert(0, "operate")

from agentic_ops_v2.models import (
    Diagnosis,
    SubDiagnosis,
    TimelineEvent,
    TraceResult,
    TriageReport,
)


class TestTriageReport:
    def test_defaults(self):
        t = TriageReport(
            stack_phase="ready",
            data_plane_status="healthy",
            control_plane_status="healthy",
            ims_status="healthy",
        )
        assert t.anomalies == []
        assert t.recommended_next_phase == "end_to_end_trace"

    def test_with_anomalies(self):
        t = TriageReport(
            stack_phase="partial",
            data_plane_status="dead",
            control_plane_status="healthy",
            ims_status="degraded",
            anomalies=["GTP packets = 0", "P-CSCF 0 contacts"],
        )
        assert len(t.anomalies) == 2

    def test_json_roundtrip(self):
        t = TriageReport(
            stack_phase="ready",
            data_plane_status="healthy",
            control_plane_status="healthy",
            ims_status="healthy",
        )
        data = t.model_dump_json()
        t2 = TriageReport.model_validate_json(data)
        assert t2.stack_phase == "ready"


class TestTraceResult:
    def test_construction(self):
        tr = TraceResult(
            call_id="abc123",
            request_type="INVITE",
            nodes_that_saw_it=["e2e_ue1", "pcscf", "scscf"],
            nodes_that_did_not=["e2e_ue2"],
            failure_point="between pcscf and e2e_ue2",
            error_messages={"icscf": "500 Server error"},
            originating_ue="e2e_ue1",
            terminating_ue="e2e_ue2",
        )
        assert "e2e_ue2" in tr.nodes_that_did_not
        assert tr.failure_point == "between pcscf and e2e_ue2"

    def test_defaults(self):
        tr = TraceResult(call_id="x", request_type="REGISTER")
        assert tr.nodes_that_saw_it == []
        assert tr.failure_point == ""


class TestSubDiagnosis:
    def test_with_evidence(self):
        sd = SubDiagnosis(
            specialist="transport",
            finding="P-CSCF sends TCP, UE listens UDP only",
            evidence=["udp_mtu_try_proto = TCP", "UNCONN 192.168.101.7:5060"],
            raw_evidence_context="133:udp_mtu = 1300\n136:udp_mtu_try_proto = TCP",
            root_cause_candidate="Transport mismatch",
            disconfirm_check="If UE has a TCP listener, this hypothesis is wrong",
            confidence="high",
        )
        assert sd.raw_evidence_context != ""
        assert sd.confidence == "high"

    def test_defaults(self):
        sd = SubDiagnosis(specialist="ims", finding="No issues found")
        assert sd.confidence == "low"
        assert sd.raw_evidence_context == ""


class TestDiagnosis:
    def test_v1_compatible(self):
        """Diagnosis should have the same fields as v1."""
        d = Diagnosis(
            summary="Call fails due to TCP transport mismatch",
            timeline=[
                TimelineEvent(timestamp="17:25:35", container="pcscf", event="INVITE sent via TCP"),
            ],
            root_cause="udp_mtu_try_proto=TCP on P-CSCF",
            affected_components=["pcscf"],
            recommendation="Set udp_mtu_try_proto=UDP",
            confidence="high",
            explanation="The P-CSCF sends large SIP messages via TCP...",
        )
        assert d.summary != ""
        assert len(d.timeline) == 1
        assert d.timeline[0].container == "pcscf"

    def test_json_roundtrip(self):
        d = Diagnosis(
            summary="test",
            root_cause="test",
            recommendation="test",
            confidence="low",
        )
        data = d.model_dump_json()
        d2 = Diagnosis.model_validate_json(data)
        assert d2.summary == "test"
