"""Unit tests for the scenario library — no Docker needed."""

import pytest

from agentic_chaos.models import BlastRadius, FaultCategory
from agentic_chaos.scenarios.library import (
    SCENARIOS,
    get_scenario,
    list_scenarios,
)


class TestScenarioLibrary:
    def test_has_10_scenarios(self):
        assert len(SCENARIOS) == 10

    def test_all_names_unique(self):
        names = list(SCENARIOS.keys())
        assert len(names) == len(set(names))

    def test_get_scenario_by_name(self):
        s = get_scenario("P-CSCF Latency")
        assert s.name == "P-CSCF Latency"
        assert s.category == FaultCategory.NETWORK

    def test_get_scenario_unknown_raises(self):
        with pytest.raises(KeyError, match="Unknown scenario"):
            get_scenario("Nonexistent Scenario")

    def test_list_scenarios_returns_all(self):
        items = list_scenarios()
        assert len(items) == 10
        assert all("name" in s for s in items)
        assert all("category" in s for s in items)

    def test_every_scenario_has_at_least_one_fault(self):
        for name, s in SCENARIOS.items():
            assert len(s.faults) >= 1, f"{name} has no faults"

    def test_every_scenario_has_description(self):
        for name, s in SCENARIOS.items():
            assert len(s.description) > 20, f"{name} has short description"

    def test_every_scenario_has_expected_symptoms(self):
        for name, s in SCENARIOS.items():
            assert len(s.expected_symptoms) >= 1, f"{name} has no expected symptoms"

    def test_every_fault_has_valid_type(self):
        valid_types = {
            "container_kill", "container_stop", "container_pause", "container_restart",
            "network_latency", "network_loss", "network_corruption",
            "network_bandwidth", "network_partition",
        }
        for name, s in SCENARIOS.items():
            for f in s.faults:
                assert f.fault_type in valid_types, (
                    f"{name}: unknown fault type '{f.fault_type}'"
                )

    def test_every_fault_target_is_known_container(self):
        from agentic_chaos.tools._common import ALL_CONTAINERS
        for name, s in SCENARIOS.items():
            for f in s.faults:
                assert f.target in ALL_CONTAINERS, (
                    f"{name}: unknown target '{f.target}'"
                )

    def test_network_latency_has_delay_param(self):
        for name, s in SCENARIOS.items():
            for f in s.faults:
                if f.fault_type == "network_latency":
                    assert "delay_ms" in f.params, f"{name}: latency missing delay_ms"
                    assert f.params["delay_ms"] > 0

    def test_network_loss_has_loss_param(self):
        for name, s in SCENARIOS.items():
            for f in s.faults:
                if f.fault_type == "network_loss":
                    assert "loss_pct" in f.params, f"{name}: loss missing loss_pct"
                    assert 0 < f.params["loss_pct"] <= 100

    def test_network_partition_has_target_ip(self):
        for name, s in SCENARIOS.items():
            for f in s.faults:
                if f.fault_type == "network_partition":
                    assert "target_ip" in f.params, f"{name}: partition missing target_ip"
                    # Validate IP format
                    import ipaddress
                    ipaddress.ip_address(f.params["target_ip"])

    def test_ttl_seconds_reasonable(self):
        for name, s in SCENARIOS.items():
            assert s.ttl_seconds >= 30, f"{name}: TTL too short"
            assert s.ttl_seconds <= 300, f"{name}: TTL too long"

    def test_blast_radius_categories(self):
        single = [s for s in SCENARIOS.values() if s.blast_radius == BlastRadius.SINGLE_NF]
        multi = [s for s in SCENARIOS.values() if s.blast_radius == BlastRadius.MULTI_NF]
        globe = [s for s in SCENARIOS.values() if s.blast_radius == BlastRadius.GLOBAL]

        assert len(single) >= 3, "Need at least 3 single-NF scenarios"
        assert len(multi) >= 2, "Need at least 2 multi-NF scenarios"
        assert len(globe) >= 1, "Need at least 1 global scenario"

    def test_cascading_failure_has_challenge_mode(self):
        s = get_scenario("Cascading IMS Failure")
        assert s.challenge_mode is True

    def test_pcscf_latency_has_escalation(self):
        s = get_scenario("P-CSCF Latency")
        assert s.escalation is True
