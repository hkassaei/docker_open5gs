"""
Tool implementations for the Telecom Troubleshooting Agent.

Each tool is an async function that receives RunContext[AgentDeps] and returns
data for the LLM to reason about. Tools shell out to Docker CLI for container
access and read files from the repository for configuration.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from .models import AgentDeps

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_MAX_OUTPUT_LINES = 500


async def _shell(cmd: str, cwd: str | None = None) -> tuple[int, str]:
    """Run a shell command and return (returncode, combined output)."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode or 0, stdout.decode(errors="replace")


def _truncate(text: str, max_lines: int = _MAX_OUTPUT_LINES) -> str:
    """Truncate output if it exceeds max_lines, with a warning."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    truncated = lines[:max_lines]
    truncated.append(f"\n... truncated ({len(lines) - max_lines} more lines). Refine your query to see more specific results.")
    return "\n".join(truncated)


# Config file paths relative to repo root, keyed by component name.
_CONFIG_PATHS: dict[str, str] = {
    "amf": "amf/amf.yaml",
    "smf": "smf/smf.yaml",
    "upf": "upf/upf.yaml",
    "pcscf": "pcscf/pcscf.cfg",
    "scscf": "scscf/scscf.cfg",
    "icscf": "icscf/icscf.cfg",
    "pyhss": "pyhss/config.yaml",
    "dns": "dns/named.conf",
    "dns-ims-zone": "dns/ims_zone",
    "ueransim-gnb": "ueransim/ueransim-gnb.yaml",
    "ueransim-ue": "ueransim/ueransim-ue.yaml",
}


# ---------------------------------------------------------------------------
# Tool 1: read_container_logs
# ---------------------------------------------------------------------------

async def read_container_logs(
    deps: AgentDeps,
    container: str,
    tail: int = 200,
    grep: str | None = None,
) -> str:
    """Read recent logs from a Docker container.

    Args:
        deps: Agent dependencies.
        container: Container name (e.g. 'pcscf', 'scscf', 'e2e_ue1', 'amf').
        tail: Number of recent lines to return (default 200).
        grep: Optional pattern to filter log lines (case-insensitive).

    Returns:
        The log output as a string. Error message if container not found.
    """
    if container not in deps.all_containers:
        return f"Unknown container '{container}'. Known containers: {', '.join(deps.all_containers)}"

    cmd = f"docker logs --tail {tail} {container} 2>&1"
    if grep:
        cmd += f" | grep -i -- {_shell_quote(grep)}"

    rc, output = await _shell(cmd)
    if rc != 0 and "No such container" in output:
        return f"Container '{container}' not found (not running or does not exist)."

    return _truncate(output.strip()) or "(no log output)"


# ---------------------------------------------------------------------------
# Tool 2: read_config
# ---------------------------------------------------------------------------

async def read_config(
    deps: AgentDeps,
    component: str,
) -> str:
    """Read the configuration file for a network component.

    Args:
        deps: Agent dependencies.
        component: One of: amf, smf, upf, pcscf, scscf, icscf, pyhss,
                   dns, dns-ims-zone, ueransim-gnb, ueransim-ue.

    Returns:
        The full configuration file content, or an error message.
    """
    rel_path = _CONFIG_PATHS.get(component)
    if rel_path is None:
        return f"Unknown component '{component}'. Valid components: {', '.join(sorted(_CONFIG_PATHS.keys()))}"

    config_path = deps.repo_root / rel_path
    if not config_path.exists():
        return f"Config file not found: {config_path}"

    return config_path.read_text(errors="replace")


# ---------------------------------------------------------------------------
# Tool 3: get_network_status
# ---------------------------------------------------------------------------

async def get_network_status(
    deps: AgentDeps,
) -> str:
    """Get the status of all network containers.

    Args:
        deps: Agent dependencies.

    Returns:
        JSON string with phase and per-container status.
    """
    tasks = {}
    for name in deps.all_containers:
        tasks[name] = asyncio.create_task(_container_status(name))

    results = {}
    for name, task in tasks.items():
        results[name] = await task

    running = [n for n, s in results.items() if s == "running"]
    down = [n for n, s in results.items() if s != "running"]

    core = {"mongo", "nrf", "scp", "ausf", "udr", "udm", "amf", "smf", "upf",
            "pcf", "dns", "mysql", "pyhss", "icscf", "scscf", "pcscf", "rtpengine"}
    core_up = core.issubset(set(running))
    gnb_up = "nr_gnb" in running
    ues_up = "e2e_ue1" in running and "e2e_ue2" in running

    if core_up and gnb_up and ues_up:
        phase = "ready"
    elif core_up:
        phase = "partial"
    else:
        phase = "down"

    summary = {
        "phase": phase,
        "running": running,
        "down_or_absent": down,
        "containers": results,
    }
    return json.dumps(summary, indent=2)


async def _container_status(name: str) -> str:
    rc, output = await _shell(f"docker inspect -f '{{{{.State.Status}}}}' {name}")
    if rc != 0:
        return "absent"
    return output.strip()


# ---------------------------------------------------------------------------
# Tool 4: query_subscriber
# ---------------------------------------------------------------------------

async def query_subscriber(
    deps: AgentDeps,
    imsi: str,
    domain: str = "both",
) -> str:
    """Query subscriber data from 5G core (MongoDB) and/or IMS (PyHSS).

    Args:
        deps: Agent dependencies.
        imsi: The subscriber's IMSI (e.g. '001011234567891').
        domain: 'core' for 5G only, 'ims' for IMS only, 'both' for both.

    Returns:
        JSON string with subscriber profiles from the requested domains.
    """
    result: dict = {}

    if domain in ("core", "both"):
        mongo_cmd = (
            f"docker exec -i mongo mongosh --quiet open5gs --eval "
            f"\"JSON.stringify(db.subscribers.findOne({{imsi: '{imsi}'}}))\""
        )
        rc, output = await _shell(mongo_cmd)
        if rc == 0 and output.strip() and output.strip() != "null":
            try:
                result["core_5g"] = json.loads(output.strip())
            except json.JSONDecodeError:
                result["core_5g"] = output.strip()
        else:
            result["core_5g"] = None
            result["core_5g_note"] = f"Subscriber {imsi} NOT FOUND in Open5GS MongoDB. This means the UE cannot attach to the 5G core."

    if domain in ("ims", "both"):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # PyHSS subscriber
                resp = await client.get(f"{deps.pyhss_api}/subscriber/imsi/{imsi}")
                if resp.status_code == 200:
                    result["ims_subscriber"] = resp.json()
                else:
                    result["ims_subscriber"] = None
                    result["ims_note"] = f"Subscriber {imsi} NOT FOUND in PyHSS. This means the UE cannot register with IMS for voice calls."

                # IMS subscriber details
                resp2 = await client.get(f"{deps.pyhss_api}/ims_subscriber/ims_subscriber_imsi/{imsi}")
                if resp2.status_code == 200:
                    result["ims_details"] = resp2.json()
        except httpx.ConnectError:
            result["ims_error"] = f"Cannot connect to PyHSS API at {deps.pyhss_api}. Is the pyhss container running?"
        except httpx.TimeoutException:
            result["ims_error"] = f"PyHSS API timeout at {deps.pyhss_api}."

    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool 5: read_env_config
# ---------------------------------------------------------------------------

async def read_env_config(
    deps: AgentDeps,
) -> str:
    """Read network topology and UE credentials from environment files.

    Args:
        deps: Agent dependencies.

    Returns:
        JSON string with network topology, UE info, and IMS domain.
    """
    env = deps.env
    mcc = env.get("MCC", "001")
    mnc = env.get("MNC", "01")
    if len(mnc) == 3:
        ims_domain = f"ims.mnc{mnc}.mcc{mcc}.3gppnetwork.org"
    else:
        ims_domain = f"ims.mnc0{mnc}.mcc{mcc}.3gppnetwork.org"

    # Extract key IPs
    network = {
        "mcc": mcc,
        "mnc": mnc,
        "ims_domain": ims_domain,
        "test_network": env.get("TEST_NETWORK", "172.22.0.0/24"),
    }
    # Collect all *_IP variables
    for key, val in sorted(env.items()):
        if key.endswith("_IP"):
            network[key.lower()] = val

    ue1 = {
        "imsi": env.get("UE1_IMSI", ""),
        "msisdn": env.get("UE1_MSISDN", ""),
        "ip": env.get("UE1_IP", ""),
    }
    ue2 = {
        "imsi": env.get("UE2_IMSI", ""),
        "msisdn": env.get("UE2_MSISDN", ""),
        "ip": env.get("UE2_IP", ""),
    }

    result = {
        "network": network,
        "ue1": ue1,
        "ue2": ue2,
        "ims_domain": ims_domain,
    }
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Tool 6: search_logs
# ---------------------------------------------------------------------------

async def search_logs(
    deps: AgentDeps,
    pattern: str,
    containers: list[str] | None = None,
    since: str | None = None,
) -> str:
    """Search for a pattern across multiple container logs.

    Unlike read_container_logs which reads the tail of one container,
    this tool searches across all (or specified) containers for a
    specific pattern. Essential for tracing a SIP Call-ID, IMSI, or
    error keyword across the entire stack.

    Args:
        deps: Agent dependencies.
        pattern: Search pattern (case-insensitive). Can be a Call-ID,
                 IMSI, SIP method, error keyword, etc.
        containers: Optional list of containers to search. If None,
                    searches all known containers.
        since: Optional time filter for docker logs (e.g. '5m', '1h').

    Returns:
        Matching lines grouped by container, with container name prefix.
    """
    targets = containers or deps.all_containers

    # Validate container names
    invalid = [c for c in targets if c not in deps.all_containers]
    if invalid:
        return f"Unknown containers: {', '.join(invalid)}. Known: {', '.join(deps.all_containers)}"

    # Search in parallel
    async def _search_one(container: str) -> tuple[str, str]:
        since_flag = f"--since {since}" if since else ""
        cmd = f"docker logs {since_flag} {container} 2>&1 | grep -i -- {_shell_quote(pattern)}"
        rc, output = await _shell(cmd)
        lines = output.strip()
        if not lines:
            return container, ""
        # Prefix each line with container name
        prefixed = "\n".join(f"[{container}] {line}" for line in lines.splitlines())
        return container, prefixed

    tasks = [_search_one(c) for c in targets]
    results = await asyncio.gather(*tasks)

    all_matches = []
    for container, output in results:
        if output:
            all_matches.append(output)

    if not all_matches:
        searched = ", ".join(targets)
        return f"No matches for '{pattern}' in containers: {searched}"

    combined = "\n".join(all_matches)
    return _truncate(combined)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _shell_quote(s: str) -> str:
    """Minimal shell quoting for grep patterns."""
    import shlex
    return shlex.quote(s)
