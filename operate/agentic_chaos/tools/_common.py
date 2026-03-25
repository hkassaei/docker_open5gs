"""Shared helpers for chaos monkey tool modules."""

from __future__ import annotations

import asyncio
import ipaddress
import shlex

# -------------------------------------------------------------------------
# Known containers (canonical list for the chaos subsystem)
# -------------------------------------------------------------------------

ALL_CONTAINERS: list[str] = [
    "mongo", "nrf", "scp", "ausf", "udr", "udm", "amf", "smf", "upf",
    "pcf", "dns", "mysql", "pyhss", "icscf", "scscf", "pcscf", "rtpengine",
    "nr_gnb", "e2e_ue1", "e2e_ue2",
]

CORE_CONTAINERS: set[str] = {
    "mongo", "nrf", "scp", "ausf", "udr", "udm", "amf", "smf", "upf",
    "pcf", "dns", "mysql", "pyhss", "icscf", "scscf", "pcscf", "rtpengine",
}

LOG_CONTAINERS: list[str] = [
    "amf", "smf", "upf", "pcscf", "icscf", "scscf",
    "pyhss", "nr_gnb", "e2e_ue1", "e2e_ue2",
]


# -------------------------------------------------------------------------
# Shell execution
# -------------------------------------------------------------------------

async def shell(cmd: str, timeout: float = 30) -> tuple[int, str]:
    """Run a shell command, return (returncode, combined output).

    Args:
        cmd: Shell command string.
        timeout: Max seconds to wait. Default 30s.

    Returns:
        (returncode, stdout+stderr combined)
    """
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 1, f"Command timed out after {timeout}s: {cmd[:100]}"
    return proc.returncode or 0, stdout.decode(errors="replace").strip()


# -------------------------------------------------------------------------
# Input validation
# -------------------------------------------------------------------------

def validate_container(container: str) -> str:
    """Validate and sanitize a container name.

    Raises ValueError if the name is not in the known container list.
    Returns the shell-quoted container name.
    """
    if container not in ALL_CONTAINERS:
        raise ValueError(
            f"Unknown container '{container}'. "
            f"Known containers: {', '.join(ALL_CONTAINERS)}"
        )
    return shlex.quote(container)


def validate_ip(ip: str) -> str:
    """Validate an IP address string.

    Raises ValueError if not a valid IPv4/IPv6 address.
    Returns the validated IP string (not quoted — IPs don't need shell quoting).
    """
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise ValueError(f"Invalid IP address: '{ip}'")
    return ip
