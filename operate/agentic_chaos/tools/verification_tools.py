"""
Verification tools — confirm that injected faults actually took effect.

Every fault injection must be followed by a verification step:
  Target → Inject → Verify

These tools probe the network from inside a container's namespace to confirm
the fault is producing the expected effect.
"""

from __future__ import annotations

import logging
import re

from ._common import shell
from .docker_tools import docker_get_pid, docker_inspect_status

log = logging.getLogger("chaos-tools.verify")


# -------------------------------------------------------------------------
# Container status verification
# -------------------------------------------------------------------------

async def verify_container_status(
    container: str, expected: str
) -> dict:
    """Verify a container is in the expected state.

    Args:
        container: Container name.
        expected: Expected status ('running', 'exited', 'paused', 'absent').

    Returns:
        {verified: bool, expected, actual, detail}
    """
    actual = await docker_inspect_status(container)
    verified = actual == expected
    detail = f"Expected '{expected}', got '{actual}'"
    if not verified:
        log.warning("Verification failed for %s: %s", container, detail)
    return {
        "verified": verified,
        "expected": expected,
        "actual": actual,
        "detail": detail,
    }


# -------------------------------------------------------------------------
# Network latency verification
# -------------------------------------------------------------------------

async def verify_latency(
    container: str, target_ip: str, min_ms: float
) -> dict:
    """Verify that latency to a target IP meets a minimum threshold.

    Sends a single ICMP ping from inside the container's netns and checks
    the round-trip time.

    Args:
        container: Container name (source).
        target_ip: IP to ping.
        min_ms: Minimum expected RTT in milliseconds.

    Returns:
        {verified: bool, measured_ms: float | None, min_ms, detail}
    """
    pid = await docker_get_pid(container)
    if pid is None:
        return {
            "verified": False,
            "measured_ms": None,
            "min_ms": min_ms,
            "detail": f"Container '{container}' not running",
        }

    cmd = f"sudo nsenter -t {pid} -n ping -c 1 -W 3 {target_ip}"
    rc, output = await shell(cmd)

    measured_ms = _parse_ping_rtt(output)
    if measured_ms is None:
        return {
            "verified": False,
            "measured_ms": None,
            "min_ms": min_ms,
            "detail": f"Ping failed or unparseable: {output[:200]}",
        }

    verified = measured_ms >= min_ms
    detail = f"RTT {measured_ms:.1f}ms (expected >= {min_ms}ms)"
    return {
        "verified": verified,
        "measured_ms": measured_ms,
        "min_ms": min_ms,
        "detail": detail,
    }


# -------------------------------------------------------------------------
# Reachability verification
# -------------------------------------------------------------------------

async def verify_reachable(
    container: str, target_ip: str
) -> dict:
    """Verify that a target IP is reachable from a container.

    Args:
        container: Container name (source).
        target_ip: IP to ping.

    Returns:
        {reachable: bool, rtt_ms: float | None, detail}
    """
    pid = await docker_get_pid(container)
    if pid is None:
        return {
            "reachable": False,
            "rtt_ms": None,
            "detail": f"Container '{container}' not running",
        }

    cmd = f"sudo nsenter -t {pid} -n ping -c 1 -W 2 {target_ip}"
    rc, output = await shell(cmd)
    rtt = _parse_ping_rtt(output)

    return {
        "reachable": rc == 0 and rtt is not None,
        "rtt_ms": rtt,
        "detail": output.splitlines()[-1] if output else "no output",
    }


async def verify_unreachable(
    container: str, target_ip: str
) -> dict:
    """Verify that a target IP is NOT reachable (partition verification).

    Args:
        container: Container name (source).
        target_ip: IP to ping (should fail).

    Returns:
        {unreachable: bool, detail}
    """
    pid = await docker_get_pid(container)
    if pid is None:
        return {
            "unreachable": True,
            "detail": f"Container '{container}' not running — trivially unreachable",
        }

    cmd = f"sudo nsenter -t {pid} -n ping -c 1 -W 2 {target_ip}"
    rc, output = await shell(cmd)
    rtt = _parse_ping_rtt(output)

    unreachable = rc != 0 or rtt is None
    detail = "Unreachable (as expected)" if unreachable else f"Still reachable! RTT={rtt}ms"
    return {
        "unreachable": unreachable,
        "detail": detail,
    }


# -------------------------------------------------------------------------
# tc rule verification
# -------------------------------------------------------------------------

async def verify_tc_active(container: str) -> dict:
    """Verify that tc netem or tbf rules are active on a container's eth0.

    Args:
        container: Container name.

    Returns:
        {active: bool, qdisc_type: str | None, detail}
    """
    pid = await docker_get_pid(container)
    if pid is None:
        return {
            "active": False,
            "qdisc_type": None,
            "detail": f"Container '{container}' not running",
        }

    return await verify_tc_with_pid(pid)


async def verify_tc_with_pid(pid: int) -> dict:
    """Verify tc rules are active using a known PID (avoids re-resolving).

    Use this when you already have the PID from a recent injection to
    avoid race conditions with PID resolution.

    Args:
        pid: Container's main process PID.

    Returns:
        {active: bool, qdisc_type: str | None, detail}
    """
    if not isinstance(pid, int) or pid <= 0:
        return {
            "active": False,
            "qdisc_type": None,
            "detail": f"Invalid PID: {pid}",
        }

    cmd = f"sudo nsenter -t {pid} -n tc qdisc show dev eth0"
    rc, output = await shell(cmd)

    has_netem = "netem" in output
    has_tbf = "tbf" in output

    if has_netem:
        qdisc_type = "netem"
    elif has_tbf:
        qdisc_type = "tbf"
    else:
        qdisc_type = None

    return {
        "active": has_netem or has_tbf,
        "qdisc_type": qdisc_type,
        "detail": output,
    }


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

_PING_RTT_RE = re.compile(r"time[=<]\s*([\d.]+)\s*ms", re.IGNORECASE)


def _parse_ping_rtt(output: str) -> float | None:
    """Extract RTT in ms from ping output. Returns None on parse failure."""
    m = _PING_RTT_RE.search(output)
    if m:
        return float(m.group(1))
    return None
