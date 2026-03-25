"""
Tool wrappers for v3 agents — reuses all 11 tools from agentic_ops v1.5
with output truncation to prevent context bloat.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Setup import path for agentic_ops
_REPO_ROOT = Path(__file__).resolve().parents[2]
_OPS_PATH = str(_REPO_ROOT / "operate")
if _OPS_PATH not in sys.path:
    sys.path.insert(0, _OPS_PATH)

from agentic_ops import tools as _t
from agentic_ops.models import AgentDeps

# -------------------------------------------------------------------------
# Output truncation
# -------------------------------------------------------------------------

_MAX_OUTPUT_BYTES = 10_240  # 10 KB


def _truncate_output(text: str, max_bytes: int = _MAX_OUTPUT_BYTES) -> str:
    """Keep the tail (most recent lines), discard oldest lines from the top.

    Docker logs are chronological — the most recent entries at the bottom are
    the ones relevant to the failure. Truncation preserves the tail and cuts
    at the nearest line boundary.
    """
    if len(text.encode("utf-8")) <= max_bytes:
        return text

    lines = text.splitlines(keepends=True)

    # Walk backward from the end, accumulating lines
    kept: list[str] = []
    total = 0
    for line in reversed(lines):
        line_bytes = len(line.encode("utf-8"))
        if total + line_bytes > max_bytes:
            break
        kept.append(line)
        total += line_bytes

    kept.reverse()
    omitted = len(lines) - len(kept)
    prefix = f"... truncated ({omitted} older lines omitted). Use grep to narrow your search.\n"
    return prefix + "".join(kept)


# -------------------------------------------------------------------------
# Module-level deps (loaded once, cached)
# -------------------------------------------------------------------------

_deps: AgentDeps | None = None


def _get_deps() -> AgentDeps:
    global _deps
    if _deps is not None:
        return _deps

    env: dict[str, str] = {**os.environ}
    for p in [_REPO_ROOT / ".env", _REPO_ROOT / "operate" / "e2e.env"]:
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()

    _deps = AgentDeps(
        repo_root=_REPO_ROOT,
        env=env,
        pyhss_api=f"http://{env.get('PYHSS_IP', '172.22.0.18')}:8080",
    )
    return _deps


# -------------------------------------------------------------------------
# Tool wrappers — each is ADK LlmAgent compatible
# -------------------------------------------------------------------------

async def read_container_logs(container: str, tail: int = 200, grep: str | None = None) -> str:
    """Read recent logs from a Docker container.

    Args:
        container: Container name (e.g. 'pcscf', 'scscf', 'e2e_ue1', 'amf').
        tail: Number of recent lines to return (default 200).
        grep: Optional pattern to filter log lines (case-insensitive).
    """
    result = await _t.read_container_logs(_get_deps(), container, tail, grep)
    if not grep:
        return _truncate_output(result)
    return result


async def read_config(component: str) -> str:
    """Read the configuration file for a network component from the repo.

    Args:
        component: One of: amf, smf, upf, pcscf, scscf, icscf, pyhss,
                   dns, dns-ims-zone, ueransim-gnb, ueransim-ue.
    """
    return await _t.read_config(_get_deps(), component)


async def get_network_status() -> str:
    """Get the status of all network containers (running/exited/absent).

    Returns JSON with phase ('ready'/'partial'/'down') and per-container status.
    """
    return await _t.get_network_status(_get_deps())


async def query_subscriber(imsi: str, domain: str = "both") -> str:
    """Query subscriber data from 5G core (MongoDB) and/or IMS (PyHSS).

    Args:
        imsi: The subscriber's IMSI (e.g. '001011234567891').
        domain: 'core' for 5G only, 'ims' for IMS only, 'both' for both.
    """
    return await _t.query_subscriber(_get_deps(), imsi, domain)


async def read_env_config() -> str:
    """Read network topology, IPs, PLMN, and UE credentials from environment files.

    Call this to discover the live topology: IPs, subscriber identities, IMS domain.
    """
    return await _t.read_env_config(_get_deps())


async def search_logs(pattern: str, containers: list[str] | None = None, since: str | None = None) -> str:
    """Search for a pattern across multiple container logs.

    Args:
        pattern: Search pattern (case-insensitive). Can be a Call-ID,
                 IMSI, SIP method, error keyword, etc.
        containers: Optional list of containers to search. Searches all if None.
        since: Optional time filter (e.g. '5m', '1h').
    """
    result = await _t.search_logs(_get_deps(), pattern, containers, since)
    return _truncate_output(result)


async def query_prometheus(query: str) -> str:
    """Query Prometheus for 5G core NF metrics using PromQL.

    Args:
        query: PromQL query string.
    """
    return await _t.query_prometheus(_get_deps(), query)


async def get_nf_metrics() -> str:
    """Get a full metrics snapshot across ALL network functions in one call.

    Collects from Prometheus (5G core), kamcmd (IMS Kamailio), RTPEngine,
    PyHSS, and MongoDB. This is the 'radiograph' — a quick health overview
    of the entire stack.
    """
    return await _t.get_nf_metrics(_get_deps())


async def run_kamcmd(container: str, command: str) -> str:
    """Run a kamcmd command inside a Kamailio container to inspect runtime state.

    Args:
        container: Kamailio container ('pcscf', 'icscf', or 'scscf').
        command: kamcmd command. Examples:
            - cdp.list_peers — Diameter peer connections and state
            - ulscscf.showimpu sip:imsi@domain — S-CSCF registration lookup
            - stats.get_statistics all — all stats
    """
    return await _t.run_kamcmd(_get_deps(), container, command)


async def read_running_config(container: str, grep: str | None = None) -> str:
    """Read the ACTUAL config from a running container (not the repo copy).

    Args:
        container: Container name (pcscf, icscf, scscf, amf, smf, upf).
        grep: Optional pattern to filter config lines (case-insensitive).
              ALWAYS use grep to avoid dumping entire config files.
    """
    return await _t.read_running_config(_get_deps(), container, grep)


async def check_process_listeners(container: str) -> str:
    """Check what ports and protocols a container's processes are listening on.

    Args:
        container: Container name (e.g. 'e2e_ue1', 'pcscf', 'scscf').
    """
    return await _t.check_process_listeners(_get_deps(), container)


async def check_tc_rules(container: str) -> str:
    """Check for active traffic control (tc) rules on a container's network interface.

    CRITICAL: Call this FIRST on any container showing timeouts. Detects
    injected latency (netem delay), packet loss (netem loss), bandwidth
    limits (tbf), or corruption. If netem/tbf rules are present, they are
    the root cause — do not investigate application-layer issues.

    Args:
        container: Container name (e.g. 'pcscf', 'upf', 'scscf').
    """
    return await _t.check_tc_rules(_get_deps(), container)


async def measure_rtt(container: str, target_ip: str) -> str:
    """Measure round-trip time (RTT) from a container to a target IP.

    Normal Docker bridge RTT is <1ms. Elevated RTT (>10ms) indicates
    injected latency or congestion. Use to confirm tc netem faults.

    Args:
        container: Source container name (e.g. 'pcscf', 'icscf').
        target_ip: Target IP address to ping (e.g. '172.22.0.19').
    """
    return await _t.measure_rtt(_get_deps(), container, target_ip)
