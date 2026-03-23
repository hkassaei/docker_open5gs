"""Unit tests for v2 data models — no Docker, no LLM needed."""

import sys
sys.path.insert(0, "operate")

from agentic_ops_v2.models import (
    Diagnosis,
    InvestigationTrace,
    PhaseTrace,
    SubDiagnosis,
    TimelineEvent,
    TokenBreakdown,
    ToolCallTrace,
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


class TestTokenBreakdown:
    def test_defaults_to_zero(self):
        tb = TokenBreakdown()
        assert tb.prompt == 0
        assert tb.completion == 0
        assert tb.thinking == 0
        assert tb.total == 0

    def test_populated(self):
        tb = TokenBreakdown(prompt=1000, completion=200, thinking=50, total=1250)
        assert tb.total == 1250


class TestToolCallTrace:
    def test_construction(self):
        tc = ToolCallTrace(
            name="read_container_logs",
            args='{"container":"pcscf","grep":"udp_mtu"}',
            result_size=245,
            timestamp=1000.5,
        )
        assert tc.name == "read_container_logs"
        assert tc.result_size == 245


class TestPhaseTrace:
    def test_defaults(self):
        p = PhaseTrace(agent_name="TestAgent")
        assert p.tokens.total == 0
        assert p.tool_calls == []
        assert p.llm_calls == 0
        assert p.state_keys_written == []

    def test_populated_phase(self):
        p = PhaseTrace(
            agent_name="TransportSpecialist",
            started_at=1000.0,
            finished_at=1006.2,
            duration_ms=6200,
            tokens=TokenBreakdown(prompt=35000, completion=3100, total=38100),
            tool_calls=[
                ToolCallTrace(name="read_running_config", args="{}", result_size=245),
                ToolCallTrace(name="check_process_listeners", args="{}", result_size=180),
            ],
            llm_calls=3,
            output_summary="Transport mismatch found.",
            state_keys_written=["finding_transport"],
        )
        assert p.agent_name == "TransportSpecialist"
        assert len(p.tool_calls) == 2
        assert p.tokens.prompt == 35000
        assert p.duration_ms == 6200

    def test_json_roundtrip(self):
        p = PhaseTrace(
            agent_name="IMSSpecialist",
            tokens=TokenBreakdown(prompt=10, completion=5, total=15),
            llm_calls=1,
        )
        data = p.model_dump_json()
        p2 = PhaseTrace.model_validate_json(data)
        assert p2.agent_name == "IMSSpecialist"
        assert p2.tokens.total == 15


class TestInvestigationTrace:
    def test_defaults(self):
        t = InvestigationTrace()
        assert t.phases == []
        assert t.invocation_chain == []
        assert t.total_tokens.total == 0

    def test_full_trace(self):
        t = InvestigationTrace(
            question="Why can't UE1 call UE2?",
            started_at=1000.0,
            finished_at=1047.4,
            duration_ms=47400,
            total_tokens=TokenBreakdown(prompt=200000, completion=78000, total=278000),
            phases=[
                PhaseTrace(agent_name="TriageAgent", duration_ms=800, tokens=TokenBreakdown(total=1204)),
                PhaseTrace(agent_name="EndToEndTracer", duration_ms=12300, tokens=TokenBreakdown(total=45200)),
                PhaseTrace(agent_name="DispatchAgent", duration_ms=1100, tokens=TokenBreakdown(total=3100)),
                PhaseTrace(agent_name="TransportSpecialist", duration_ms=6200, tokens=TokenBreakdown(total=38100)),
                PhaseTrace(agent_name="SynthesisAgent", duration_ms=9800, tokens=TokenBreakdown(total=91200)),
            ],
            invocation_chain=["TriageAgent", "EndToEndTracer", "DispatchAgent", "TransportSpecialist", "SynthesisAgent"],
        )
        assert len(t.phases) == 5
        assert t.invocation_chain[0] == "TriageAgent"
        assert t.duration_ms == 47400
        # Sum of phase tokens
        phase_total = sum(p.tokens.total for p in t.phases)
        assert phase_total == 1204 + 45200 + 3100 + 38100 + 91200

    def test_json_roundtrip(self):
        t = InvestigationTrace(
            question="test",
            phases=[PhaseTrace(agent_name="A", llm_calls=2)],
            invocation_chain=["A"],
        )
        data = t.model_dump_json()
        t2 = InvestigationTrace.model_validate_json(data)
        assert t2.phases[0].agent_name == "A"
        assert t2.phases[0].llm_calls == 2
