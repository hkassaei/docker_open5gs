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
# Tool 7: query_prometheus
# ---------------------------------------------------------------------------

async def query_prometheus(
    deps: AgentDeps,
    query: str,
) -> str:
    """Query Prometheus for 5G core NF metrics using PromQL.

    **Call this EARLY in every investigation.** Prometheus metrics are the fastest
    way to triage — a 3-second query replaces 30 minutes of log analysis.
    Metrics tell you WHAT is broken. Logs tell you WHY. Start with WHAT.

    The stack scrapes metrics from AMF, SMF, UPF, PCF every 5 seconds.

    Args:
        deps: Agent dependencies.
        query: A PromQL query string. Common queries:

            Data plane health (check FIRST for call/connectivity issues):
              fivegs_ep_n3_gtp_indatapktn3upf — GTP incoming packets at UPF (0 = data plane dead)
              fivegs_ep_n3_gtp_outdatapktn3upf — GTP outgoing packets at UPF

            Session counts:
              fivegs_upffunction_upf_sessionnbr — UPF active sessions
              fivegs_smffunction_sm_sessionnbr — SMF active sessions

            UE/gNB counts:
              ran_ue — RAN-connected UEs at AMF
              gnb — connected gNBs at AMF
              amf_session — AMF session count

            Registration stats:
              fivegs_amffunction_rm_reginitreq — 5G NAS initial registration requests
              fivegs_amffunction_rm_reginitsucc — 5G NAS initial registration successes
              fivegs_amffunction_amf_authreq — authentication requests
              fivegs_amffunction_amf_authfail — authentication failures

            PDU session stats:
              fivegs_smffunction_sm_pdusessioncreationreq — PDU session requests
              fivegs_smffunction_sm_pdusessioncreationsucc — PDU session successes

            PCF policy sessions:
              fivegs_pcffunction_pa_sessionnbr — PCF policy sessions

    Returns:
        Query result as formatted text showing metric name, labels, and value.
        Returns error message if Prometheus is unreachable.
    """
    prom_ip = deps.env.get("METRICS_IP", "172.22.0.36")
    prom_url = f"http://{prom_ip}:9090"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{prom_url}/api/v1/query",
                params={"query": query},
            )
            if resp.status_code != 200:
                return f"Prometheus returned HTTP {resp.status_code}: {resp.text[:200]}"

            body = resp.json()
            status = body.get("status", "")
            if status != "success":
                return f"Prometheus query failed: {body.get('error', 'unknown error')}"

            results = body.get("data", {}).get("result", [])
            if not results:
                return f"No results for query '{query}'. The metric may not exist or have no data."

            # Format results as readable text
            lines = []
            for r in results:
                metric = r.get("metric", {})
                value = r.get("value", [None, None])
                metric_name = metric.get("__name__", query)
                labels = {k: v for k, v in metric.items() if k != "__name__"}
                label_str = ", ".join(f"{k}={v}" for k, v in labels.items())
                val = value[1] if len(value) > 1 else "?"
                if label_str:
                    lines.append(f"{metric_name}{{{label_str}}} = {val}")
                else:
                    lines.append(f"{metric_name} = {val}")

            return "\n".join(lines)

    except httpx.ConnectError:
        return f"Cannot connect to Prometheus at {prom_url}. Is the metrics container running?"
    except httpx.TimeoutException:
        return f"Prometheus query timed out at {prom_url}."
    except Exception as e:
        return f"Prometheus query error: {e}"


# ---------------------------------------------------------------------------
# Tool 8: get_nf_metrics
# ---------------------------------------------------------------------------

async def get_nf_metrics(
    deps: AgentDeps,
) -> str:
    """Get a full metrics snapshot across ALL network functions in one call.

    Collects metrics from:
      - Prometheus (AMF, SMF, UPF, PCF) — 5G core KPIs
      - Kamailio kamcmd (P-CSCF, I-CSCF, S-CSCF) — IMS stats
      - RTPEngine rtpengine-ctl — media relay stats
      - PyHSS REST API — IMS subscriber count
      - MongoDB — 5G subscriber count

    This is the "radiograph" — a quick health overview of the entire stack.
    Use this BEFORE diving into logs. If a metric is zero when it should be
    nonzero (e.g., GTP packets = 0 but sessions > 0), that's an anomaly
    worth investigating.

    Returns:
        JSON object with per-NF metrics, badges, and data sources.
        Each NF entry has: {metrics: {key: value}, badge: "summary", source: "prometheus|kamcmd|api"}
    """
    import sys
    gui_dir = str(deps.repo_root / "operate" / "gui")
    if gui_dir not in sys.path:
        sys.path.insert(0, gui_dir)

    try:
        from metrics import MetricsCollector
        env = deps.env
        collector = MetricsCollector(env)
        collector._cache_ts = 0.0  # Force fresh collection
        data = await asyncio.wait_for(collector.collect(), timeout=15)

        if not data:
            return "No metrics collected. Prometheus and/or containers may be down."

        # Format as readable text
        lines = []
        for nf, info in sorted(data.items()):
            badge = info.get("badge", "")
            source = info.get("source", "?")
            metrics = info.get("metrics", {})
            badge_str = f" [{badge}]" if badge else ""
            lines.append(f"\n{nf.upper()}{badge_str} (via {source}):")
            for k, v in sorted(metrics.items()):
                if k.startswith("_"):
                    continue
                lines.append(f"  {k} = {v}")

        return "\n".join(lines)

    except asyncio.TimeoutError:
        return "Metrics collection timed out (15s). Some NFs may be unreachable."
    except ImportError as e:
        return f"Cannot import MetricsCollector: {e}"
    except Exception as e:
        return f"Metrics collection error: {e}"


# ---------------------------------------------------------------------------
# Tool 9: run_kamcmd (renumbered from 7)
# ---------------------------------------------------------------------------

async def run_kamcmd(
    deps: AgentDeps,
    container: str,
    command: str,
) -> str:
    """Run a kamcmd command inside a Kamailio container (pcscf, icscf, scscf).

    This provides access to Kamailio's internal runtime state that is NOT
    visible in logs or config files: Diameter peer status, usrloc registered
    contacts, transaction stats, shared memory usage, dialog state, etc.

    Args:
        deps: Agent dependencies.
        container: Kamailio container name ('pcscf', 'icscf', or 'scscf').
        command: kamcmd command string. Common commands:
            - cdp.list_peers — Diameter peer connections and state
            - ulscscf.showimpu <sip:imsi@domain> — S-CSCF registration lookup
            - stats.get_statistics all — all Kamailio stats
            - tm.stats — SIP transaction statistics
            - dlg.list — active SIP dialogs

    Returns:
        Command output as string, or error message.
    """
    valid_containers = {"pcscf", "icscf", "scscf"}
    if container not in valid_containers:
        return f"Container must be one of {valid_containers}, got '{container}'"

    if container not in deps.all_containers:
        return f"Container '{container}' not in known containers list"

    cmd = f"docker exec {container} kamcmd {command}"
    rc, output = await _shell(cmd)

    if rc != 0 and "not found" in output:
        return f"kamcmd command '{command}' not found. Try: cdp.list_peers, stats.get_statistics all, tm.stats"

    result = _truncate(output.strip()) or "(no output)"

    # Annotate I_Open Diameter peer state — this is a known cosmetic artifact
    # of the PyHSS/Kamailio interop in this stack, not a real failure.
    if "cdp" in command and "I_Open" in result:
        result += (
            "\n\n--- NOTE ---\n"
            "I_Open is a KNOWN BENIGN display artifact in this stack. "
            "Kamailio's CDP module shows I_Open for PyHSS peers even when "
            "the Diameter connection is fully functional. This has been "
            "verified: PyHSS processes 242+ Diameter messages/hour on these "
            "connections, and UE registration (UAR/UAA, MAR/SAR) succeeds. "
            "Do NOT treat I_Open as a root cause. To verify the connection "
            "is working, check PyHSS logs for recent Diameter message processing."
        )

    return result


# ---------------------------------------------------------------------------
# Tool 8: read_running_config
# ---------------------------------------------------------------------------

async def read_running_config(
    deps: AgentDeps,
    container: str,
    grep: str | None = None,
) -> str:
    """Read the ACTUAL configuration from a running container (not the repo copy).

    This reads the config that the process is currently using, which may differ
    from the repo version if the container was restarted from a volume mount
    or if runtime changes were applied.

    Use this when you need to verify what config a container is ACTUALLY running
    with, especially for settings like udp_mtu_try_proto, auth algorithms, etc.

    Args:
        deps: Agent dependencies.
        container: Container name.
        grep: Optional pattern to filter config lines (case-insensitive).

    Returns:
        Config content (or filtered lines), or error message.
    """
    # Map containers to their config file paths inside the container
    config_paths = {
        "pcscf": "/etc/kamailio_pcscf/kamailio_pcscf.cfg",
        "icscf": "/etc/kamailio_icscf/kamailio_icscf.cfg",
        "scscf": "/etc/kamailio_scscf/kamailio_scscf.cfg",
        "amf": "/open5gs/install/etc/open5gs/amf.yaml",
        "smf": "/open5gs/install/etc/open5gs/smf.yaml",
        "upf": "/open5gs/install/etc/open5gs/upf.yaml",
    }

    config_path = config_paths.get(container)
    if not config_path:
        return f"No known config path for container '{container}'. Known: {', '.join(sorted(config_paths.keys()))}"

    if grep:
        cmd = f"docker exec {container} grep -in -- {_shell_quote(grep)} {config_path}"
    else:
        cmd = f"docker exec {container} cat {config_path}"

    rc, output = await _shell(cmd)
    if rc != 0:
        return f"Failed to read config from {container}:{config_path} — {output.strip()}"

    return _truncate(output.strip()) or "(empty config or no matches)"


# ---------------------------------------------------------------------------
# Tool 9: check_process_listeners
# ---------------------------------------------------------------------------

async def check_process_listeners(
    deps: AgentDeps,
    container: str,
) -> str:
    """Check what network ports and protocols a container's processes are listening on.

    Shows UDP and TCP listeners. Essential for diagnosing transport mismatches
    — e.g., when a SIP proxy sends via TCP but the UE only listens on UDP.

    Args:
        deps: Agent dependencies.
        container: Container name.

    Returns:
        Output of ss -tulnp showing all listeners, or error message.
    """
    if container not in deps.all_containers:
        return f"Unknown container '{container}'. Known: {', '.join(deps.all_containers)}"

    cmd = f"docker exec {container} ss -tulnp"
    rc, output = await _shell(cmd)

    if rc != 0:
        # ss might not be available, try netstat
        cmd = f"docker exec {container} netstat -tulnp"
        rc, output = await _shell(cmd)

    if rc != 0:
        return f"Neither ss nor netstat available in {container}. Output: {output.strip()}"

    return output.strip() or "(no listeners found)"


# ---------------------------------------------------------------------------
# Tool 10: check_tc_rules
# ---------------------------------------------------------------------------

async def check_tc_rules(
    deps: AgentDeps,
    container: str,
) -> str:
    """Check for active traffic control (tc) rules on a container's network interface.

    This detects injected network faults: latency (netem delay), packet loss
    (netem loss), bandwidth limits (tbf), or corruption (netem corrupt).

    **CRITICAL: Call this FIRST on any container showing timeouts or slow
    responses.** A tc netem rule is the #1 cause of latency-induced timeouts
    in this environment. If tc rules are present, they are almost certainly
    the root cause — do not investigate application-layer issues until you
    have ruled out tc rules.

    In a healthy Docker network, RTT between containers is <1ms. If you see
    netem delay rules, that explains any timeout behavior.

    Args:
        deps: Agent dependencies.
        container: Container name (e.g. 'pcscf', 'upf', 'scscf').

    Returns:
        tc qdisc output showing active rules. "noqueue" or "fq_codel" means
        no artificial rules are present. "netem" or "tbf" means a fault is
        active.
    """
    if container not in deps.all_containers:
        return f"Unknown container '{container}'. Known: {', '.join(deps.all_containers)}"

    # Get the container's PID to enter its network namespace
    rc, pid_out = await _shell(f"docker inspect -f '{{{{.State.Pid}}}}' {container}")
    pid = pid_out.strip()
    if rc != 0 or not pid or pid == "0":
        return f"Cannot get PID for container '{container}' — is it running? (status: {pid_out.strip()})"

    cmd = f"sudo nsenter -t {pid} -n tc qdisc show dev eth0"
    rc, output = await _shell(cmd)

    if rc != 0:
        return f"Failed to check tc rules on {container}: {output.strip()}"

    result = output.strip()
    if not result:
        return f"No tc rules found on {container} (interface may not exist)."

    # Annotate the result for the LLM
    if "netem" in result:
        result += "\n\n⚠ NETEM RULES DETECTED — this container has artificial network faults (latency/loss/corruption) injected."
    elif "tbf" in result:
        result += "\n\n⚠ TBF RULES DETECTED — this container has artificial bandwidth limits."
    else:
        result += "\n\n✓ No artificial network faults detected on this container."

    return result


# ---------------------------------------------------------------------------
# Tool 11: measure_rtt
# ---------------------------------------------------------------------------

async def measure_rtt(
    deps: AgentDeps,
    container: str,
    target_ip: str,
) -> str:
    """Measure round-trip time (RTT) from a container to a target IP.

    In a healthy Docker bridge network, RTT between any two containers is
    <1ms. If RTT is elevated (>10ms), it indicates network latency injection
    (tc netem) or severe congestion.

    Use this to confirm latency faults detected by check_tc_rules, or to
    measure the actual impact of injected latency on specific paths.

    Args:
        deps: Agent dependencies.
        container: Source container name (e.g. 'pcscf', 'icscf').
        target_ip: Target IP address to ping (e.g. '172.22.0.19').

    Returns:
        Ping output with RTT statistics, or error message.
    """
    if container not in deps.all_containers:
        return f"Unknown container '{container}'. Known: {', '.join(deps.all_containers)}"

    cmd = f"docker exec {container} ping -c 3 -W 2 {target_ip}"
    rc, output = await _shell(cmd)

    if rc != 0 and "100% packet loss" in output:
        return f"Target {target_ip} is UNREACHABLE from {container}:\n{output.strip()}"
    if rc != 0:
        return f"Ping failed from {container} to {target_ip}: {output.strip()}"

    return output.strip()


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _shell_quote(s: str) -> str:
    """Minimal shell quoting for grep patterns."""
    import shlex
    return shlex.quote(s)
