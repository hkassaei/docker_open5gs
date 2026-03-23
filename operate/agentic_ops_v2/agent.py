"""
ADK Web UI entry point — exposes the InvestigationDirector as root_agent.

This file is required by `adk web` to discover the agent. Start with:

    cd operate
    .venv/bin/adk web agentic_ops_v2 --port 8074

Then open http://localhost:8074 to interact with the multi-agent pipeline
and see all tool calls, agent state, and LLM conversations.
"""

from .orchestrator import create_investigation_director

root_agent = create_investigation_director()
