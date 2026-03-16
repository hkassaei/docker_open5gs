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
        "AGENT_MODEL", "anthropic:claude-sonnet-4-20250514"
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
        ],
        retries=2,
    )

    return agent
