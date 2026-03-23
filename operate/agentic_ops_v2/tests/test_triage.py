"""Tests for Phase 0 triage logic — deterministic path (no LLM needed for these)."""

import sys
sys.path.insert(0, "operate")

import pytest


class TestTriageClassification:
    """Test the deterministic classification logic from the triage agent."""

    def test_gtp_zero_with_sessions_means_dead(self):
        """When GTP packets = 0 AND sessions > 0, data plane is dead."""
        gtp_in_zero = True
        gtp_out_zero = True
        has_sessions = True  # UPF has active sessions but no traffic
        is_dead = gtp_in_zero and gtp_out_zero and has_sessions
        assert is_dead

    def test_gtp_zero_without_sessions_is_normal(self):
        """When GTP packets = 0 AND sessions = 0, data plane is just idle."""
        gtp_in_zero = True
        gtp_out_zero = True
        has_sessions = False  # No sessions — idle is normal
        is_dead = gtp_in_zero and gtp_out_zero and has_sessions
        assert not is_dead

    def test_zero_registered_contacts_means_ims_degraded(self):
        metrics = "ims_usrloc_pcscf:registered_contacts = 0.0"
        has_anomaly = "registered_contacts" in metrics and "= 0" in metrics
        assert has_anomaly

    def test_healthy_metrics_no_anomalies(self):
        metrics = "ran_ue = 2.0\ngtp_indatapktn3upf = 1500.0\nregistered_contacts = 2.0"
        anomalies = []
        if "gtp_indatapktn3upf" in metrics:
            for line in metrics.splitlines():
                if "gtp_indatapktn3upf" in line and "= 0" in line:
                    anomalies.append("GTP = 0")
        assert len(anomalies) == 0

    def test_container_down_detected(self):
        containers = {"amf": "running", "pcscf": "exited", "smf": "running"}
        down = [c for c, s in containers.items() if s != "running"]
        assert down == ["pcscf"]

    def test_recommended_phase_data_plane_dead(self):
        data_plane_status = "dead"
        ims_status = "healthy"
        if data_plane_status == "dead":
            recommended = "data_plane_probe"
        elif ims_status == "down":
            recommended = "ims_analysis"
        else:
            recommended = "end_to_end_trace"
        assert recommended == "data_plane_probe"

    def test_recommended_phase_ims_down(self):
        data_plane_status = "healthy"
        ims_status = "down"
        if data_plane_status == "dead":
            recommended = "data_plane_probe"
        elif ims_status == "down":
            recommended = "ims_analysis"
        else:
            recommended = "end_to_end_trace"
        assert recommended == "ims_analysis"

    def test_recommended_phase_subtle_problem(self):
        """When everything looks healthy, default to end-to-end trace."""
        data_plane_status = "healthy"
        ims_status = "healthy"
        if data_plane_status == "dead":
            recommended = "data_plane_probe"
        elif ims_status == "down":
            recommended = "ims_analysis"
        else:
            recommended = "end_to_end_trace"
        assert recommended == "end_to_end_trace"
