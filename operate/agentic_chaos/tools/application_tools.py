"""
Application-level fault injection tools — config corruption, DB faults.

These tools modify application state (configs, database records) rather than
infrastructure (containers, network). They are more surgical but harder to
reverse cleanly.

Every mutating function returns a dict with:
  - success: bool
  - mechanism: str (exact command or action taken)
  - heal_cmd: str (command to reverse, if possible)
  - detail: str (output or description)
"""

from __future__ import annotations

import logging
import shlex

from ._common import shell, validate_container

log = logging.getLogger("chaos-tools.application")


# -------------------------------------------------------------------------
# MongoDB (5G core subscriber store)
# -------------------------------------------------------------------------

async def delete_subscriber_mongo(imsi: str) -> dict:
    """Delete a subscriber from the Open5GS MongoDB database.

    Args:
        imsi: IMSI string (e.g. '001011234567891').

    Returns:
        {success, mechanism, heal_cmd, detail}
    """
    if not imsi.isdigit() or len(imsi) < 10:
        raise ValueError(f"Invalid IMSI: '{imsi}' (must be 10-15 digits)")

    safe_imsi = shlex.quote(imsi)
    mechanism = (
        f"docker exec mongo mongosh --quiet --eval "
        f"\"db.subscribers.deleteOne({{imsi: {safe_imsi}}})\" open5gs"
    )
    rc, output = await shell(mechanism)

    # There's no simple heal for deletion — would need the full subscriber doc
    return {
        "success": rc == 0 and "deletedCount" in output,
        "mechanism": mechanism,
        "heal_cmd": "# Manual: re-provision subscriber via provision.sh",
        "detail": output,
    }


async def count_subscribers_mongo() -> dict:
    """Count subscribers in the Open5GS MongoDB database.

    Returns:
        {success, count, detail}
    """
    mechanism = (
        "docker exec mongo mongosh --quiet --eval "
        "\"db.subscribers.countDocuments()\" open5gs"
    )
    rc, output = await shell(mechanism)

    count = None
    if rc == 0 and output.strip().isdigit():
        count = int(output.strip())

    return {
        "success": count is not None,
        "count": count,
        "detail": output,
    }


async def drop_collection_mongo(collection: str = "subscribers") -> dict:
    """Drop a MongoDB collection. DESTRUCTIVE — use with extreme caution.

    Args:
        collection: Collection name (default 'subscribers').

    Returns:
        {success, mechanism, heal_cmd, detail}
    """
    safe_col = shlex.quote(collection)
    mechanism = (
        f"docker exec mongo mongosh --quiet --eval "
        f"\"db.{safe_col}.drop()\" open5gs"
    )
    rc, output = await shell(mechanism)

    return {
        "success": rc == 0,
        "mechanism": mechanism,
        "heal_cmd": "# Manual: re-provision all subscribers via provision.sh",
        "detail": output,
    }


# -------------------------------------------------------------------------
# PyHSS (IMS subscriber store)
# -------------------------------------------------------------------------

async def delete_subscriber_pyhss(
    subscriber_id: int, pyhss_ip: str = "172.22.0.18"
) -> dict:
    """Delete an IMS subscriber from PyHSS via REST API.

    Args:
        subscriber_id: PyHSS subscriber ID (integer).
        pyhss_ip: PyHSS IP address.

    Returns:
        {success, mechanism, heal_cmd, detail}
    """
    subscriber_id = int(subscriber_id)
    url = f"http://{pyhss_ip}:8080/ims_subscriber/{subscriber_id}"
    mechanism = f"curl -s -X DELETE {shlex.quote(url)}"
    rc, output = await shell(mechanism)

    return {
        "success": rc == 0 and "error" not in output.lower(),
        "mechanism": mechanism,
        "heal_cmd": "# Manual: re-provision IMS subscriber via provision.sh",
        "detail": output,
    }


async def count_subscribers_pyhss(pyhss_ip: str = "172.22.0.18") -> dict:
    """Count IMS subscribers in PyHSS via REST API.

    Returns:
        {success, count, detail}
    """
    url = f"http://{pyhss_ip}:8080/ims_subscriber/list"
    mechanism = f"curl -s {shlex.quote(url)}"
    rc, output = await shell(mechanism, timeout=5)

    count = None
    if rc == 0:
        try:
            import json
            data = json.loads(output)
            if isinstance(data, list):
                count = len(data)
        except (json.JSONDecodeError, ValueError):
            pass

    return {
        "success": count is not None,
        "count": count,
        "detail": f"{count} IMS subscribers" if count is not None else output[:200],
    }


# -------------------------------------------------------------------------
# Config corruption
# -------------------------------------------------------------------------

async def corrupt_config(
    container: str, config_path: str, search: str, replace: str
) -> dict:
    """Corrupt a config value inside a running container using Python str.replace().

    Uses `docker exec python3 -c ...` instead of sed to avoid regex escaping
    pitfalls. Does NOT restart the container — caller must restart for the
    change to take effect.

    Args:
        container: Container name.
        config_path: Path to the config file inside the container.
        search: Exact string to find (literal, not regex).
        replace: String to replace with.

    Returns:
        {success, mechanism, heal_cmd, detail}
    """
    validate_container(container)
    safe_container = shlex.quote(container)
    safe_path = shlex.quote(config_path)
    safe_search = shlex.quote(search)
    safe_replace = shlex.quote(replace)

    # Use Python inside the container for safe string replacement (no regex edge cases)
    py_script = (
        f"p={safe_path}; "
        f"t=open(p).read(); "
        f"n=t.replace({safe_search},{safe_replace}); "
        f"open(p,'w').write(n); "
        f"print(f'replaced {{t.count({safe_search})}} occurrences')"
    )
    mechanism = f"docker exec {safe_container} python3 -c {shlex.quote(py_script)}"

    # Heal command: reverse the replacement
    py_heal = (
        f"p={safe_path}; "
        f"t=open(p).read(); "
        f"n=t.replace({safe_replace},{safe_search}); "
        f"open(p,'w').write(n); "
        f"print(f'restored {{t.count({safe_replace})}} occurrences')"
    )
    heal_cmd = f"docker exec {safe_container} python3 -c {shlex.quote(py_heal)}"

    rc, output = await shell(mechanism)
    return {
        "success": rc == 0,
        "mechanism": mechanism,
        "heal_cmd": heal_cmd,
        "detail": output or "Config modified",
    }


# -------------------------------------------------------------------------
# VoNR call setup/teardown (for data plane scenarios)
# -------------------------------------------------------------------------

_CALL_SETUP_TIMEOUT = 30  # seconds to wait for call to connect
_PJSUA_FIFO = "/tmp/pjsua_cmd"


async def establish_vonr_call(ims_domain: str, callee_imsi: str) -> dict:
    """Initiate a VoNR call from UE1 to UE2 via pjsua FIFO.

    Sends the make-call command to UE1's pjsua instance, dials UE2's SIP URI,
    and waits for the call to reach CONFIRMED state.

    Args:
        ims_domain: IMS domain (e.g. 'ims.mnc001.mcc001.3gppnetwork.org').
        callee_imsi: Callee's IMSI (e.g. '001011234567892').

    Returns:
        {success, call_uri, detail}
    """
    import asyncio

    call_uri = f"sip:{callee_imsi}@{ims_domain}"

    # Step 1: Send 'm' to enter the make-call menu
    rc, out = await shell(
        f'docker exec e2e_ue1 bash -c "echo m >> {_PJSUA_FIFO}"'
    )
    if rc != 0:
        return {"success": False, "call_uri": call_uri, "detail": f"Failed to send make-call command: {out}"}

    # Wait for pjsua to show the dial prompt
    await asyncio.sleep(3)

    # Step 2: Send the SIP URI to dial
    rc, out = await shell(
        f"docker exec e2e_ue1 bash -c \"echo '{call_uri}' >> {_PJSUA_FIFO}\""
    )
    if rc != 0:
        return {"success": False, "call_uri": call_uri, "detail": f"Failed to send dial command: {out}"}

    # Step 3: Poll UE1 logs for call confirmation
    elapsed = 0
    poll_interval = 2
    while elapsed < _CALL_SETUP_TIMEOUT:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        rc, logs = await shell(
            "docker logs --tail 20 e2e_ue1 2>&1"
        )
        if "CONFIRMED" in logs:
            log.info("VoNR call established: %s → CONFIRMED", call_uri)
            return {
                "success": True,
                "call_uri": call_uri,
                "detail": "Call established and in CONFIRMED state",
            }

    # Timeout — call didn't connect
    return {
        "success": False,
        "call_uri": call_uri,
        "detail": f"Call setup timed out after {_CALL_SETUP_TIMEOUT}s — call did not reach CONFIRMED state",
    }


async def hangup_call() -> dict:
    """Hang up the active VoNR call on UE1 via pjsua FIFO.

    Returns:
        {success, detail}
    """
    rc, out = await shell(
        f'docker exec e2e_ue1 bash -c "echo h >> {_PJSUA_FIFO}"'
    )
    if rc != 0:
        return {"success": False, "detail": f"Failed to send hangup command: {out}"}

    log.info("VoNR call hangup sent")
    return {"success": True, "detail": "Hangup command sent"}
