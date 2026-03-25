"""
Functional tests — hit the live Docker stack.

These tests inject real faults, verify them, and heal them.
Skipped automatically if the stack is not running.

Run with: pytest tests/test_functional.py -v
"""

import asyncio

import pytest

from .conftest import requires_stack

from agentic_chaos.tools.docker_tools import (
    docker_get_pid,
    docker_inspect_status,
    docker_pause,
    docker_unpause,
)
from agentic_chaos.tools.network_tools import (
    clear_tc_rules,
    inject_bandwidth_limit,
    inject_corruption,
    inject_latency,
    inject_packet_loss,
    inject_partition,
    show_tc_rules,
)
from agentic_chaos.tools.verification_tools import (
    verify_container_status,
    verify_latency,
    verify_tc_with_pid,
    verify_reachable,
    verify_tc_active,
    verify_unreachable,
)
from agentic_chaos.tools.observation_tools import (
    compute_blast_radius,
    determine_phase,
    snapshot_container_status,
    snapshot_logs,
    snapshot_metrics,
)


# Use dns container for all fault tests — low-risk, not in the critical path
SAFE_TARGET = "dns"


# =========================================================================
# Docker tools
# =========================================================================

@requires_stack
class TestDockerToolsFunctional:
    @pytest.mark.asyncio
    async def test_inspect_running_container(self):
        status = await docker_inspect_status("amf")
        assert status == "running"

    @pytest.mark.asyncio
    async def test_inspect_absent_container(self):
        status = await docker_inspect_status("this_container_does_not_exist_xyz")
        assert status == "absent"

    @pytest.mark.asyncio
    async def test_get_pid_returns_positive_int(self):
        pid = await docker_get_pid("amf")
        assert isinstance(pid, int)
        assert pid > 0

    @pytest.mark.asyncio
    async def test_get_pid_absent_returns_none(self):
        pid = await docker_get_pid("this_container_does_not_exist_xyz")
        assert pid is None

    @pytest.mark.asyncio
    async def test_pause_unpause_cycle(self):
        """Pause a container, verify it's paused, then unpause."""
        result = await docker_pause(SAFE_TARGET)
        assert result["success"], f"Pause failed: {result['detail']}"

        try:
            v = await verify_container_status(SAFE_TARGET, "paused")
            assert v["verified"], f"Expected paused, got {v['actual']}"
        finally:
            # Always unpause, even if verification fails
            heal = await docker_unpause(SAFE_TARGET)
            assert heal["success"], f"Unpause failed: {heal['detail']}"

        # Verify it's running again
        v2 = await verify_container_status(SAFE_TARGET, "running")
        assert v2["verified"], f"Expected running after unpause, got {v2['actual']}"


# =========================================================================
# Network tools
# =========================================================================

@requires_stack
class TestNetworkToolsFunctional:
    @pytest.mark.asyncio
    async def test_inject_latency_and_heal(self):
        """Full cycle: inject latency → verify tc active → heal → verify clean."""
        result = await inject_latency(SAFE_TARGET, delay_ms=100, jitter_ms=10)
        assert result["success"], f"Inject failed: {result['detail']}"

        try:
            tc = await verify_tc_active(SAFE_TARGET)
            assert tc["active"], "tc netem not active after injection"
            assert tc["qdisc_type"] == "netem"
        finally:
            heal = await clear_tc_rules(SAFE_TARGET)
            assert heal["success"], f"Heal failed: {heal['detail']}"

        tc2 = await verify_tc_active(SAFE_TARGET)
        assert not tc2["active"], "tc rules still active after heal"

    @pytest.mark.asyncio
    async def test_inject_packet_loss_and_heal(self):
        result = await inject_packet_loss(SAFE_TARGET, loss_pct=10)
        assert result["success"], f"Inject failed: {result['detail']}"

        try:
            tc = await verify_tc_active(SAFE_TARGET)
            assert tc["active"]
            assert "netem" in tc["detail"]
            assert "loss" in tc["detail"]
        finally:
            await clear_tc_rules(SAFE_TARGET)

    @pytest.mark.asyncio
    async def test_show_tc_rules(self):
        """Inject then show rules to verify human-readable output."""
        await inject_latency(SAFE_TARGET, delay_ms=50)
        try:
            output = await show_tc_rules(SAFE_TARGET)
            assert "netem" in output
            assert "delay" in output
        finally:
            await clear_tc_rules(SAFE_TARGET)

    @pytest.mark.asyncio
    async def test_clear_on_clean_interface_is_safe(self):
        """Clearing tc on an interface with no rules should not error."""
        result = await clear_tc_rules(SAFE_TARGET)
        # "No such file" is expected when there's nothing to delete — still success
        assert result["success"]

    @pytest.mark.asyncio
    async def test_inject_corruption_and_heal(self):
        """Inject packet corruption, verify tc active, heal."""
        result = await inject_corruption(SAFE_TARGET, corrupt_pct=5)
        assert result["success"], f"Inject failed: {result['detail']}"

        try:
            tc = await verify_tc_active(SAFE_TARGET)
            assert tc["active"]
            assert "corrupt" in tc["detail"]
        finally:
            await clear_tc_rules(SAFE_TARGET)

    @pytest.mark.asyncio
    async def test_inject_bandwidth_limit_and_heal(self):
        """Inject bandwidth limit (tbf), verify tc active, heal."""
        result = await inject_bandwidth_limit(SAFE_TARGET, rate_kbit=100)
        assert result["success"], f"Inject failed: {result['detail']}"

        try:
            tc = await verify_tc_active(SAFE_TARGET)
            assert tc["active"]
            assert tc["qdisc_type"] == "tbf"
        finally:
            await clear_tc_rules(SAFE_TARGET)

    @pytest.mark.asyncio
    async def test_inject_partition_and_heal(self):
        """Inject iptables partition, verify unreachable, heal."""
        # Partition dns from mysql (172.22.0.17)
        target_ip = "172.22.0.17"
        result = await inject_partition(SAFE_TARGET, target_ip)
        assert result["success"], f"Inject failed: {result['detail']}"

        try:
            # Verify dns cannot reach mysql
            from agentic_chaos.tools.verification_tools import verify_unreachable
            v = await verify_unreachable(SAFE_TARGET, target_ip)
            assert v["unreachable"], f"Expected unreachable: {v['detail']}"
        finally:
            # Heal: remove iptables rules
            from agentic_chaos.tools._common import shell
            pid = result["pid"]
            ns = f"sudo nsenter -t {pid} -n"
            await shell(f"{ns} iptables -D OUTPUT -d {target_ip} -j DROP")
            await shell(f"{ns} iptables -D INPUT -s {target_ip} -j DROP")

        # Verify reachable again after heal
        v2 = await verify_reachable(SAFE_TARGET, target_ip)
        assert v2["reachable"], f"Still unreachable after heal: {v2['detail']}"

    @pytest.mark.asyncio
    async def test_verify_tc_with_pid(self):
        """verify_tc_with_pid uses a known PID instead of re-resolving."""
        from agentic_chaos.tools.docker_tools import docker_get_pid
        pid = await docker_get_pid(SAFE_TARGET)
        assert pid is not None

        # Clean state — no tc rules
        result = await verify_tc_with_pid(pid)
        assert not result["active"]

        # Inject and verify with same PID
        await inject_latency(SAFE_TARGET, delay_ms=100)
        try:
            result = await verify_tc_with_pid(pid)
            assert result["active"]
            assert result["qdisc_type"] == "netem"
        finally:
            await clear_tc_rules(SAFE_TARGET)

    @pytest.mark.asyncio
    async def test_invalid_container_raises(self):
        """Injecting on an unknown container should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown container"):
            await inject_latency("totally_fake_container", delay_ms=100)

    @pytest.mark.asyncio
    async def test_invalid_ip_raises(self):
        """Partition with an invalid IP should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid IP"):
            await inject_partition(SAFE_TARGET, "not-an-ip")

    @pytest.mark.asyncio
    async def test_invalid_delay_raises(self):
        """Negative delay should raise ValueError."""
        with pytest.raises(ValueError, match="delay_ms must be"):
            await inject_latency(SAFE_TARGET, delay_ms=-1)


# =========================================================================
# Verification tools
# =========================================================================

@requires_stack
class TestVerificationToolsFunctional:
    @pytest.mark.asyncio
    async def test_verify_running_container(self):
        result = await verify_container_status("amf", "running")
        assert result["verified"]

    @pytest.mark.asyncio
    async def test_verify_wrong_status_fails(self):
        result = await verify_container_status("amf", "exited")
        assert not result["verified"]
        assert result["actual"] == "running"

    @pytest.mark.asyncio
    async def test_reachability_between_containers(self):
        """P-CSCF should be able to reach I-CSCF."""
        result = await verify_reachable("pcscf", "172.22.0.20")
        assert result["reachable"]
        assert result["rtt_ms"] is not None
        assert result["rtt_ms"] < 50  # Should be sub-ms on a Docker bridge

    @pytest.mark.asyncio
    async def test_latency_verification_with_injection(self):
        """Inject 200ms, verify ping RTT exceeds 150ms."""
        await inject_latency(SAFE_TARGET, delay_ms=200)
        try:
            # Ping from dns to mysql (172.22.0.17)
            result = await verify_latency(SAFE_TARGET, "172.22.0.17", min_ms=150)
            assert result["verified"], f"Expected RTT >= 150ms, got {result['measured_ms']}ms"
            assert result["measured_ms"] >= 150
        finally:
            await clear_tc_rules(SAFE_TARGET)


# =========================================================================
# Observation tools
# =========================================================================

@requires_stack
class TestObservationToolsFunctional:
    @pytest.mark.asyncio
    async def test_snapshot_metrics(self):
        metrics = await snapshot_metrics()
        assert isinstance(metrics, dict)
        assert len(metrics) > 0
        # Should have at least AMF if Prometheus is up
        if "amf" in metrics:
            assert "metrics" in metrics["amf"]

    @pytest.mark.asyncio
    async def test_snapshot_container_status(self):
        statuses = await snapshot_container_status()
        assert "amf" in statuses
        assert statuses["amf"] == "running"
        assert len(statuses) >= 17  # At least core containers

    @pytest.mark.asyncio
    async def test_determine_phase_on_live_stack(self):
        statuses = await snapshot_container_status()
        phase = determine_phase(statuses)
        assert phase in ("ready", "partial", "down")

    @pytest.mark.asyncio
    async def test_snapshot_logs(self):
        logs = await snapshot_logs(containers=["amf", "pcscf"], tail=10)
        assert "amf" in logs
        assert "pcscf" in logs
        assert isinstance(logs["amf"], list)

    @pytest.mark.asyncio
    async def test_blast_radius_pcscf(self):
        impact = await compute_blast_radius("pcscf")
        assert impact["node"] == "pcscf"
        assert "affected_nodes" in impact
        assert len(impact["affected_nodes"]) > 0
        # P-CSCF connects to icscf, scscf, rtpengine, pcf, UEs, dns, mysql
        assert "icscf" in impact["affected_nodes"]

    @pytest.mark.asyncio
    async def test_blast_radius_unknown_node(self):
        impact = await compute_blast_radius("nonexistent_node_xyz")
        assert impact["node"] == "nonexistent_node_xyz"
        assert len(impact["affected_nodes"]) == 0


# =========================================================================
# Integration: full inject → observe → heal cycle
# =========================================================================

@requires_stack
class TestFullCycleFunctional:
    @pytest.mark.asyncio
    async def test_latency_inject_observe_heal(self):
        """End-to-end: baseline → inject → observe delta → heal → verify clean."""
        from agentic_chaos.tools.observation_tools import compute_metrics_delta

        # 1. Baseline
        baseline_status = await snapshot_container_status()
        assert determine_phase(baseline_status) in ("ready", "partial")

        # 2. Inject 200ms latency on dns
        inject = await inject_latency(SAFE_TARGET, delay_ms=200)
        assert inject["success"]

        try:
            # 3. Verify injection
            tc = await verify_tc_active(SAFE_TARGET)
            assert tc["active"]

            # 4. Verify latency effect
            lat = await verify_latency(SAFE_TARGET, "172.22.0.17", min_ms=150)
            assert lat["verified"]

        finally:
            # 5. Heal
            await clear_tc_rules(SAFE_TARGET)

        # 6. Verify clean
        tc_after = await verify_tc_active(SAFE_TARGET)
        assert not tc_after["active"]

        # 7. Stack still healthy
        post_status = await snapshot_container_status()
        assert determine_phase(post_status) in ("ready", "partial")
