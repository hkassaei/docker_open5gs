"""Unit tests for the Challenge Mode scorer — no Docker, no LLM needed."""

from agentic_chaos.scorer import (
    score_diagnosis,
    _extract_fault_keywords,
    _expected_severity,
    _infer_severity_from_diagnosis,
)


class TestScoreDiagnosis:
    def test_perfect_diagnosis(self):
        """RCA agent correctly identifies the root cause and components."""
        diagnosis = {
            "summary": "P-CSCF is down due to network latency",
            "root_cause": "The pcscf container has 500ms latency causing SIP timeouts",
            "affected_components": ["pcscf", "icscf", "scscf"],
            "confidence": "high",
            "explanation": "Latency on pcscf caused degraded SIP performance",
        }
        faults = [{"target": "pcscf", "fault_type": "network_latency"}]
        scenario = {"description": "Inject latency on P-CSCF"}

        score = score_diagnosis(diagnosis, faults, scenario)
        assert score["root_cause_correct"] is True
        assert score["component_overlap"] > 0  # pcscf is in both sets
        assert score["total_score"] > 0.5

    def test_wrong_root_cause(self):
        """RCA agent identifies wrong component."""
        diagnosis = {
            "summary": "AMF is having issues",
            "root_cause": "The amf is not processing NAS messages correctly",
            "affected_components": ["amf", "smf"],
            "confidence": "high",
            "explanation": "AMF failure",
        }
        faults = [{"target": "pcscf", "fault_type": "network_latency"}]
        scenario = {"description": "Inject latency on P-CSCF"}

        score = score_diagnosis(diagnosis, faults, scenario)
        assert score["root_cause_correct"] is False
        assert score["component_overlap"] == 0.0
        assert score["total_score"] < 0.3

    def test_partial_component_match(self):
        """RCA agent gets some components right, misses others."""
        diagnosis = {
            "root_cause": "pcscf has connectivity issues",
            "affected_components": ["pcscf", "amf", "smf"],
            "confidence": "medium",
        }
        faults = [{"target": "pcscf", "fault_type": "container_kill"}]
        scenario = {}

        score = score_diagnosis(diagnosis, faults, scenario)
        assert score["root_cause_correct"] is True
        # Jaccard: {pcscf} ∩ {pcscf, amf, smf} = {pcscf}, union = 3 → 1/3
        assert 0.3 <= score["component_overlap"] <= 0.4

    def test_multi_fault_scoring(self):
        """Scoring with multiple injected faults."""
        diagnosis = {
            "root_cause": "pyhss is down and scscf has latency issues",
            "affected_components": ["pyhss", "scscf", "icscf"],
            "confidence": "high",
        }
        faults = [
            {"target": "pyhss", "fault_type": "container_kill"},
            {"target": "scscf", "fault_type": "network_latency"},
        ]
        scenario = {}

        score = score_diagnosis(diagnosis, faults, scenario)
        assert score["root_cause_correct"] is True
        # Truth: {pyhss, scscf}, RCA: {pyhss, scscf, icscf} → overlap = 2/3
        assert score["component_overlap"] > 0.6

    def test_empty_diagnosis(self):
        """Handle an empty/minimal diagnosis gracefully."""
        diagnosis = {"root_cause": "", "affected_components": [], "confidence": "low"}
        faults = [{"target": "dns", "fault_type": "container_kill"}]
        scenario = {}

        score = score_diagnosis(diagnosis, faults, scenario)
        assert score["root_cause_correct"] is False
        assert score["component_overlap"] == 0.0
        assert score["total_score"] < 0.2

    def test_confidence_calibration_high_correct(self):
        """High confidence + correct = well calibrated."""
        diagnosis = {
            "root_cause": "dns container is killed",
            "affected_components": ["dns"],
            "confidence": "high",
        }
        faults = [{"target": "dns", "fault_type": "container_kill"}]
        score = score_diagnosis(diagnosis, faults, {})
        assert score["confidence_calibrated"] is True

    def test_confidence_calibration_high_wrong(self):
        """High confidence + wrong = poorly calibrated."""
        diagnosis = {
            "root_cause": "amf is the issue",
            "affected_components": ["amf"],
            "confidence": "high",
        }
        faults = [{"target": "dns", "fault_type": "container_kill"}]
        score = score_diagnosis(diagnosis, faults, {})
        assert score["confidence_calibrated"] is False

    def test_confidence_calibration_low_wrong(self):
        """Low confidence + wrong = actually well calibrated (knows it doesn't know)."""
        diagnosis = {
            "root_cause": "unclear",
            "affected_components": ["amf"],
            "confidence": "low",
        }
        faults = [{"target": "dns", "fault_type": "container_kill"}]
        score = score_diagnosis(diagnosis, faults, {})
        assert score["confidence_calibrated"] is True


class TestFaultKeywords:
    def test_kill_keywords(self):
        kw = _extract_fault_keywords([{"fault_type": "container_kill"}])
        assert "kill" in kw
        assert "crash" in kw
        assert "down" in kw

    def test_latency_keywords(self):
        kw = _extract_fault_keywords([{"fault_type": "network_latency"}])
        assert "latency" in kw
        assert "timeout" in kw

    def test_partition_keywords(self):
        kw = _extract_fault_keywords([{"fault_type": "network_partition"}])
        assert "partition" in kw
        assert "unreachable" in kw

    def test_multiple_faults(self):
        kw = _extract_fault_keywords([
            {"fault_type": "container_kill"},
            {"fault_type": "network_latency"},
        ])
        assert "kill" in kw
        assert "latency" in kw


class TestSeverityInference:
    def test_kill_is_down(self):
        assert _expected_severity([{"fault_type": "container_kill"}]) == "down"

    def test_stop_is_down(self):
        assert _expected_severity([{"fault_type": "container_stop"}]) == "down"

    def test_latency_is_degraded(self):
        assert _expected_severity([{"fault_type": "network_latency"}]) == "degraded"

    def test_pause_is_degraded(self):
        assert _expected_severity([{"fault_type": "container_pause"}]) == "degraded"

    def test_infer_down_from_text(self):
        d = {"root_cause": "Container is dead", "summary": "", "explanation": ""}
        assert _infer_severity_from_diagnosis(d) == "down"

    def test_infer_degraded_from_text(self):
        d = {"root_cause": "High latency on SIP path", "summary": "", "explanation": ""}
        assert _infer_severity_from_diagnosis(d) == "degraded"

    def test_infer_healthy_from_bland_text(self):
        d = {"root_cause": "Everything looks fine", "summary": "", "explanation": ""}
        assert _infer_severity_from_diagnosis(d) == "healthy"
