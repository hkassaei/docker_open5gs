"""
Docker container lifecycle tools — kill, stop, pause, restart.

Every mutating function returns a dict with:
  - success: bool
  - heal_cmd: str (command to reverse the fault)
  - mechanism: str (exact command that was executed)
  - detail: str (stdout/stderr from the command)

These are framework-agnostic async functions — usable from ADK, Pydantic AI, or plain scripts.
"""

from __future__ import annotations

import logging
import shlex

from ._common import shell, validate_container

log = logging.getLogger("chaos-tools.docker")


async def docker_kill(container: str) -> dict:
    """Send SIGKILL to a container (immediate death).

    Args:
        container: Container name (e.g. 'pcscf', 'amf').

    Returns:
        {success, mechanism, heal_cmd, detail}
    """
    safe = validate_container(container)
    mechanism = f"docker kill {safe}"
    rc, output = await shell(mechanism)
    return {
        "success": rc == 0,
        "mechanism": mechanism,
        "heal_cmd": f"docker start {safe}",
        "detail": output,
    }


async def docker_stop(container: str, timeout: int = 0) -> dict:
    """Send SIGTERM then SIGKILL after timeout.

    Args:
        container: Container name.
        timeout: Grace period in seconds before SIGKILL (default 0 = immediate).

    Returns:
        {success, mechanism, heal_cmd, detail}
    """
    safe = validate_container(container)
    timeout = max(0, int(timeout))
    mechanism = f"docker stop -t {timeout} {safe}"
    rc, output = await shell(mechanism)
    return {
        "success": rc == 0,
        "mechanism": mechanism,
        "heal_cmd": f"docker start {safe}",
        "detail": output,
    }


async def docker_pause(container: str) -> dict:
    """Freeze a container in place (SIGSTOP). All processes suspended.

    Args:
        container: Container name.

    Returns:
        {success, mechanism, heal_cmd, detail}
    """
    safe = validate_container(container)
    mechanism = f"docker pause {safe}"
    rc, output = await shell(mechanism)
    return {
        "success": rc == 0,
        "mechanism": mechanism,
        "heal_cmd": f"docker unpause {safe}",
        "detail": output,
    }


async def docker_restart(container: str) -> dict:
    """Stop and start a container (simulates NF restart / upgrade).

    Args:
        container: Container name.

    Returns:
        {success, mechanism, heal_cmd, detail}
    """
    safe = validate_container(container)
    mechanism = f"docker restart {safe}"
    rc, output = await shell(mechanism)
    return {
        "success": rc == 0,
        "mechanism": mechanism,
        "heal_cmd": f"docker start {safe}",
        "detail": output,
    }


async def docker_start(container: str) -> dict:
    """Start a stopped container (heal action).

    Args:
        container: Container name.

    Returns:
        {success, mechanism, detail}
    """
    safe = validate_container(container)
    mechanism = f"docker start {safe}"
    rc, output = await shell(mechanism)
    return {
        "success": rc == 0,
        "mechanism": mechanism,
        "detail": output,
    }


async def docker_unpause(container: str) -> dict:
    """Unpause a paused container (heal action).

    Args:
        container: Container name.

    Returns:
        {success, mechanism, detail}
    """
    safe = validate_container(container)
    mechanism = f"docker unpause {safe}"
    rc, output = await shell(mechanism)
    return {
        "success": rc == 0,
        "mechanism": mechanism,
        "detail": output,
    }


async def docker_inspect_status(container: str) -> str:
    """Return the container's current status.

    Returns one of: 'running', 'exited', 'paused', 'restarting', 'dead', 'absent'.
    """
    safe = shlex.quote(container)
    rc, output = await shell(
        f"docker inspect -f '{{{{.State.Status}}}}' {safe}"
    )
    if rc != 0:
        return "absent"
    return output.strip()


async def docker_get_pid(container: str) -> int | None:
    """Return the container's main process PID, or None if not running.

    Used by network tools for nsenter.
    """
    safe = shlex.quote(container)
    rc, output = await shell(
        f"docker inspect -f '{{{{.State.Pid}}}}' {safe}"
    )
    if rc != 0 or not output.strip():
        return None
    try:
        pid = int(output.strip())
    except ValueError:
        return None
    return pid if pid > 0 else None
