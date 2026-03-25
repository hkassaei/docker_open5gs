"""
Telecom Troubleshooting Agent — built with Pydantic AI.

Usage:
    from operate.agentic_ops.agent import create_agent
    from operate.agentic_ops.models import AgentDeps

    agent = create_agent()
    result = await agent.run("Why can't UE2 register?", deps=deps)
    print(result.output)  # Diagnosis object
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_ai import Agent, RunContext, Tool

from .models import AgentDeps, Diagnosis
from . import tools as t

# ---------------------------------------------------------------------------
# System prompt — loaded from markdown file at import time
# ---------------------------------------------------------------------------

_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def _load_system_prompt() -> str:
    """Load the system prompt from prompts/system.md."""
    prompt_file = _PROMPT_DIR / "system.md"
    if prompt_file.exists():
        return prompt_file.read_text()
    raise FileNotFoundError(f"System prompt not found: {prompt_file}")


SYSTEM_PROMPT = _load_system_prompt()


# ---------------------------------------------------------------------------
# Tool wrappers — bridge between Pydantic AI's RunContext and our tool funcs
# ---------------------------------------------------------------------------

async def _tool_read_container_logs(
    ctx: RunContext[AgentDeps],
    container: str,
    tail: int = 200,
    grep: str | None = None,
) -> str:
    """Read recent logs from a Docker container.

    Args:
        container: Container name (e.g. 'pcscf', 'scscf', 'e2e_ue1', 'amf').
        tail: Number of recent lines to return (default 200).
        grep: Optional pattern to filter log lines (case-insensitive).
    """
    return await t.read_container_logs(ctx.deps, container, tail, grep)


async def _tool_read_config(
    ctx: RunContext[AgentDeps],
    component: str,
) -> str:
    """Read the configuration file for a network component.

    Args:
        component: One of: amf, smf, upf, pcscf, scscf, icscf, pyhss,
                   dns, dns-ims-zone, ueransim-gnb, ueransim-ue.
    """
    return await t.read_config(ctx.deps, component)


async def _tool_get_network_status(
    ctx: RunContext[AgentDeps],
) -> str:
    """Get the status of all network containers (running/exited/absent)."""
    return await t.get_network_status(ctx.deps)


async def _tool_query_subscriber(
    ctx: RunContext[AgentDeps],
    imsi: str,
    domain: str = "both",
) -> str:
    """Query subscriber data from 5G core (MongoDB) and/or IMS (PyHSS).

    Args:
        imsi: The subscriber's IMSI (e.g. '001011234567891').
        domain: 'core' for 5G only, 'ims' for IMS only, 'both' for both.
    """
    return await t.query_subscriber(ctx.deps, imsi, domain)


async def _tool_read_env_config(
    ctx: RunContext[AgentDeps],
) -> str:
    """Read network topology, IPs, PLMN, and UE credentials from environment files.

    Call this FIRST in every investigation to discover the live topology.
    """
    return await t.read_env_config(ctx.deps)


async def _tool_search_logs(
    ctx: RunContext[AgentDeps],
    pattern: str,
    containers: list[str] | None = None,
    since: str | None = None,
) -> str:
    """Search for a pattern across multiple container logs.

    Essential for tracing a SIP Call-ID, IMSI, or error keyword across the
    entire stack in a single call.

    Args:
        pattern: Search pattern (case-insensitive). Can be a Call-ID,
                 IMSI, SIP method, error keyword, etc.
        containers: Optional list of containers to search. Searches all if None.
        since: Optional time filter (e.g. '5m', '1h').
    """
    return await t.search_logs(ctx.deps, pattern, containers, since)


async def _tool_query_prometheus(
    ctx: RunContext[AgentDeps],
    query: str,
) -> str:
    """Query Prometheus for 5G core NF metrics using PromQL.

    Call this EARLY — metrics are the fastest way to triage. A 3-second query
    replaces 30 minutes of log analysis. Common queries:
      - fivegs_ep_n3_gtp_indatapktn3upf (GTP data plane packets — 0 means dead)
      - ran_ue (connected UEs), gnb (connected gNBs)
      - fivegs_smffunction_sm_sessionnbr (active PDU sessions)
      - fivegs_amffunction_amf_authfail (authentication failures)

    Args:
        query: PromQL query string (e.g. 'ran_ue', 'fivegs_ep_n3_gtp_indatapktn3upf').
    """
    return await t.query_prometheus(ctx.deps, query)


async def _tool_get_nf_metrics(
    ctx: RunContext[AgentDeps],
) -> str:
    """Get a full metrics snapshot across ALL network functions in one call.

    Collects from Prometheus (5G core), kamcmd (IMS Kamailio), RTPEngine,
    PyHSS, and MongoDB. This is the 'radiograph' — a quick health overview
    of the entire stack. Use BEFORE diving into logs.

    Returns per-NF metrics with badges and data sources.
    """
    return await t.get_nf_metrics(ctx.deps)


async def _tool_run_kamcmd(
    ctx: RunContext[AgentDeps],
    container: str,
    command: str,
) -> str:
    """Run a kamcmd command inside a Kamailio container to inspect runtime state.

    Provides access to internal state not visible in logs: Diameter peer
    connections, registered contacts, transaction stats, dialog state.

    Args:
        container: Kamailio container ('pcscf', 'icscf', or 'scscf').
        command: kamcmd command. Examples:
            - cdp.list_peers — Diameter peer connections and state
            - ulscscf.showimpu sip:imsi@domain — S-CSCF registration lookup
            - stats.get_statistics all — all stats
            - tm.stats — SIP transaction statistics
    """
    return await t.run_kamcmd(ctx.deps, container, command)


async def _tool_read_running_config(
    ctx: RunContext[AgentDeps],
    container: str,
    grep: str | None = None,
) -> str:
    """Read the ACTUAL config from a running container (not the repo copy).

    The running config may differ from the repo if the container was restarted
    from a volume mount. Use this to verify critical settings like
    udp_mtu_try_proto, auth algorithms, listen addresses, etc.

    Args:
        container: Container name (pcscf, icscf, scscf, amf, smf, upf).
        grep: Optional pattern to filter config lines (case-insensitive).
    """
    return await t.read_running_config(ctx.deps, container, grep)


async def _tool_check_process_listeners(
    ctx: RunContext[AgentDeps],
    container: str,
) -> str:
    """Check what ports and protocols a container's processes are listening on.

    Shows TCP and UDP listeners. Essential for diagnosing transport mismatches
    — e.g., when P-CSCF sends SIP via TCP but the UE only listens on UDP.

    Args:
        container: Container name (e.g. 'e2e_ue1', 'pcscf', 'scscf').
    """
    return await t.check_process_listeners(ctx.deps, container)


async def _tool_check_tc_rules(
    ctx: RunContext[AgentDeps],
    container: str,
) -> str:
    """Check for active traffic control (tc) rules on a container's network interface.

    CRITICAL: Call this FIRST on any container showing timeouts or slow
    responses. Detects injected latency (netem delay), packet loss (netem loss),
    bandwidth limits (tbf), or corruption. In a healthy Docker network, RTT is
    <1ms — if netem rules are present, they explain all timeout behavior.

    Args:
        container: Container name (e.g. 'pcscf', 'upf', 'scscf').
    """
    return await t.check_tc_rules(ctx.deps, container)


async def _tool_measure_rtt(
    ctx: RunContext[AgentDeps],
    container: str,
    target_ip: str,
) -> str:
    """Measure round-trip time (RTT) from a container to a target IP.

    Normal Docker bridge RTT is <1ms. Elevated RTT (>10ms) indicates injected
    latency or congestion. Use to confirm tc netem faults or measure impact.

    Args:
        container: Source container name (e.g. 'pcscf', 'icscf').
        target_ip: Target IP address to ping (e.g. '172.22.0.19').
    """
    return await t.measure_rtt(ctx.deps, container, target_ip)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

def create_agent(model: str | None = None) -> Agent[AgentDeps, Diagnosis]:
    """Create the telecom troubleshooting agent.

    Args:
        model: Model identifier string (e.g. 'anthropic:claude-sonnet-4-20250514').
               Falls back to AGENT_MODEL env var, then to a default.

    Returns:
        A Pydantic AI Agent configured with telecom tools and knowledge.
    """
    model_id = model or os.environ.get(
        "AGENT_MODEL", "google-vertex:gemini-2.5-pro"
    )

    agent: Agent[AgentDeps, Diagnosis] = Agent(
        model_id,
        instructions=SYSTEM_PROMPT,
        deps_type=AgentDeps,
        output_type=Diagnosis,
        tools=[
            Tool(_tool_read_container_logs, takes_ctx=True),
            Tool(_tool_read_config, takes_ctx=True),
            Tool(_tool_get_network_status, takes_ctx=True),
            Tool(_tool_query_subscriber, takes_ctx=True),
            Tool(_tool_read_env_config, takes_ctx=True),
            Tool(_tool_search_logs, takes_ctx=True),
            Tool(_tool_query_prometheus, takes_ctx=True),
            Tool(_tool_get_nf_metrics, takes_ctx=True),
            Tool(_tool_run_kamcmd, takes_ctx=True),
            Tool(_tool_read_running_config, takes_ctx=True),
            Tool(_tool_check_process_listeners, takes_ctx=True),
            Tool(_tool_check_tc_rules, takes_ctx=True),
            Tool(_tool_measure_rtt, takes_ctx=True),
        ],
        retries=2,
    )

    return agent
