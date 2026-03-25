"""Unit tests for observation_tools — pure logic tests (no Docker)."""

from agentic_chaos.tools.observation_tools import compute_metrics_delta, determine_phase


class TestComputeMetricsDelta:
    def test_no_change_returns_empty(self):
        snapshot = {
            "amf": {"metrics": {"ran_ue": 2, "amf_session": 2}},
            "smf": {"metrics": {"sessions": 4}},
        }
        delta = compute_metrics_delta(snapshot, snapshot)
        assert delta == {}

    def test_detects_increase(self):
        baseline = {"amf": {"metrics": {"ran_ue": 2}}}
        current = {"amf": {"metrics": {"ran_ue": 4}}}
        delta = compute_metrics_delta(baseline, current)
        assert "amf" in delta
        assert delta["amf"]["ran_ue"]["baseline"] == 2
        assert delta["amf"]["ran_ue"]["current"] == 4
        assert delta["amf"]["ran_ue"]["delta"] == 2

    def test_detects_decrease(self):
        baseline = {"pcscf": {"metrics": {"active_transactions": 5}}}
        current = {"pcscf": {"metrics": {"active_transactions": 0}}}
        delta = compute_metrics_delta(baseline, current)
        assert delta["pcscf"]["active_transactions"]["delta"] == -5

    def test_ignores_underscore_keys(self):
        baseline = {"amf": {"metrics": {"_t": 1000, "ran_ue": 2}}}
        current = {"amf": {"metrics": {"_t": 2000, "ran_ue": 2}}}
        delta = compute_metrics_delta(baseline, current)
        assert delta == {}

    def test_ignores_non_numeric_values(self):
        baseline = {"amf": {"metrics": {"status": "ok", "ran_ue": 2}}}
        current = {"amf": {"metrics": {"status": "bad", "ran_ue": 2}}}
        delta = compute_metrics_delta(baseline, current)
        assert delta == {}

    def test_handles_missing_nodes(self):
        baseline = {"amf": {"metrics": {"ran_ue": 2}}}
        current = {"smf": {"metrics": {"sessions": 4}}}
        delta = compute_metrics_delta(baseline, current)
        # No overlapping metrics to compare
        assert delta == {}

    def test_handles_missing_metrics_key(self):
        baseline = {"amf": {"badge": "2 UE"}}  # No "metrics" key
        current = {"amf": {"metrics": {"ran_ue": 2}}}
        delta = compute_metrics_delta(baseline, current)
        assert delta == {}

    def test_multiple_nodes_with_changes(self):
        baseline = {
            "amf": {"metrics": {"ran_ue": 2}},
            "smf": {"metrics": {"sessions": 4}},
            "pcscf": {"metrics": {"transactions": 10}},
        }
        current = {
            "amf": {"metrics": {"ran_ue": 0}},     # Changed
            "smf": {"metrics": {"sessions": 4}},    # No change
            "pcscf": {"metrics": {"transactions": 15}},  # Changed
        }
        delta = compute_metrics_delta(baseline, current)
        assert "amf" in delta
        assert "smf" not in delta
        assert "pcscf" in delta


class TestDeterminePhase:
    def test_all_running_is_ready(self):
        statuses = {c: "running" for c in [
            "mongo", "nrf", "scp", "ausf", "udr", "udm", "amf", "smf", "upf",
            "pcf", "dns", "mysql", "pyhss", "icscf", "scscf", "pcscf", "rtpengine",
            "nr_gnb", "e2e_ue1", "e2e_ue2",
        ]}
        assert determine_phase(statuses) == "ready"

    def test_core_up_no_ues_is_partial(self):
        statuses = {c: "running" for c in [
            "mongo", "nrf", "scp", "ausf", "udr", "udm", "amf", "smf", "upf",
            "pcf", "dns", "mysql", "pyhss", "icscf", "scscf", "pcscf", "rtpengine",
            "nr_gnb",
        ]}
        statuses["e2e_ue1"] = "exited"
        statuses["e2e_ue2"] = "exited"
        assert determine_phase(statuses) == "partial"

    def test_core_nf_down_is_down(self):
        statuses = {c: "running" for c in [
            "mongo", "nrf", "scp", "ausf", "udr", "udm", "smf", "upf",
            "pcf", "dns", "mysql", "pyhss", "icscf", "scscf", "pcscf", "rtpengine",
        ]}
        statuses["amf"] = "exited"  # Core NF down
        assert determine_phase(statuses) == "down"

    def test_empty_statuses_is_down(self):
        assert determine_phase({}) == "down"
