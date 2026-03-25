"""
Network fault injection tools — latency, packet loss, corruption, bandwidth, partition.

All network faults use `nsenter` from the host to enter the container's network
namespace. This requires `sudo` access to nsenter (configured via sudoers).

Every mutating function returns a dict with:
  - success: bool
  - heal_cmd: str (command to reverse the fault)
  - mechanism: str (exact command that was executed)
  - pid: int (container PID used for nsenter)
  - detail: str (stdout/stderr from the command)
"""

from __future__ import annotations

import logging

from ._common import shell, validate_container, validate_ip
from .docker_tools import docker_get_pid

log = logging.getLogger("chaos-tools.network")


async def _resolve_pid(container: str) -> int:
    """Get container PID or raise."""
    pid = await docker_get_pid(container)
    if pid is None:
        raise RuntimeError(f"Cannot get PID for container '{container}' — not running?")
    return pid


def _nsenter(pid: int) -> str:
    """Build the nsenter prefix for a container's network namespace."""
    if not isinstance(pid, int) or pid <= 0:
        raise ValueError(f"Invalid PID: {pid}")
    return f"sudo nsenter -t {pid} -n"


# -------------------------------------------------------------------------
# Latency
# -------------------------------------------------------------------------

async def inject_latency(
    container: str, delay_ms: int, jitter_ms: int = 0
) -> dict:
    """Add network latency to a container's eth0 interface.

    Args:
        container: Container name.
        delay_ms: Delay in milliseconds (1-100000).
        jitter_ms: Optional jitter in milliseconds.

    Returns:
        {success, mechanism, heal_cmd, pid, detail}
    """
    validate_container(container)
    delay_ms = int(delay_ms)
    jitter_ms = int(jitter_ms)
    if delay_ms <= 0 or delay_ms > 100000:
        raise ValueError(f"delay_ms must be 1-100000, got {delay_ms}")

    pid = await _resolve_pid(container)
    ns = _nsenter(pid)

    jitter_part = f" {jitter_ms}ms" if jitter_ms > 0 else ""
    mechanism = f"{ns} tc qdisc add dev eth0 root netem delay {delay_ms}ms{jitter_part}"
    heal_cmd = f"{ns} tc qdisc del dev eth0 root"

    rc, output = await shell(mechanism)
    return {
        "success": rc == 0,
        "mechanism": mechanism,
        "heal_cmd": heal_cmd,
        "pid": pid,
        "detail": output,
    }


async def inject_packet_loss(container: str, loss_pct: float) -> dict:
    """Add packet loss to a container's eth0 interface.

    Args:
        container: Container name.
        loss_pct: Percentage of packets to drop (0.1-100).

    Returns:
        {success, mechanism, heal_cmd, pid, detail}
    """
    validate_container(container)
    loss_pct = float(loss_pct)
    if loss_pct <= 0 or loss_pct > 100:
        raise ValueError(f"loss_pct must be 0.1-100, got {loss_pct}")

    pid = await _resolve_pid(container)
    ns = _nsenter(pid)

    mechanism = f"{ns} tc qdisc add dev eth0 root netem loss {loss_pct}%"
    heal_cmd = f"{ns} tc qdisc del dev eth0 root"

    rc, output = await shell(mechanism)
    return {
        "success": rc == 0,
        "mechanism": mechanism,
        "heal_cmd": heal_cmd,
        "pid": pid,
        "detail": output,
    }


async def inject_corruption(container: str, corrupt_pct: float) -> dict:
    """Add packet corruption to a container's eth0 interface.

    Args:
        container: Container name.
        corrupt_pct: Percentage of packets to corrupt (0.1-100).

    Returns:
        {success, mechanism, heal_cmd, pid, detail}
    """
    validate_container(container)
    corrupt_pct = float(corrupt_pct)
    if corrupt_pct <= 0 or corrupt_pct > 100:
        raise ValueError(f"corrupt_pct must be 0.1-100, got {corrupt_pct}")

    pid = await _resolve_pid(container)
    ns = _nsenter(pid)

    mechanism = f"{ns} tc qdisc add dev eth0 root netem corrupt {corrupt_pct}%"
    heal_cmd = f"{ns} tc qdisc del dev eth0 root"

    rc, output = await shell(mechanism)
    return {
        "success": rc == 0,
        "mechanism": mechanism,
        "heal_cmd": heal_cmd,
        "pid": pid,
        "detail": output,
    }


async def inject_bandwidth_limit(container: str, rate_kbit: int) -> dict:
    """Limit outbound bandwidth on a container's eth0 interface.

    Args:
        container: Container name.
        rate_kbit: Rate limit in kbit/s (1-1000000).

    Returns:
        {success, mechanism, heal_cmd, pid, detail}
    """
    validate_container(container)
    rate_kbit = int(rate_kbit)
    if rate_kbit <= 0 or rate_kbit > 1000000:
        raise ValueError(f"rate_kbit must be 1-1000000, got {rate_kbit}")

    pid = await _resolve_pid(container)
    ns = _nsenter(pid)

    burst = max(rate_kbit // 10, 1)  # burst ≈ 10% of rate, minimum 1kbit
    mechanism = (
        f"{ns} tc qdisc add dev eth0 root tbf "
        f"rate {rate_kbit}kbit burst {burst}kbit latency 400ms"
    )
    heal_cmd = f"{ns} tc qdisc del dev eth0 root"

    rc, output = await shell(mechanism)
    return {
        "success": rc == 0,
        "mechanism": mechanism,
        "heal_cmd": heal_cmd,
        "pid": pid,
        "detail": output,
    }


# -------------------------------------------------------------------------
# Network partition (iptables)
# -------------------------------------------------------------------------

async def inject_partition(container: str, target_ip: str) -> dict:
    """Create a network partition — drop all traffic between container and target IP.

    Args:
        container: Container name.
        target_ip: IP address to block (e.g. '172.22.0.20').

    Returns:
        {success, mechanism, heal_cmd, pid, detail}
    """
    validate_container(container)
    validate_ip(target_ip)

    pid = await _resolve_pid(container)
    ns = _nsenter(pid)

    # Block both directions
    cmd_out = f"{ns} iptables -A OUTPUT -d {target_ip} -j DROP"
    cmd_in = f"{ns} iptables -A INPUT -s {target_ip} -j DROP"
    mechanism = f"{cmd_out} && {cmd_in}"

    heal_out = f"{ns} iptables -D OUTPUT -d {target_ip} -j DROP"
    heal_in = f"{ns} iptables -D INPUT -s {target_ip} -j DROP"
    heal_cmd = f"{heal_out} && {heal_in}"

    rc, output = await shell(mechanism)
    return {
        "success": rc == 0,
        "mechanism": mechanism,
        "heal_cmd": heal_cmd,
        "pid": pid,
        "detail": output,
    }


# -------------------------------------------------------------------------
# Heal / clear
# -------------------------------------------------------------------------

async def clear_tc_rules(container: str) -> dict:
    """Remove all tc queueing disciplines from a container's eth0.

    Args:
        container: Container name.

    Returns:
        {success, mechanism, detail}
    """
    pid = await _resolve_pid(container)
    ns = _nsenter(pid)
    mechanism = f"{ns} tc qdisc del dev eth0 root"
    rc, output = await shell(mechanism)
    # rc != 0 is expected when there are no rules to delete
    no_rules = (
        "RTNETLINK answers: No such file" in output
        or "Cannot delete qdisc with handle of zero" in output
    )
    return {
        "success": rc == 0 or no_rules,
        "mechanism": mechanism,
        "detail": output,
    }


async def show_tc_rules(container: str) -> str:
    """Show current tc queueing disciplines on a container's eth0.

    Args:
        container: Container name.

    Returns:
        tc qdisc show output as string.
    """
    pid = await _resolve_pid(container)
    ns = _nsenter(pid)
    _, output = await shell(f"{ns} tc -s qdisc show dev eth0")
    return output
